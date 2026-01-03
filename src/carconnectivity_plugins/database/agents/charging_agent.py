from __future__ import annotations
from typing import TYPE_CHECKING

import threading

import logging
from datetime import timedelta, datetime, timezone

from sqlalchemy.exc import DatabaseError

from carconnectivity.observable import Observable
from carconnectivity.vehicle import ElectricVehicle
from carconnectivity.charging import Charging
from carconnectivity.charging_connector import ChargingConnector

from carconnectivity_plugins.database.agents.base_agent import BaseAgent

from carconnectivity_plugins.database.model.charging_state import ChargingState
from carconnectivity_plugins.database.model.charging_rate import ChargingRate
from carconnectivity_plugins.database.model.charging_power import ChargingPower
from carconnectivity_plugins.database.model.charging_session import ChargingSession
from carconnectivity_plugins.database.model.location import Location
from carconnectivity_plugins.database.model.charging_station import ChargingStation

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import EnumAttribute, SpeedAttribute, PowerAttribute

    from carconnectivity_plugins.database.plugin import Plugin
    from carconnectivity_plugins.database.model.vehicle import Vehicle
    from carconnectivity.drive import ElectricDrive

LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.charging_agent")


class ChargingAgent(BaseAgent):

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
            self.last_charging_session: Optional[ChargingSession] = session.query(ChargingSession).filter(ChargingSession.vehicle == vehicle) \
                .order_by(ChargingSession.session_start_date.desc().nulls_first(),
                          ChargingSession.plug_locked_date.desc().nulls_first(),
                          ChargingSession.plug_connected_date.desc().nulls_first()).first()

            self.last_charging_session_lock: threading.RLock = threading.RLock()
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
                    LOG.info("Last charging session for vehicle %s is still open during startup, will continue this session", vehicle.vin)
                else:
                    LOG.info("Last charging session for vehicle %s is still open during startup, but we are not charging, ignoring it", vehicle.vin)
                    self.last_charging_session = None
            else:
                self.last_charging_session = None

            self.last_charging_state: Optional[ChargingState] = session.query(ChargingState).filter(ChargingState.vehicle == vehicle)\
                .order_by(ChargingState.first_date.desc()).first()
            self.last_charging_state_lock: threading.RLock = threading.RLock()

            self.last_charging_rate: Optional[ChargingRate] = session.query(ChargingRate).filter(ChargingRate.vehicle == vehicle)\
                .order_by(ChargingRate.first_date.desc()).first()
            self.last_charging_rate_lock: threading.RLock = threading.RLock()

            self.last_charging_power: Optional[ChargingPower] = session.query(ChargingPower).filter(ChargingPower.vehicle == vehicle)\
                .order_by(ChargingPower.first_date.desc()).first()
            self.last_charging_power_lock: threading.RLock = threading.RLock()

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
        self.session_factory.remove()

    def __on_charging_state_change(self, element: EnumAttribute[Charging.ChargingState], flags: Observable.ObserverEvent) -> None:
        del flags
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")

        if element.enabled:
            with self.session_factory() as session:
                with self.last_charging_state_lock:
                    if self.last_charging_state is not None:
                        self.last_charging_state = session.merge(self.last_charging_state)
                        session.refresh(self.last_charging_state)
                    if (self.last_charging_state is None or self.last_charging_state.state != element.value) \
                            and element.last_updated is not None:
                        new_charging_state: ChargingState = ChargingState(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                          last_date=element.last_updated, state=element.value)
                        try:
                            session.add(new_charging_state)
                            session.commit()
                            LOG.debug('Added new charging state %s for vehicle %s to database', element.value, self.vehicle.vin)
                            self.last_charging_state = new_charging_state
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
                            self.last_charging_session = session.merge(self.last_charging_session)
                            session.refresh(self.last_charging_session)

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
                                if self.last_charging_session is not None \
                                        and self.last_charging_session.was_connected() and not self.last_charging_session.was_disconnected() \
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
            with self.last_charging_rate_lock:
                with self.session_factory() as session:
                    if self.last_charging_rate is not None:
                        self.last_charging_rate = session.merge(self.last_charging_rate)
                        session.refresh(self.last_charging_rate)
                    if (self.last_charging_rate is None or self.last_charging_rate.rate != element.value) \
                            and element.last_updated is not None:
                        new_charging_rate: ChargingRate = ChargingRate(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                       last_date=element.last_updated, rate=element.value)
                        try:
                            session.add(new_charging_rate)
                            session.commit()
                            LOG.debug('Added new charging rate %s for vehicle %s to database', element.value, self.vehicle.vin)
                            self.last_charging_rate = new_charging_rate
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding charging rate for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_charging_rate is not None and self.last_charging_rate.rate == element.value and element.last_updated is not None:
                        if self.last_charging_rate.last_date is None or element.last_updated > self.last_charging_rate.last_date:
                            try:
                                self.last_charging_rate.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated charging rate %s for vehicle %s in database', element.value, self.vehicle.vin)
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
            with self.last_charging_power_lock:
                with self.session_factory() as session:
                    if self.last_charging_power is not None:
                        self.last_charging_power = session.merge(self.last_charging_power)
                        session.refresh(self.last_charging_power)
                    if (self.last_charging_power is None or self.last_charging_power.power != element.value) \
                            and element.last_updated is not None:
                        new_charging_power: ChargingPower = ChargingPower(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                          last_date=element.last_updated, power=element.value)
                        try:
                            session.add(new_charging_power)
                            session.commit()
                            LOG.debug('Added new charging power %s for vehicle %s to database', element.value, self.vehicle.vin)
                            self.last_charging_power = new_charging_power
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding charging power for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_charging_power is not None and self.last_charging_power.power == element.value and element.last_updated is not None:
                        if self.last_charging_power.last_date is None or element.last_updated > self.last_charging_power.last_date:
                            try:
                                self.last_charging_power.last_date = element.last_updated
                                LOG.debug('Updated charging power %s for vehicle %s in database', element.value, self.vehicle.vin)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating charging power for vehicle %s in database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_connector_state_change(self, element: EnumAttribute[ChargingConnector.ChargingConnectorConnectionState], flags: Observable.ObserverEvent) -> None:
        del flags
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")

        with self.session_factory() as session:
            with self.last_charging_session_lock:
                if self.last_charging_session is not None:
                    self.last_charging_session = session.merge(self.last_charging_session)
                    session.refresh(self.last_charging_session)

                if element.value == ChargingConnector.ChargingConnectorConnectionState.CONNECTED \
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
                        LOG.info("Starting new charging session for vehicle %s due to connector connected state", self.vehicle.vin)
                        new_session: ChargingSession = ChargingSession(vin=self.vehicle.vin, plug_connected_date=element.last_changed)
                        try:
                            session.add(new_session)
                            self._update_session_odometer(session, new_session)
                            self._update_session_position(session, new_session)
                            session.commit()
                            LOG.debug('Added new charging session for vehicle %s to database', self.vehicle.vin)
                            self.last_charging_session = new_session
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
            with self.last_charging_session_lock:
                if self.last_charging_session is not None:
                    self.last_charging_session = session.merge(self.last_charging_session)
                    session.refresh(self.last_charging_session)

                if element.value == ChargingConnector.ChargingConnectorLockState.LOCKED \
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
                        LOG.info("Starting new charging session for vehicle %s due to connector locked state", self.vehicle.vin)
                        new_session: ChargingSession = ChargingSession(vin=self.vehicle.vin, plug_locked_date=element.last_changed)
                        try:
                            session.add(new_session)
                            self._update_session_odometer(session, new_session)
                            self._update_session_position(session, new_session)
                            session.commit()
                            LOG.debug('Added new charging session for vehicle %s to database', self.vehicle.vin)
                            self.last_charging_session = new_session
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
            if charging_session.session_odometer is None:
                try:
                    charging_session.session_odometer = self.carconnectivity_vehicle.odometer.value
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
                with self.last_charging_session_lock:
                    if self.last_charging_session is not None:
                        self.last_charging_session = session.merge(self.last_charging_session)
                        session.refresh(self.last_charging_session)
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
