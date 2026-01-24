"""
Module for monitoring and persisting vehicle state changes to the database.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging

from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm.exc import ObjectDeletedError

from carconnectivity.observable import Observable
from carconnectivity.utils.timeout_lock import TimeoutLock

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.state import State
from carconnectivity_plugins.database.model.connection_state import ConnectionState
from carconnectivity_plugins.database.model.outside_temperature import OutsideTemperature

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import EnumAttribute, TemperatureAttribute, StringAttribute, IntegerAttribute

    from carconnectivity.vehicle import GenericVehicle

    from carconnectivity_plugins.database.plugin import Plugin
    from carconnectivity_plugins.database.model.vehicle import Vehicle


LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.state_agent")


#  pylint: disable=duplicate-code
# pylint: disable-next=too-many-instance-attributes, too-few-public-methods
class StateAgent(BaseAgent):
    """
        Agent responsible for monitoring and persisting vehicle state changes to the database.

        This agent observes changes to:
        - Vehicle state (e.g., parked, driving)
        - Connection state (e.g., online, offline)
        - Outside temperature

        When changes are detected, the agent either creates new database records or updates
        existing ones with the latest timestamp. It maintains references to the last known
        values to optimize database operations and avoid unnecessary writes.
        """
    def __init__(self, database_plugin: Plugin, session_factory: scoped_session[Session], vehicle: Vehicle, carconnectivity_vehicle: GenericVehicle) -> None:
        if vehicle is None or carconnectivity_vehicle is None:
            raise ValueError("Vehicle or its carconnectivity_vehicle attribute is None")
        self.database_plugin: Plugin = database_plugin
        self.session_factory: scoped_session[Session] = session_factory
        self.vehicle: Vehicle = vehicle
        self.carconnectivity_vehicle: GenericVehicle = carconnectivity_vehicle

        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            self.last_state: Optional[State] = session.query(State).filter(State.vehicle == self.vehicle).order_by(State.first_date.desc()).first()
            self.last_state_lock: TimeoutLock = TimeoutLock()

            self.last_connection_state: Optional[ConnectionState] = session.query(ConnectionState).filter(ConnectionState.vehicle == self.vehicle) \
                .order_by(ConnectionState.first_date.desc()).first()
            self.last_connection_state_lock: TimeoutLock = TimeoutLock()

            self.last_outside_temperature: Optional[OutsideTemperature] = session.query(OutsideTemperature).filter(OutsideTemperature.vehicle == self.vehicle) \
                .order_by(OutsideTemperature.first_date.desc()).first()
            self.last_outside_temperature_lock: TimeoutLock = TimeoutLock()

            self.carconnectivity_vehicle.state.add_observer(self.__on_state_change, Observable.ObserverEvent.UPDATED)
            self.__on_state_change(self.carconnectivity_vehicle.state, Observable.ObserverEvent.UPDATED)

            self.carconnectivity_vehicle.connection_state.add_observer(self.__on_connection_state_change, Observable.ObserverEvent.UPDATED)
            self.__on_connection_state_change(self.carconnectivity_vehicle.connection_state, Observable.ObserverEvent.UPDATED)

            self.carconnectivity_vehicle.outside_temperature.add_observer(self.__on_outside_temperature_change, Observable.ObserverEvent.UPDATED)
            self.__on_outside_temperature_change(self.carconnectivity_vehicle.outside_temperature, Observable.ObserverEvent.UPDATED)

            self.carconnectivity_vehicle.name.add_observer(self.__on_name_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
            self.carconnectivity_vehicle.manufacturer.add_observer(self.__on_manufacturer_change, Observable.ObserverEvent.VALUE_CHANGED,
                                                                   on_transaction_end=True)
            self.carconnectivity_vehicle.model.add_observer(self.__on_model_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
            self.carconnectivity_vehicle.model_year.add_observer(self.__on_model_year_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
            self.carconnectivity_vehicle.type.add_observer(self.__on_type_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
            self.carconnectivity_vehicle.license_plate.add_observer(self.__on_license_plate_change, Observable.ObserverEvent.VALUE_CHANGED,
                                                                    on_transaction_end=True)
        self.session_factory.remove()

    def __del__(self) -> None:
        self.carconnectivity_vehicle.state.remove_observer(self.__on_state_change)
        self.carconnectivity_vehicle.connection_state.remove_observer(self.__on_connection_state_change)
        self.carconnectivity_vehicle.outside_temperature.remove_observer(self.__on_outside_temperature_change)
        self.carconnectivity_vehicle.name.remove_observer(self.__on_name_change)
        self.carconnectivity_vehicle.manufacturer.remove_observer(self.__on_manufacturer_change)
        self.carconnectivity_vehicle.model.remove_observer(self.__on_model_change)
        self.carconnectivity_vehicle.model_year.remove_observer(self.__on_model_year_change)
        self.carconnectivity_vehicle.type.remove_observer(self.__on_type_change)
        self.carconnectivity_vehicle.license_plate.remove_observer(self.__on_license_plate_change)

    def __on_state_change(self, element: EnumAttribute[GenericVehicle.State], flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            with self.last_state_lock:
                with self.session_factory() as session:
                    self.vehicle = session.merge(self.vehicle)
                    session.refresh(self.vehicle)
                    if self.last_state is not None:
                        try:
                            self.last_state = session.merge(self.last_state)
                            session.refresh(self.last_state)
                        except ObjectDeletedError:
                            self.last_state = session.query(State).filter(State.vehicle == self.vehicle) \
                                .order_by(State.first_date.desc()).first()
                            if self.last_state is not None:
                                LOG.info('Last state for vehicle %s was deleted from database, reloaded last state', self.vehicle.vin)
                            else:
                                LOG.info('Last state for vehicle %s was deleted from database, no more states found', self.vehicle.vin)
                    if element.last_updated is not None \
                            and (self.last_state is None or (self.last_state.state != element.value
                                                             and element.last_updated > self.last_state.last_date)):
                        new_state: State = State(vin=self.vehicle.vin, first_date=element.last_updated, last_date=element.last_updated, state=element.value)
                        try:
                            session.add(new_state)
                            session.commit()
                            LOG.debug('Added new state %s for vehicle %s to database', element.value, self.vehicle.vin)
                            self.last_state = new_state
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding state for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding state for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access

                    elif self.last_state is not None and self.last_state.state == element.value and element.last_updated is not None:
                        if self.last_state.last_date is None or element.last_updated > self.last_state.last_date:
                            try:
                                self.last_state.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated state %s for vehicle %s in database', element.value, self.vehicle.vin)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating state for vehicle %s in database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_connection_state_change(self, element: EnumAttribute[GenericVehicle.ConnectionState], flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            with self.last_connection_state_lock:
                with self.session_factory() as session:
                    self.vehicle = session.merge(self.vehicle)
                    session.refresh(self.vehicle)
                    if self.last_connection_state is not None:
                        try:
                            self.last_connection_state = session.merge(self.last_connection_state)
                            session.refresh(self.last_connection_state)
                        except ObjectDeletedError:
                            self.last_connection_state = session.query(ConnectionState).filter(ConnectionState.vehicle == self.vehicle) \
                                .order_by(ConnectionState.first_date.desc()).first()
                            if self.last_connection_state is not None:
                                LOG.info('Last connection state for vehicle %s was deleted from database, reloaded last connection state', self.vehicle.vin)
                            else:
                                LOG.info('Last connection state for vehicle %s was deleted from database, no more connection states found', self.vehicle.vin)
                    if element.last_updated is not None \
                            and (self.last_connection_state is None or (self.last_connection_state.connection_state != element.value
                                                                        and element.last_updated > self.last_connection_state.last_date)):
                        new_connection_state: ConnectionState = ConnectionState(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                                last_date=element.last_updated, connection_state=element.value)
                        try:
                            session.add(new_connection_state)
                            session.commit()
                            LOG.debug('Added new connection state %s for vehicle %s to database', element.value, self.vehicle.vin)
                            self.last_connection_state = new_connection_state
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding state for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding connection state for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_connection_state is not None and self.last_connection_state.connection_state == element.value \
                            and element.last_updated is not None:
                        if self.last_connection_state.last_date is None or element.last_updated > self.last_connection_state.last_date:
                            try:
                                self.last_connection_state.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated connection state %s for vehicle %s in database', element.value, self.vehicle.vin)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating connection state for vehicle %s in database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_outside_temperature_change(self, element: TemperatureAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            converted_value: Optional[float] = element.in_locale(locale=self.database_plugin.locale)[0]
            with self.last_outside_temperature_lock:
                with self.session_factory() as session:
                    self.vehicle = session.merge(self.vehicle)
                    session.refresh(self.vehicle)
                    if self.last_outside_temperature is not None:
                        try:
                            self.last_outside_temperature = session.merge(self.last_outside_temperature)
                            session.refresh(self.last_outside_temperature)
                        except ObjectDeletedError:
                            self.last_outside_temperature = session.query(OutsideTemperature).filter(OutsideTemperature.vehicle == self.vehicle) \
                                .order_by(OutsideTemperature.first_date.desc()).first()
                            if self.last_outside_temperature is not None:
                                LOG.info('Last outside temperature for vehicle %s was deleted from database, reloaded last outside temperature',
                                         self.vehicle.vin)
                            else:
                                LOG.info('Last outside temperature for vehicle %s was deleted from database, no more outside temperatures found',
                                         self.vehicle.vin)
                    if element.last_updated is not None \
                            and (self.last_outside_temperature is None or (self.last_outside_temperature.outside_temperature != converted_value
                                                                           and element.last_updated > self.last_outside_temperature.last_date)):
                        new_outside_temperature: OutsideTemperature = OutsideTemperature(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                                         last_date=element.last_updated, outside_temperature=converted_value)
                        try:
                            session.add(new_outside_temperature)
                            session.commit()
                            LOG.debug('Added new outside temperature %.2f for vehicle %s to database', converted_value, self.vehicle.vin)
                            self.last_outside_temperature = new_outside_temperature
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding outside temperature for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding outside temperature for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_outside_temperature is not None and self.last_outside_temperature.outside_temperature == converted_value \
                            and element.last_updated is not None:
                        if self.last_outside_temperature.last_date is None or element.last_updated > self.last_outside_temperature.last_date:
                            try:
                                self.last_outside_temperature.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated outside temperature %.2f for vehicle %s in database', converted_value, self.vehicle.vin)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating outside temperature for vehicle %s in database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_name_change(self, element: StringAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            if self.vehicle.name != element.value:
                self.vehicle.name = element.value
        self.session_factory.remove()

    def __on_manufacturer_change(self, element: StringAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            if self.vehicle.manufacturer != element.value:
                self.vehicle.manufacturer = element.value
        self.session_factory.remove()

    def __on_model_change(self, element: StringAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            if self.vehicle.model != element.value:
                self.vehicle.model = element.value
        self.session_factory.remove()

    def __on_model_year_change(self, element: IntegerAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            if self.vehicle.model_year != element.value:
                self.vehicle.model_year = element.value
        self.session_factory.remove()

    def __on_type_change(self, element: EnumAttribute[GenericVehicle.Type], flags: Observable.ObserverEvent) -> None:
        del flags
        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            if element.value is not None and self.vehicle.type != element.value:
                self.vehicle.type = element.value
        self.session_factory.remove()

    def __on_license_plate_change(self, element: StringAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            if self.vehicle.license_plate != element.value:
                self.vehicle.license_plate = element.value
        self.session_factory.remove()
