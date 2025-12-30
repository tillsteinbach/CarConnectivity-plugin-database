from __future__ import annotations
from typing import TYPE_CHECKING

import logging

from sqlalchemy.exc import DatabaseError

from carconnectivity.observable import Observable

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.climatization_state import ClimatizationState

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import EnumAttribute

    from carconnectivity.climatization import Climatization

    from carconnectivity_plugins.database.model.vehicle import Vehicle


LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.climatization_agent")


class ClimatizationAgent(BaseAgent):
    def __init__(self, session: Session, vehicle: Vehicle) -> None:
        if vehicle is None or vehicle.carconnectivity_vehicle is None:
            raise ValueError("Vehicle or its carconnectivity_vehicle attribute is None")
        self.session: Session = session
        self.vehicle: Vehicle = vehicle
        self.last_state: Optional[ClimatizationState] = session.query(ClimatizationState).filter(ClimatizationState.vehicle == vehicle)\
            .order_by(ClimatizationState.first_date.desc()).first()

        vehicle.carconnectivity_vehicle.climatization.state.add_observer(self.__on_state_change, Observable.ObserverEvent.UPDATED)
        self.__on_state_change(vehicle.carconnectivity_vehicle.climatization.state, Observable.ObserverEvent.UPDATED)

    def __on_state_change(self, element: EnumAttribute[Climatization.ClimatizationState], flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            if self.last_state is not None:
                self.session.refresh(self.last_state)
            if (self.last_state is None or self.last_state.state != element.value) \
                    and element.last_updated is not None:
                new_state: ClimatizationState = ClimatizationState(vin=self.vehicle.vin, first_date=element.last_updated, last_date=element.last_updated,
                                                                   state=element.value)
                try:
                    self.session.add(new_state)
                    LOG.debug('Added new climatization state %s for vehicle %s to database', element.value, self.vehicle.vin)
                    self.last_state = new_state
                except DatabaseError as err:
                    self.session.rollback()
                    LOG.error('DatabaseError while adding climatizationstate for vehicle %s to database: %s', self.vehicle.vin, err)

            elif self.last_state is not None and self.last_state.state == element.value and element.last_updated is not None:
                if self.last_state.last_date is None or element.last_updated > self.last_state.last_date:
                    try:
                        self.last_state.last_date = element.last_updated
                        LOG.debug('Updated climatizationstate %s for vehicle %s in database', element.value, self.vehicle.vin)
                    except DatabaseError as err:
                        self.session.rollback()
                        LOG.error('DatabaseError while updating climatizationstate for vehicle %s in database: %s', self.vehicle.vin, err)
