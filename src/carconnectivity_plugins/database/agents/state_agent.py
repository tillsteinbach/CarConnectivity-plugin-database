from __future__ import annotations
from typing import TYPE_CHECKING

from carconnectivity.observable import Observable

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.state import State
from carconnectivity_plugins.database.model.connection_state import ConnectionState
from carconnectivity_plugins.database.model.outside_temperature import OutsideTemperature

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import EnumAttribute, TemperatureAttribute

    from carconnectivity.vehicle import GenericVehicle

    from carconnectivity_plugins.database.model.vehicle import Vehicle


class StateAgent(BaseAgent):
    def __init__(self, session: Session, vehicle: Vehicle) -> None:
        if vehicle is None or vehicle.carconnectivity_vehicle is None:
            raise ValueError("Vehicle or its carconnectivity_vehicle attribute is None")
        self.session: Session = session
        self.vehicle: Vehicle = vehicle
        self.last_state: Optional[State] = session.query(State).filter(State.vehicle == vehicle).order_by(State.first_date.desc()).first()
        self.last_connection_state: Optional[ConnectionState] = session.query(ConnectionState).filter(ConnectionState.vehicle == vehicle) \
            .order_by(ConnectionState.first_date.desc()).first()
        self.last_outside_temperature: Optional[OutsideTemperature] = session.query(OutsideTemperature).filter(OutsideTemperature.vehicle == vehicle) \
            .order_by(OutsideTemperature.first_date.desc()).first()

        vehicle.carconnectivity_vehicle.state.add_observer(self.__on_state_change, Observable.ObserverEvent.UPDATED)
        self.__on_state_change(vehicle.carconnectivity_vehicle.state, Observable.ObserverEvent.UPDATED)

        vehicle.carconnectivity_vehicle.connection_state.add_observer(self.__on_connection_state_change, Observable.ObserverEvent.UPDATED)
        self.__on_connection_state_change(vehicle.carconnectivity_vehicle.connection_state, Observable.ObserverEvent.UPDATED)

        vehicle.carconnectivity_vehicle.outside_temperature.add_observer(self.__on_outside_temperature_change, Observable.ObserverEvent.UPDATED)
        self.__on_outside_temperature_change(vehicle.carconnectivity_vehicle.outside_temperature, Observable.ObserverEvent.UPDATED)

    def __on_state_change(self, element: EnumAttribute[GenericVehicle.State], flags: Observable.ObserverEvent) -> None:
        del flags
        if self.last_state is not None:
            self.session.refresh(self.last_state)
        if (self.last_state is None or self.last_state.state != element.value) \
                and element.last_updated is not None:
            new_state: State = State(vin=self.vehicle.vin, first_date=element.last_updated, last_date=element.last_updated, state=element.value)
            with self.session.begin_nested():
                self.session.add(new_state)
            self.session.commit()
            self.last_state = new_state
        elif self.last_state is not None and self.last_state.state == element.value and element.last_updated is not None:
            if self.last_state.last_date is None or element.last_updated > self.last_state.last_date:
                with self.session.begin_nested():
                    self.last_state.last_date = element.last_updated
                self.session.commit()

    def __on_connection_state_change(self, element: EnumAttribute[GenericVehicle.ConnectionState], flags: Observable.ObserverEvent) -> None:
        del flags
        if self.last_connection_state is not None:
            self.session.refresh(self.last_connection_state)
        if (self.last_connection_state is None or self.last_connection_state.connection_state != element.value) \
                and element.last_updated is not None:
            new_connection_state: ConnectionState = ConnectionState(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                    last_date=element.last_updated, connection_state=element.value)
            with self.session.begin_nested():
                self.session.add(new_connection_state)
            self.session.commit()
            self.last_connection_state = new_connection_state
        elif self.last_connection_state is not None and self.last_connection_state.connection_state == element.value and element.last_updated is not None:
            if self.last_connection_state.last_date is None or element.last_updated > self.last_connection_state.last_date:
                with self.session.begin_nested():
                    self.last_connection_state.last_date = element.last_updated
                self.session.commit()

    def __on_outside_temperature_change(self, element: TemperatureAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.last_outside_temperature is not None:
            self.session.refresh(self.last_outside_temperature)
        if (self.last_outside_temperature is None or self.last_outside_temperature.outside_temperature != element.value) \
                and element.last_updated is not None:
            new_outside_temperature: OutsideTemperature = OutsideTemperature(vin=self.vehicle.vin, first_date=element.last_updated,
                                                                             last_date=element.last_updated, outside_temperature=element.value)
            self.session.add(new_outside_temperature)
            self.session.commit()
            self.last_outside_temperature = new_outside_temperature
        elif self.last_outside_temperature is not None and self.last_outside_temperature.outside_temperature == element.value \
                and element.last_updated is not None:
            if self.last_outside_temperature.last_date is None or element.last_updated > self.last_outside_temperature.last_date:
                with self.session.begin_nested():
                    self.last_outside_temperature.last_date = element.last_updated
                self.session.commit()
