"""
Handles charging-related data for electric vehicles, tracking charging sessions,
charging states, rates, and power, and recording them in the database.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging
from datetime import timedelta, datetime, timezone

from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm.exc import ObjectDeletedError

from carconnectivity.observable import Observable
from carconnectivity.vehicle import ElectricVehicle
from carconnectivity.charging import Charging
from carconnectivity.charging_connector import ChargingConnector
from carconnectivity.utils.timeout_lock import TimeoutLock

from carconnectivity_plugins.database.agents.base_agent import BaseAgent

from carconnectivity_plugins.database.model.charging_state import ChargingState
from carconnectivity_plugins.database.model.charging_rate import ChargingRate
from carconnectivity_plugins.database.model.charging_power import ChargingPower
from carconnectivity_plugins.database.model.charging_session import ChargingSession
from carconnectivity_plugins.database.model.location import Location
from carconnectivity_plugins.database.model.charging_station import ChargingStation
from carconnectivity_plugins.database.model.battery_temperature import BatteryTemperature

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import EnumAttribute, SpeedAttribute, PowerAttribute, FloatAttribute, TemperatureAttribute

    from carconnectivity_plugins.database.plugin import Plugin
    from carconnectivity_plugins.database.model.vehicle import Vehicle
    from carconnectivity.drive import ElectricDrive

LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.charging_agent")


# pylint: disable=duplicate-code
# pylint: disable-next=too-many-instance-attributes, too-few-public-methods
class ChargingAgent(BaseAgent):
    """
    Agent responsible for tracking and recording vehicle charging sessions and related data.
    This agent monitors various charging-related attributes of an electric vehicle and records
    changes to a database. It tracks charging sessions, charging states, charging rates, charging
    power, connector states, and battery levels.
    The agent creates and manages charging sessions based on:
    - Charging state changes (CHARGING, CONSERVATION)
    - Connector connection/disconnection events
    - Connector lock/unlock events
    - Battery level changes
    - Charging type changes (AC/DC)
    Each charging session records:
    - Start and end timestamps
    - Battery levels at start and end
    - Odometer reading
    - Geographic position and location
    - Charging station information
    - Charging type (AC/DC)
    - Plug connection, disconnection, lock, and unlock timestamps
    The agent handles session continuity logic, allowing sessions to resume after brief
    interruptions (e.g., conservation mode) while creating new sessions for distinct
    charging events.
    Attributes:
        database_plugin (Plugin): Reference to the database plugin for health status updates.
        session_factory (scoped_session[Session]): SQLAlchemy session factory for database operations.
        vehicle (Vehicle): Database model of the vehicle being monitored.
        carconnectivity_vehicle (ElectricVehicle): CarConnectivity vehicle object with live data.
        last_charging_session (Optional[ChargingSession]): Most recent charging session from database.
        last_charging_session_lock (TimeoutLock): Lock for thread-safe charging session updates.
        carconnectivity_last_charging_state (Optional[Charging.ChargingState]): Last observed charging state.
        carconnectivity_last_connector_state (Optional[ChargingConnector.ChargingConnectorConnectionState]):
            Last observed connector connection state.
        carconnectivity_last_connector_lock_state (Optional[ChargingConnector.ChargingConnectorLockState]):
            Last observed connector lock state.
        last_charging_state (Optional[ChargingState]): Most recent charging state record from database.
        last_charging_state_lock (TimeoutLock): Lock for thread-safe charging state updates.
        last_charging_rate (Optional[ChargingRate]): Most recent charging rate record from database.
        last_charging_rate_lock (TimeoutLock): Lock for thread-safe charging rate updates.
        last_charging_power (Optional[ChargingPower]): Most recent charging power record from database.
        last_charging_power_lock (TimeoutLock): Lock for thread-safe charging power updates.
    Raises:
        ValueError: If vehicle or carconnectivity_vehicle is None, or if carconnectivity_vehicle
            is not an ElectricVehicle instance.
    """
    # pylint: disable-next=too-many-statements
    def __init__(self, database_plugin: Plugin, session_factory: scoped_session[Session], vehicle: Vehicle,
                 carconnectivity_vehicle: ElectricVehicle) -> None:
        if vehicle is None or carconnectivity_vehicle is None:
            raise ValueError("Vehicle or its carconnectivity_vehicle attribute is None")
        if not isinstance(carconnectivity_vehicle, ElectricVehicle):
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is not an ElectricVehicle")
        self.database_plugin: Plugin = database_plugin
        self.session_factory: scoped_session[Session] = session_factory
        self.vehicle: Vehicle = vehicle
        self.carconnectivity_vehicle: ElectricVehicle = carconnectivity_vehicle

        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            self.last_charging_session: Optional[ChargingSession] = session.query(ChargingSession).filter(ChargingSession.vehicle == self.vehicle) \
                .order_by(ChargingSession.session_start_date.desc().nulls_first(),
                          ChargingSession.plug_locked_date.desc().nulls_first(),
                          ChargingSession.plug_connected_date.desc().nulls_first()).first()

            self.last_charging_session_lock: TimeoutLock = TimeoutLock()
            self.carconnectivity_last_charging_state: Optional[Charging.ChargingState] = self.carconnectivity_vehicle.charging.state.value
            self.carconnectivity_last_connector_state: Optional[ChargingConnector.ChargingConnectorConnectionState] = self.carconnectivity_vehicle.charging\
                .connector.connection_state.value
            self.carconnectivity_last_connector_lock_state: Optional[ChargingConnector.ChargingConnectorLockState] = self.carconnectivity_vehicle.charging\
                .connector.lock_state.value
            if self.last_charging_session is not None and not self.last_charging_session.is_closed():
                if self.carconnectivity_vehicle.charging.state.value in (Charging.ChargingState.CHARGING, Charging.ChargingState.CONSERVATION) \
                    or (self.carconnectivity_vehicle.charging.connector.connection_state.enabled
                        and self.carconnectivity_vehicle.charging.connector.connection_state.value ==
                        ChargingConnector.ChargingConnectorConnectionState.CONNECTED) \
                    or (self.carconnectivity_vehicle.charging.connector.lock_state.enabled
                        and self.carconnectivity_vehicle.charging.connector.lock_state.value == ChargingConnector.ChargingConnectorLockState.LOCKED):
                    LOG.info("Last charging session for vehicle %s is still open during startup, will continue this session", self.vehicle.vin)
                else:
                    LOG.info("Last charging session for vehicle %s is still open during startup, but we are not charging, ignoring it", self.vehicle.vin)
                    self.last_charging_session = None

            self.last_charging_state: Optional[ChargingState] = session.query(ChargingState).filter(ChargingState.vehicle == self.vehicle)\
                .order_by(ChargingState.first_date.desc()).first()
            self.last_charging_state_lock: TimeoutLock = TimeoutLock()

            self.last_charging_rate: Optional[ChargingRate] = session.query(ChargingRate).filter(ChargingRate.vehicle == self.vehicle)\
                .order_by(ChargingRate.first_date.desc()).first()
            self.last_charging_rate_lock: TimeoutLock = TimeoutLock()

            self.last_charging_power: Optional[ChargingPower] = session.query(ChargingPower).filter(ChargingPower.vehicle == self.vehicle)\
                .order_by(ChargingPower.first_date.desc()).first()
            self.last_charging_power_lock: TimeoutLock = TimeoutLock()

            self.last_battery_temperature: Optional[BatteryTemperature] = session.query(BatteryTemperature).filter(BatteryTemperature.vehicle == self.vehicle) \
                .order_by(BatteryTemperature.first_date.desc()).first()
            self.last_battery_temperature_lock: TimeoutLock = TimeoutLock()

            self.carconnectivity_vehicle.charging.connector.connection_state.add_observer(self.__on_connector_state_change, Observable.ObserverEvent.UPDATED)
            if self.carconnectivity_vehicle.charging.connector.connection_state.enabled:
                self.__on_connector_state_change(self.carconnectivity_vehicle.charging.connector.connection_state, Observable.ObserverEvent.UPDATED)

            self.carconnectivity_vehicle.charging.connector.lock_state.add_observer(self.__on_connector_lock_state_change, Observable.ObserverEvent.UPDATED)
            if self.carconnectivity_vehicle.charging.connector.lock_state.enabled:
                self.__on_connector_lock_state_change(self.carconnectivity_vehicle.charging.connector.lock_state, Observable.ObserverEvent.UPDATED)

            self.carconnectivity_vehicle.charging.state.add_observer(self.__on_charging_state_change, Observable.ObserverEvent.UPDATED)
            if self.carconnectivity_vehicle.charging.state.enabled:
                self.__on_charging_state_change(self.carconnectivity_vehicle.charging.state, Observable.ObserverEvent.UPDATED)

            self.carconnectivity_vehicle.charging.rate.add_observer(self.__on_charging_rate_change, Observable.ObserverEvent.UPDATED)
            if self.carconnectivity_vehicle.charging.rate.enabled:
                self.__on_charging_rate_change(self.carconnectivity_vehicle.charging.rate, Observable.ObserverEvent.UPDATED)

            self.carconnectivity_vehicle.charging.power.add_observer(self.__on_charging_power_change, Observable.ObserverEvent.UPDATED)
            if self.carconnectivity_vehicle.charging.power.enabled:
                self.__on_charging_power_change(self.carconnectivity_vehicle.charging.power, Observable.ObserverEvent.UPDATED)

            self.carconnectivity_vehicle.charging.type.add_observer(self._on_charging_type_change, Observable.ObserverEvent.VALUE_CHANGED)

            electric_drive: Optional[ElectricDrive] = self.carconnectivity_vehicle.get_electric_drive()
            if electric_drive is not None:
                electric_drive.level.add_observer(self._on_battery_level_change, Observable.ObserverEvent.VALUE_CHANGED)

                electric_drive.battery.temperature.add_observer(self.__on_battery_temperature_change, Observable.ObserverEvent.VALUE_CHANGED)
                if electric_drive.battery.temperature.enabled:
                    self.__on_battery_temperature_change(electric_drive.battery.temperature, Observable.ObserverEvent.UPDATED)
        self.session_factory.remove()

    def __del__(self) -> None:
        self.carconnectivity_vehicle.charging.connector.connection_state.remove_observer(self.__on_connector_state_change)
        self.carconnectivity_vehicle.charging.connector.lock_state.remove_observer(self.__on_connector_lock_state_change)
        self.carconnectivity_vehicle.charging.state.remove_observer(self.__on_charging_state_change)
        self.carconnectivity_vehicle.charging.rate.remove_observer(self.__on_charging_rate_change)
        self.carconnectivity_vehicle.charging.power.remove_observer(self.__on_charging_power_change)
        self.carconnectivity_vehicle.charging.type.remove_observer(self._on_charging_type_change)
        electric_drive: Optional[ElectricDrive] = self.carconnectivity_vehicle.get_electric_drive()
        if electric_drive is not None:
            electric_drive.level.remove_observer(self._on_battery_level_change)
            electric_drive.battery.temperature.remove_observer(self.__on_battery_temperature_change)

    # pylint: disable=too-many-branches, too-many-statements
    def __on_charging_state_change(self, element: EnumAttribute[Charging.ChargingState], flags: Observable.ObserverEvent) -> None:
        del flags
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")

        if element.enabled:
            with self.session_factory() as session:
                self.vehicle = session.merge(self.vehicle)
                session.refresh(self.vehicle)
                with self.last_charging_state_lock:
                    if self.last_charging_state is not None:
                        try:
                            self.last_charging_state = session.merge(self.last_charging_state)
                            session.refresh(self.last_charging_state)
                        except ObjectDeletedError:
                            self.last_charging_state = session.query(ChargingState).filter(ChargingState.vehicle == self.vehicle)\
                                .order_by(ChargingState.first_date.desc()).first()
                            if self.last_charging_state is not None:
                                LOG.info('Last charging state for vehicle %s was deleted from database, reloaded last charging state', self.vehicle.vin)
                            else:
                                LOG.info('Last charging state for vehicle %s was deleted from database, no more charging states found', self.vehicle.vin)
                    if element.last_updated is not None \
                            and (self.last_charging_state is None or (self.last_charging_state.state != element.value
                                                                      and element.last_updated > self.last_charging_state.last_date)):
                        new_charging_state: ChargingState = ChargingState(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                          last_date=element.last_updated, state=element.value)
                        try:
                            session.add(new_charging_state)
                            session.commit()
                            LOG.debug('Added new charging state %s for vehicle %s to database', element.value, self.vehicle.vin)
                            self.last_charging_state = new_charging_state
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding charging state for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding charging state for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access

                    elif self.last_charging_state is not None and self.last_charging_state.state == element.value and element.last_updated is not None:
                        if self.last_charging_state.last_date is None or element.last_updated > self.last_charging_state.last_date:
                            try:
                                self.last_charging_state.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated charging state %s for vehicle %s in database', element.value, self.vehicle.vin)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating charging state for vehicle %s in database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access

                    with self.last_charging_session_lock:
                        if self.last_charging_session is not None:
                            try:
                                self.last_charging_session = session.merge(self.last_charging_session)
                                session.refresh(self.last_charging_session)
                            except ObjectDeletedError:
                                self.last_charging_session = session.query(ChargingSession).filter(ChargingSession.vehicle == self.vehicle) \
                                    .order_by(ChargingSession.session_start_date.desc().nulls_first(),
                                              ChargingSession.plug_locked_date.desc().nulls_first(),
                                              ChargingSession.plug_connected_date.desc().nulls_first()).first()

                        if element.value in (Charging.ChargingState.CHARGING, Charging.ChargingState.CONSERVATION) \
                                and self.carconnectivity_last_charging_state not in (Charging.ChargingState.CHARGING, Charging.ChargingState.CONSERVATION):
                            if self.last_charging_session is None or self.last_charging_session.is_closed():
                                # check that we are not resuming an old session
                                allowed_interrupt: timedelta = timedelta(hours=24)
                                # we allow longer CONSERVATION within the session
                                if element.value == Charging.ChargingState.CONSERVATION:
                                    allowed_interrupt = timedelta(hours=300)
                                # We can reuse the session if the vehicle was connected and not disconnected in the meantime
                                # And the session end date was not set or is within the allowed interrupt time
                                # pylint: disable-next=too-many-boolean-expressions
                                if self.last_charging_session is not None \
                                        and not self.last_charging_session.was_disconnected() \
                                        and (self.last_charging_session.session_end_date is None or element.last_changed is None
                                             or self.last_charging_session.session_end_date > (element.last_changed - allowed_interrupt)):
                                    LOG.debug("Continuing existing charging session for vehicle %s", self.vehicle.vin)
                                    try:
                                        self.last_charging_session.session_end_date = None
                                        self.last_charging_session.end_level = None
                                        self._update_session_charging_type(session, self.last_charging_session)
                                        session.commit()
                                    except DatabaseError as err:
                                        session.rollback()
                                        LOG.error('DatabaseError while updating charging session for vehicle %s in database: %s', self.vehicle.vin, err)
                                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                                else:
                                    LOG.info("Starting new charging session for vehicle %s", self.vehicle.vin)
                                    new_session: ChargingSession = ChargingSession(vin=self.vehicle.vin, session_start_date=element.last_changed)
                                    try:
                                        session.add(new_session)
                                        LOG.debug('Added new charging session for vehicle %s to database', self.vehicle.vin)
                                        self._update_session_odometer(session, new_session)
                                        self._update_session_position(session, new_session)
                                        self._update_session_charging_type(session, new_session)
                                        self.last_charging_session = new_session
                                        session.commit()
                                    except IntegrityError as err:
                                        session.rollback()
                                        LOG.error('IntegrityError while adding charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                                    except DatabaseError as err:
                                        session.rollback()
                                        LOG.error('DatabaseError while adding charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                            else:
                                if self.last_charging_session.was_started():
                                    LOG.debug("Continuing existing charging session for vehicle %s", self.vehicle.vin)
                                else:
                                    LOG.debug("Starting charging in existing charging session for vehicle %s", self.vehicle.vin)
                                    try:
                                        if self.last_charging_session.session_start_date is None:
                                            self.last_charging_session.session_start_date = element.last_changed
                                        self._update_session_odometer(session, self.last_charging_session)
                                        self._update_session_position(session, self.last_charging_session)
                                        self._update_session_charging_type(session, self.last_charging_session)
                                        session.commit()
                                    except DatabaseError as err:
                                        session.rollback()
                                        LOG.error('DatabaseError while starting charging session for vehicle %s in database: %s', self.vehicle.vin, err)
                                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                            # Update startlevel at beginning of charging
                            if self.last_charging_session is not None and isinstance(self.carconnectivity_vehicle, ElectricVehicle):
                                electric_drive: Optional[ElectricDrive] = self.carconnectivity_vehicle.get_electric_drive()
                                if electric_drive is not None and electric_drive.level.enabled and electric_drive.level.value is not None:
                                    if self.last_charging_session.start_level is None:
                                        try:
                                            self.last_charging_session.start_level = electric_drive.level.value
                                            session.commit()
                                        except DatabaseError as err:
                                            session.rollback()
                                            LOG.error('DatabaseError while setting start level for vehicle %s in database: %s', self.vehicle.vin, err)
                                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                        elif element.value not in (Charging.ChargingState.CHARGING, Charging.ChargingState.CONSERVATION) \
                                and self.carconnectivity_last_charging_state in (Charging.ChargingState.CHARGING, Charging.ChargingState.CONSERVATION):
                            if self.last_charging_session is not None and not self.last_charging_session.was_ended():
                                LOG.info("Ending charging session for vehicle %s", self.vehicle.vin)
                                try:
                                    self.last_charging_session.session_end_date = element.last_changed
                                    session.commit()
                                except DatabaseError as err:
                                    session.rollback()
                                    LOG.error('DatabaseError while ending charging session for vehicle %s in database: %s', self.vehicle.vin, err)
                                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                                if isinstance(self.carconnectivity_vehicle, ElectricVehicle):
                                    electric_drive: Optional[ElectricDrive] = self.carconnectivity_vehicle.get_electric_drive()
                                    if electric_drive is not None and electric_drive.level.enabled and electric_drive.level.value is not None:
                                        try:
                                            self.last_charging_session.end_level = electric_drive.level.value
                                            session.commit()
                                        except DatabaseError as err:
                                            session.rollback()
                                            LOG.error('DatabaseError while setting start level for vehicle %s in database: %s', self.vehicle.vin, err)
                                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    self.carconnectivity_last_charging_state = element.value
            self.session_factory.remove()

    def __on_charging_rate_change(self, element: SpeedAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
        if element.enabled:
            converted_value: Optional[float] = element.in_locale(locale=self.database_plugin.locale)[0]
            with self.last_charging_rate_lock:
                with self.session_factory() as session:
                    self.vehicle = session.merge(self.vehicle)
                    session.refresh(self.vehicle)
                    if self.last_charging_rate is not None:
                        try:
                            self.last_charging_rate = session.merge(self.last_charging_rate)
                            session.refresh(self.last_charging_rate)
                        except ObjectDeletedError:
                            self.last_charging_rate = session.query(ChargingRate).filter(ChargingRate.vehicle == self.vehicle)\
                                .order_by(ChargingRate.first_date.desc()).first()
                            if self.last_charging_rate is not None:
                                LOG.info('Last charging rate for vehicle %s was deleted from database, reloaded last charging rate', self.vehicle.vin)
                            else:
                                LOG.info('Last charging rate for vehicle %s was deleted from database, no more charging rates found', self.vehicle.vin)
                    if element.last_updated is not None \
                            and (self.last_charging_rate is None or (self.last_charging_rate.rate != converted_value
                                                                     and element.last_updated > self.last_charging_rate.last_date)):
                        new_charging_rate: ChargingRate = ChargingRate(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                       last_date=element.last_updated, rate=converted_value)
                        try:
                            session.add(new_charging_rate)
                            session.commit()
                            LOG.debug('Added new charging rate %s for vehicle %s to database', converted_value, self.vehicle.vin)
                            self.last_charging_rate = new_charging_rate
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding charging rate for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding charging rate for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_charging_rate is not None and self.last_charging_rate.rate == converted_value and element.last_updated is not None:
                        if self.last_charging_rate.last_date is None or element.last_updated > self.last_charging_rate.last_date:
                            try:
                                self.last_charging_rate.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated charging rate %s for vehicle %s in database', converted_value, self.vehicle.vin)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating charging rate for vehicle %s in database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_charging_power_change(self, element: PowerAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
        if element.enabled:
            converted_value: Optional[float] = element.in_locale(locale=self.database_plugin.locale)[0]
            with self.last_charging_power_lock:
                with self.session_factory() as session:
                    self.vehicle = session.merge(self.vehicle)
                    session.refresh(self.vehicle)
                    if self.last_charging_power is not None:
                        try:
                            self.last_charging_power = session.merge(self.last_charging_power)
                            session.refresh(self.last_charging_power)
                        except ObjectDeletedError:
                            self.last_charging_power = session.query(ChargingPower).filter(ChargingPower.vehicle == self.vehicle)\
                                .order_by(ChargingPower.first_date.desc()).first()
                            if self.last_charging_power is not None:
                                LOG.info('Last charging power for vehicle %s was deleted from database, reloaded last charging power', self.vehicle.vin)
                            else:
                                LOG.info('Last charging power for vehicle %s was deleted from database, no more charging powers found', self.vehicle.vin)
                    if element.last_updated is not None \
                            and (self.last_charging_power is None or (self.last_charging_power.power != converted_value
                                                                      and element.last_updated > self.last_charging_power.last_date)):
                        new_charging_power: ChargingPower = ChargingPower(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                          last_date=element.last_updated, power=converted_value)
                        try:
                            session.add(new_charging_power)
                            session.commit()
                            LOG.debug('Added new charging power %s for vehicle %s to database', converted_value, self.vehicle.vin)
                            self.last_charging_power = new_charging_power
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding charging power for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding charging power for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_charging_power is not None and self.last_charging_power.power == converted_value and element.last_updated is not None:
                        if self.last_charging_power.last_date is None or element.last_updated > self.last_charging_power.last_date:
                            try:
                                self.last_charging_power.last_date = element.last_updated
                                LOG.debug('Updated charging power %s for vehicle %s in database', converted_value, self.vehicle.vin)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating charging power for vehicle %s in database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    # pylint: disable=too-many-branches, too-many-statements
    def __on_connector_state_change(self, element: EnumAttribute[ChargingConnector.ChargingConnectorConnectionState], flags: Observable.ObserverEvent) -> None:
        del flags
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")

        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            with self.last_charging_session_lock:
                if self.last_charging_session is not None:
                    try:
                        self.last_charging_session = session.merge(self.last_charging_session)
                        session.refresh(self.last_charging_session)
                    except ObjectDeletedError:
                        self.last_charging_session = session.query(ChargingSession).filter(ChargingSession.vehicle == self.vehicle) \
                            .order_by(ChargingSession.session_start_date.desc().nulls_first(),
                                      ChargingSession.plug_locked_date.desc().nulls_first(),
                                      ChargingSession.plug_connected_date.desc().nulls_first()).first()
                        if self.last_charging_session is not None:
                            LOG.info('Last charging session for vehicle %s was deleted from database, reloaded last charging session', self.vehicle.vin)
                        else:
                            LOG.info('Last charging session for vehicle %s was deleted from database, no more charging sessions found', self.vehicle.vin)
                if element.value == ChargingConnector.ChargingConnectorConnectionState.CONNECTED \
                        and self.carconnectivity_last_connector_state is not None \
                        and self.carconnectivity_last_connector_state != ChargingConnector.ChargingConnectorConnectionState.CONNECTED:
                    if self.last_charging_session is None or self.last_charging_session.is_closed():
                        LOG.info("Starting new charging session for vehicle %s  due to connector connected state", self.vehicle.vin)
                        new_session: ChargingSession = ChargingSession(vin=self.vehicle.vin, plug_connected_date=element.last_changed)
                        try:
                            session.add(new_session)
                            self._update_session_odometer(session, new_session)
                            self._update_session_position(session, new_session)
                            session.commit()
                            LOG.debug('Added new charging session for vehicle %s to database', self.vehicle.vin)
                            self.last_charging_session = new_session
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif not self.last_charging_session.was_connected():
                        LOG.debug("Continuing existing charging session for vehicle %s, writing connected date", self.vehicle.vin)
                        try:
                            self.last_charging_session.plug_connected_date = element.last_changed
                            self._update_session_odometer(session, self.last_charging_session)
                            self._update_session_position(session, self.last_charging_session)
                            session.commit()
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while starting charging session for vehicle %s in database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                elif element.value != ChargingConnector.ChargingConnectorConnectionState.CONNECTED \
                        and self.carconnectivity_last_connector_state == ChargingConnector.ChargingConnectorConnectionState.CONNECTED:
                    if self.last_charging_session is not None and not self.last_charging_session.was_disconnected():
                        LOG.info("Writing plug disconnected date for charging session of vehicle %s", self.vehicle.vin)
                        try:
                            self.last_charging_session.plug_disconnected_date = element.last_changed
                            session.commit()
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while ending charging session for vehicle %s in database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                # Create charging session when connected at startup
                elif element.value == ChargingConnector.ChargingConnectorConnectionState.CONNECTED \
                        and self.carconnectivity_last_connector_state == ChargingConnector.ChargingConnectorConnectionState.CONNECTED:
                    if self.last_charging_session is None or self.last_charging_session.is_closed():
                        # when the incoming connected state was during the last session, this is a continuation
                        if self.last_charging_session is None or element.last_changed is not None and element.last_changed > \
                                (self.last_charging_session.session_end_date
                                 or self.last_charging_session.plug_unlocked_date
                                 or datetime.min.replace(tzinfo=timezone.utc)):
                            LOG.info("Starting new charging session for vehicle %s due to connector connected state on startup", self.vehicle.vin)
                            new_session: ChargingSession = ChargingSession(vin=self.vehicle.vin, plug_connected_date=element.last_changed)
                            try:
                                session.add(new_session)
                                self._update_session_odometer(session, new_session)
                                self._update_session_position(session, new_session)
                                session.commit()
                                LOG.debug('Added new charging session for vehicle %s to database', self.vehicle.vin)
                                self.last_charging_session = new_session
                            except IntegrityError as err:
                                session.rollback()
                                LOG.error('IntegrityError while adding charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while adding charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_charging_session is not None and not self.last_charging_session.was_connected():
                        try:
                            self.last_charging_session.plug_connected_date = element.last_changed
                            session.commit()
                            LOG.info("Writing plug connected date for charging session of vehicle %s", self.vehicle.vin)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while changing charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.carconnectivity_last_connector_state = element.value
        self.session_factory.remove()

    def __on_connector_lock_state_change(self, element: EnumAttribute[ChargingConnector.ChargingConnectorLockState], flags: Observable.ObserverEvent) -> None:
        del flags
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")

        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            with self.last_charging_session_lock:
                if self.last_charging_session is not None:
                    try:
                        self.last_charging_session = session.merge(self.last_charging_session)
                        session.refresh(self.last_charging_session)
                    except ObjectDeletedError:
                        self.last_charging_session = session.query(ChargingSession).filter(ChargingSession.vehicle == self.vehicle) \
                            .order_by(ChargingSession.session_start_date.desc().nulls_first(),
                                      ChargingSession.plug_locked_date.desc().nulls_first(),
                                      ChargingSession.plug_connected_date.desc().nulls_first()).first()
                        if self.last_charging_session is not None:
                            LOG.info('Last charging session for vehicle %s was deleted from database, reloaded last charging session', self.vehicle.vin)
                        else:
                            LOG.info('Last charging session for vehicle %s was deleted from database, no more charging sessions found', self.vehicle.vin)
                if element.value == ChargingConnector.ChargingConnectorLockState.LOCKED \
                        and self.carconnectivity_last_connector_lock_state is not None \
                        and self.carconnectivity_last_connector_lock_state != ChargingConnector.ChargingConnectorLockState.LOCKED:
                    if self.last_charging_session is None or self.last_charging_session.is_closed():
                        # In case this was an interrupted charging session (interrupt no longer than 24hours), continue by erasing end time
                        if self.last_charging_session is not None and not self.last_charging_session.was_disconnected() \
                            and (self.last_charging_session.plug_unlocked_date is None
                                 or self.last_charging_session.plug_unlocked_date > ((element.last_changed or datetime.now(timezone.utc))
                                                                                     - timedelta(hours=24))):
                            LOG.debug("found a closed charging session that was not disconneced. This could be an interrupted session we want to continue")
                            try:
                                self.last_charging_session.plug_unlocked_date = None
                                session.commit()
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while changing charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                        else:
                            LOG.info("Starting new charging session for vehicle %s due to connector locked state", self.vehicle.vin)
                            new_session: ChargingSession = ChargingSession(vin=self.vehicle.vin, plug_locked_date=element.last_changed)
                            try:
                                session.add(new_session)
                                self._update_session_odometer(session, new_session)
                                self._update_session_position(session, new_session)
                                session.commit()
                                LOG.debug('Added new charging session for vehicle %s to database', self.vehicle.vin)
                                self.last_charging_session = new_session
                            except IntegrityError as err:
                                session.rollback()
                                LOG.error('IntegrityError while adding charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while adding charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif not self.last_charging_session.was_locked():
                        LOG.debug("Continuing existing charging session for vehicle %s, writing locked date", self.vehicle.vin)
                        try:
                            self.last_charging_session.plug_locked_date = element.last_changed
                            self._update_session_odometer(session, self.last_charging_session)
                            self._update_session_position(session, self.last_charging_session)
                            session.commit()
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while starting charging session for vehicle %s in database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                elif element.value != ChargingConnector.ChargingConnectorLockState.LOCKED \
                        and self.carconnectivity_last_connector_lock_state == ChargingConnector.ChargingConnectorLockState.LOCKED:
                    if self.last_charging_session is not None and not self.last_charging_session.was_unlocked():
                        LOG.info("Writing plug unlocked date for charging session of vehicle %s", self.vehicle.vin)
                        try:
                            self.last_charging_session.plug_unlocked_date = element.last_changed
                            session.commit()
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while ending charging session for vehicle %s in database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                # Create charging session when locked at startup
                elif element.value == ChargingConnector.ChargingConnectorLockState.LOCKED \
                        and self.carconnectivity_last_connector_lock_state == ChargingConnector.ChargingConnectorLockState.LOCKED:
                    if self.last_charging_session is None or self.last_charging_session.is_closed():
                        # In case this was an interrupted charging session (interrupt no longer than 24hours), continue by erasing end time
                        if self.last_charging_session is not None and not self.last_charging_session.was_disconnected() \
                            and (self.last_charging_session.plug_unlocked_date is None
                                 or self.last_charging_session.plug_unlocked_date > ((element.last_changed or datetime.now(timezone.utc))
                                                                                     - timedelta(hours=24))):
                            LOG.debug("found a closed charging session that was not disconneced. This could be an interrupted session we want to continue")
                            try:
                                self.last_charging_session.plug_unlocked_date = None
                                session.commit()
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while changing charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                        else:
                            LOG.info("Starting new charging session for vehicle %s due to connector locked state on startup", self.vehicle.vin)
                        new_session: ChargingSession = ChargingSession(vin=self.vehicle.vin, plug_locked_date=element.last_changed)
                        try:
                            session.add(new_session)
                            self._update_session_odometer(session, new_session)
                            self._update_session_position(session, new_session)
                            session.commit()
                            LOG.debug('Added new charging session for vehicle %s to database', self.vehicle.vin)
                            self.last_charging_session = new_session
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_charging_session is not None and not self.last_charging_session.was_locked():
                        try:
                            self.last_charging_session.plug_locked_date = element.last_changed
                            session.commit()
                            LOG.info("Writing plug locked date for charging session of vehicle %s", self.vehicle.vin)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while changing charging session for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.carconnectivity_last_connector_lock_state = element.value
        self.session_factory.remove()

    def _update_session_odometer(self, session: Session, charging_session: ChargingSession) -> None:
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
        if self.carconnectivity_vehicle.odometer.enabled:
            converted_odometer: Optional[float] = self.carconnectivity_vehicle.odometer.in_locale(locale=self.database_plugin.locale)[0]
            if charging_session.session_odometer is None:
                try:
                    charging_session.session_odometer = converted_odometer
                except DatabaseError as err:
                    session.rollback()
                    LOG.error('DatabaseError while updating odometer for charging session of vehicle %s in database: %s', self.vehicle.vin, err)
                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access

    def _update_session_charging_type(self, session: Session, charging_session: ChargingSession) -> None:
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
        if isinstance(self.carconnectivity_vehicle, ElectricVehicle) and self.carconnectivity_vehicle.charging.type.enabled \
                and self.carconnectivity_vehicle.charging.type.value is not None:
            if charging_session.charging_type is None:
                try:
                    charging_session.charging_type = self.carconnectivity_vehicle.charging.type.value
                except DatabaseError as err:
                    session.rollback()
                    LOG.error('DatabaseError while updating charging type for charging session of vehicle %s in database: %s', self.vehicle.vin, err)
                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access

    def _update_session_position(self, session: Session, charging_session: ChargingSession) -> None:
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
        if self.carconnectivity_vehicle.position.enabled and self.carconnectivity_vehicle.position.latitude.enabled \
                and self.carconnectivity_vehicle.position.longitude.enabled \
                and self.carconnectivity_vehicle.position.latitude.value is not None \
                and self.carconnectivity_vehicle.position.longitude.value is not None:
            if charging_session.session_position_latitude is None and charging_session.session_position_longitude is None:
                try:
                    charging_session.session_position_latitude = self.carconnectivity_vehicle.position.latitude.value
                    charging_session.session_position_longitude = self.carconnectivity_vehicle.position.longitude.value
                except DatabaseError as err:
                    session.rollback()
                    LOG.error('DatabaseError while updating position for charging session of vehicle %s in database: %s', self.vehicle.vin, err)
                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
            if charging_session.location is None and self.carconnectivity_vehicle.position.location.enabled:
                location: Location = Location.from_carconnectivity_location(location=self.carconnectivity_vehicle.position.location)
                try:
                    location = session.merge(location)
                    charging_session.location = location
                except DatabaseError as err:
                    session.rollback()
                    LOG.error('DatabaseError while merging location for charging session of vehicle %s in database: %s', self.vehicle.vin, err)
                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
        if charging_session.charging_station is None \
                and isinstance(self.carconnectivity_vehicle, ElectricVehicle) and self.carconnectivity_vehicle.charging is not None \
                and self.carconnectivity_vehicle.charging.enabled and self.carconnectivity_vehicle.charging.charging_station.enabled:
            charging_station: ChargingStation = ChargingStation.from_carconnectivity_charging_station(
                charging_station=self.carconnectivity_vehicle.charging.charging_station)
            try:
                charging_station = session.merge(charging_station)
                charging_session.charging_station = charging_station
            except DatabaseError as err:
                session.rollback()
                LOG.error('DatabaseError while merging charging station for charging session of vehicle %s in database: %s', self.vehicle.vin, err)
                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access

    def _on_charging_type_change(self, element: EnumAttribute[Charging.ChargingType], flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            with self.session_factory() as session:
                self.vehicle = session.merge(self.vehicle)
                session.refresh(self.vehicle)
                with self.last_charging_session_lock:
                    if self.last_charging_session is not None:
                        try:
                            self.last_charging_session = session.merge(self.last_charging_session)
                            session.refresh(self.last_charging_session)
                        except ObjectDeletedError:
                            self.last_charging_session = session.query(ChargingSession).filter(ChargingSession.vehicle == self.vehicle) \
                                .order_by(ChargingSession.session_start_date.desc().nulls_first(),
                                          ChargingSession.plug_locked_date.desc().nulls_first(),
                                          ChargingSession.plug_connected_date.desc().nulls_first()).first()
                            if self.last_charging_session is not None:
                                LOG.info('Last charging session for vehicle %s was deleted from database, reloaded last charging session', self.vehicle.vin)
                            else:
                                LOG.info('Last charging session for vehicle %s was deleted from database, no more charging sessions found', self.vehicle.vin)
                    if self.last_charging_session is not None and not self.last_charging_session.is_closed() \
                            and element.value in [Charging.ChargingType.AC, Charging.ChargingType.DC]:
                        try:
                            self.last_charging_session.charging_type = element.value
                            session.commit()
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while updating type of charging session for vehicle %s in database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
            self.session_factory.remove()

    def _on_battery_level_change(self, element: FloatAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled and element.value is not None:
            # We try to see if there was a late battery level update for a finished session
            with self.session_factory() as session:
                self.vehicle = session.merge(self.vehicle)
                session.refresh(self.vehicle)
                with self.last_charging_session_lock:
                    if self.last_charging_session is not None:
                        try:
                            self.last_charging_session = session.merge(self.last_charging_session)
                            session.refresh(self.last_charging_session)
                        except ObjectDeletedError:
                            self.last_charging_session = session.query(ChargingSession).filter(ChargingSession.vehicle == self.vehicle) \
                                .order_by(ChargingSession.session_start_date.desc().nulls_first(),
                                          ChargingSession.plug_locked_date.desc().nulls_first(),
                                          ChargingSession.plug_connected_date.desc().nulls_first()).first()
                            if self.last_charging_session is not None:
                                LOG.info('Last charging session for vehicle %s was deleted from database, reloaded last charging session', self.vehicle.vin)
                            else:
                                LOG.info('Last charging session for vehicle %s was deleted from database, no more charging sessions found', self.vehicle.vin)
                    if self.last_charging_session is not None and self.last_charging_session.session_end_date is not None:
                        if element.last_updated is not None and (element.last_updated <= (self.last_charging_session.session_end_date + timedelta(minutes=1))):
                            # Only update if we have no end level yet or the new level is higher than the previous one (this happens with late level updates)
                            if self.last_charging_session.end_level is None or self.last_charging_session.end_level < element.value:
                                try:
                                    self.last_charging_session.end_level = element.value
                                    session.commit()
                                except DatabaseError as err:
                                    session.rollback()
                                    LOG.error('DatabaseError while updating battery level of charging session for vehicle %s in database: %s',
                                              self.vehicle.vin, err)
                                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
            self.session_factory.remove()

    def __on_battery_temperature_change(self, element: TemperatureAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            converted_value: Optional[float] = element.in_locale(locale=self.database_plugin.locale)[0]
            with self.last_battery_temperature_lock:
                with self.session_factory() as session:
                    self.vehicle = session.merge(self.vehicle)
                    session.refresh(self.vehicle)
                    if self.last_battery_temperature is not None:
                        try:
                            self.last_battery_temperature = session.merge(self.last_battery_temperature)
                            session.refresh(self.last_battery_temperature)
                        except ObjectDeletedError:
                            self.last_battery_temperature = session.query(BatteryTemperature).filter(BatteryTemperature.vehicle == self.vehicle)\
                                .order_by(BatteryTemperature.first_date.desc()).first()
                            if self.last_battery_temperature is not None:
                                LOG.info('Last battery temperature for vehicle %s was deleted from database, reloaded last battery temperature',
                                         self.vehicle.vin)
                            else:
                                LOG.info('Last battery temperature for vehicle %s was deleted from database, no more battery temperatures found',
                                         self.vehicle.vin)
                    if element.last_updated is not None \
                            and (self.last_battery_temperature is None or (self.last_battery_temperature.battery_temperature != converted_value
                                                                           and element.last_updated > self.last_battery_temperature.last_date)):
                        new_battery_temperature: BatteryTemperature = BatteryTemperature(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                                         last_date=element.last_updated, battery_temperature=converted_value)
                        try:
                            session.add(new_battery_temperature)
                            session.commit()
                            LOG.debug('Added new battery temperature %.2f for vehicle %s to database', converted_value, self.vehicle.vin)
                            self.last_battery_temperature = new_battery_temperature
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding battery temperature for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding battery temperature for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_battery_temperature is not None and self.last_battery_temperature.battery_temperature == converted_value \
                            and element.last_updated is not None:
                        if self.last_battery_temperature.last_date is None or element.last_updated > self.last_battery_temperature.last_date:
                            try:
                                self.last_battery_temperature.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated battery temperature %.2f for vehicle %s in database', converted_value, self.vehicle.vin)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating battery temperature for vehicle %s in database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()
