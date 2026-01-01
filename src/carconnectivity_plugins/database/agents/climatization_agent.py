from __future__ import annotations
from typing import TYPE_CHECKING

import threading

import logging

from sqlalchemy.exc import DatabaseError

from carconnectivity.observable import Observable

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.climatization_state import ClimatizationState

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import EnumAttribute

    from carconnectivity.climatization import Climatization

    from carconnectivity_plugins.database.model.vehicle import Vehicle


LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.climatization_agent")


class ClimatizationAgent(BaseAgent):
    def __init__(self, session_factory: scoped_session[Session], vehicle: Vehicle) -> None:
        if vehicle is None or vehicle.carconnectivity_vehicle is None:
            raise ValueError("Vehicle or its carconnectivity_vehicle attribute is None")
        self.session_factory: scoped_session[Session] = session_factory
        self.vehicle: Vehicle = vehicle

        with self.session_factory() as session:
            self.last_state: Optional[ClimatizationState] = session.query(ClimatizationState).filter(ClimatizationState.vehicle == vehicle)\
                .order_by(ClimatizationState.first_date.desc()).first()
            self.last_state_lock: threading.Lock = threading.Lock()

            vehicle.carconnectivity_vehicle.climatization.state.add_observer(self.__on_state_change, Observable.ObserverEvent.UPDATED)
            self.__on_state_change(vehicle.carconnectivity_vehicle.climatization.state, Observable.ObserverEvent.UPDATED)
        self.session_factory.remove()

    def __on_state_change(self, element: EnumAttribute[Climatization.ClimatizationState], flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            with self.last_state_lock:
                with self.session_factory() as session:
                    if self.last_state is not None:
                        self.last_state = session.merge(self.last_state)
                        session.refresh(self.last_state)
                    if (self.last_state is None or self.last_state.state != element.value) \
                            and element.last_updated is not None:
                        new_state: ClimatizationState = ClimatizationState(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                           last_date=element.last_updated, state=element.value)
                        try:
                            session.add(new_state)
                            session.commit()
                            LOG.debug('Added new climatization state %s for vehicle %s to database', element.value, self.vehicle.vin)
                            self.last_state = new_state
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding climatizationstate for vehicle %s to database: %s', self.vehicle.vin, err)

                    elif self.last_state is not None and self.last_state.state == element.value and element.last_updated is not None:
                        if self.last_state.last_date is None or element.last_updated > self.last_state.last_date:
                            try:
                                self.last_state.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated climatizationstate %s for vehicle %s in database', element.value, self.vehicle.vin)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating climatizationstate for vehicle %s in database: %s', self.vehicle.vin, err)
                self.session_factory.remove()
