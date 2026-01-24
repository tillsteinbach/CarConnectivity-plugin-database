"""
Agent for monitoring and persisting climatization state changes to the database.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging

from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm.exc import ObjectDeletedError

from carconnectivity.observable import Observable
from carconnectivity.utils.timeout_lock import TimeoutLock

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.climatization_state import ClimatizationState

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import EnumAttribute
    from carconnectivity.vehicle import GenericVehicle

    from carconnectivity.climatization import Climatization

    from carconnectivity_plugins.database.plugin import Plugin
    from carconnectivity_plugins.database.model.vehicle import Vehicle


LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.climatization_agent")


# pylint: disable=duplicate-code
# pylint: disable=duplicate-code
# pylint: disable-next=too-few-public-methods
class ClimatizationAgent(BaseAgent):
    """
    Agent responsible for monitoring and persisting climatization state changes to the database.
    This agent observes changes to a vehicle's climatization state and records these changes
    in the database. It maintains a record of state transitions, tracking both the first and
    last occurrence of each state.
    Attributes:
        database_plugin (Plugin): Reference to the database plugin for health monitoring.
        session_factory (scoped_session[Session]): SQLAlchemy session factory for database operations.
        vehicle (Vehicle): The database vehicle entity being monitored.
        carconnectivity_vehicle (GenericVehicle): The CarConnectivity vehicle object providing real-time data.
        last_state (Optional[ClimatizationState]): The most recent climatization state record from the database.
        last_state_lock (TimeoutLock): Thread-safe lock for managing concurrent access to state updates.
    Raises:
        ValueError: If either vehicle or carconnectivity_vehicle is None during initialization.
    Notes:
        - Automatically registers as an observer to the vehicle's climatization state attribute.
        - Creates new database records when climatization state changes.
        - Updates existing records' last_date when the same state persists.
        - Sets the database plugin health status to False if database errors occur.
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
            self.last_state: Optional[ClimatizationState] = session.query(ClimatizationState).filter(ClimatizationState.vehicle == self.vehicle)\
                .order_by(ClimatizationState.first_date.desc()).first()
            self.last_state_lock: TimeoutLock = TimeoutLock()

            self.carconnectivity_vehicle.climatization.state.add_observer(self.__on_state_change, Observable.ObserverEvent.UPDATED)
            self.__on_state_change(self.carconnectivity_vehicle.climatization.state, Observable.ObserverEvent.UPDATED)
        self.session_factory.remove()

    def __del__(self) -> None:
        self.carconnectivity_vehicle.climatization.state.remove_observer(self.__on_state_change)

    def __on_state_change(self, element: EnumAttribute[Climatization.ClimatizationState], flags: Observable.ObserverEvent) -> None:
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
                            self.last_state = session.query(ClimatizationState).filter(ClimatizationState.vehicle == self.vehicle) \
                                .order_by(ClimatizationState.first_date.desc()).first()
                            if self.last_state is not None:
                                LOG.info('Last climatization state for vehicle %s was deleted from database, reloaded last climatization state',
                                         self.vehicle.vin)
                            else:
                                LOG.info('Last climatization state for vehicle %s was deleted from database, no more climatization states found',
                                         self.vehicle.vin)
                    if element.last_updated is not None \
                            and (self.last_state is None or (self.last_state.state != element.value
                                                             and element.last_updated > self.last_state.last_date)):
                        new_state: ClimatizationState = ClimatizationState(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                           last_date=element.last_updated, state=element.value)
                        try:
                            session.add(new_state)
                            session.commit()
                            LOG.debug('Added new climatization state %s for vehicle %s to database', element.value, self.vehicle.vin)
                            self.last_state = new_state
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding climatization state for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding climatizationstate for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access

                    elif self.last_state is not None and self.last_state.state == element.value and element.last_updated is not None:
                        if self.last_state.last_date is None or element.last_updated > self.last_state.last_date:
                            try:
                                self.last_state.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated climatizationstate %s for vehicle %s in database', element.value, self.vehicle.vin)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating climatizationstate for vehicle %s in database: %s', self.vehicle.vin, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()
