from __future__ import annotations
from typing import TYPE_CHECKING

import logging

from sqlalchemy.exc import DatabaseError

from carconnectivity.observable import Observable
from carconnectivity.vehicle import ElectricVehicle
from carconnectivity.charging import Charging

from carconnectivity_plugins.database.agents.base_agent import BaseAgent

from carconnectivity_plugins.database.model.charging_state import ChargingState
from carconnectivity_plugins.database.model.charging_rate import ChargingRate
from carconnectivity_plugins.database.model.charging_power import ChargingPower

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import EnumAttribute, SpeedAttribute, PowerAttribute

    from carconnectivity_plugins.database.model.vehicle import Vehicle

LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.charging_agent")


class ChargingAgent(BaseAgent):

    def __init__(self, session: Session, vehicle: Vehicle) -> None:
        if vehicle is None or vehicle.carconnectivity_vehicle is None:
            raise ValueError("Vehicle or its carconnectivity_vehicle attribute is None")
        if not isinstance(vehicle.carconnectivity_vehicle, ElectricVehicle):
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is not an ElectricVehicle")
        self.session: Session = session
        self.vehicle: Vehicle = vehicle

        self.last_charging_state: Optional[ChargingState] = session.query(ChargingState).filter(ChargingState.vehicle == vehicle)\
            .order_by(ChargingState.first_date.desc()).first()
        self.last_charging_rate: Optional[ChargingRate] = session.query(ChargingRate).filter(ChargingRate.vehicle == vehicle)\
            .order_by(ChargingRate.first_date.desc()).first()
        self.last_charging_power: Optional[ChargingPower] = session.query(ChargingPower).filter(ChargingPower.vehicle == vehicle)\
            .order_by(ChargingPower.first_date.desc()).first()

        vehicle.carconnectivity_vehicle.charging.state.add_observer(self.__on_charging_state_change, Observable.ObserverEvent.UPDATED)
        if vehicle.carconnectivity_vehicle.charging.state.enabled:
            self.__on_charging_state_change(vehicle.carconnectivity_vehicle.charging.state, Observable.ObserverEvent.UPDATED)

        vehicle.carconnectivity_vehicle.charging.rate.add_observer(self.__on_charging_rate_change, Observable.ObserverEvent.UPDATED)
        if vehicle.carconnectivity_vehicle.charging.rate.enabled:
            self.__on_charging_rate_change(vehicle.carconnectivity_vehicle.charging.rate, Observable.ObserverEvent.UPDATED)

        vehicle.carconnectivity_vehicle.charging.power.add_observer(self.__on_charging_power_change, Observable.ObserverEvent.UPDATED)
        if vehicle.carconnectivity_vehicle.charging.power.enabled:
            self.__on_charging_power_change(vehicle.carconnectivity_vehicle.charging.power, Observable.ObserverEvent.UPDATED)

    def __on_charging_state_change(self, element: EnumAttribute[Charging.ChargingState], flags: Observable.ObserverEvent) -> None:
        del flags
        if self.vehicle.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")

        if self.last_charging_state is not None:
            self.session.refresh(self.last_charging_state)
        if (self.last_charging_state is None or self.last_charging_state.state != element.value) \
                and element.last_updated is not None:
            new_charging_state: ChargingState = ChargingState(vin=self.vehicle.vin, first_date=element.last_updated,
                                                              last_date=element.last_updated, state=element.value)
            try:
                self.session.add(new_charging_state)
                LOG.debug('Added new charging state %s for vehicle %s to database', element.value, self.vehicle.vin)
                self.last_charging_state = new_charging_state
            except DatabaseError as err:
                self.session.rollback()
                LOG.error('DatabaseError while adding charging state for vehicle %s to database: %s', self.vehicle.vin, err)

        elif self.last_charging_state is not None and self.last_charging_state.state == element.value and element.last_updated is not None:
            if self.last_charging_state.last_date is None or element.last_updated > self.last_charging_state.last_date:
                try:
                    self.last_charging_state.last_date = element.last_updated
                    LOG.debug('Updated charging state %s for vehicle %s in database', element.value, self.vehicle.vin)
                except DatabaseError as err:
                    self.session.rollback()
                    LOG.error('DatabaseError while updating charging state for vehicle %s in database: %s', self.vehicle.vin, err)

    def __on_charging_rate_change(self, element: SpeedAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.vehicle.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
        if self.last_charging_rate is not None:
            self.session.refresh(self.last_charging_rate)
        if (self.last_charging_rate is None or self.last_charging_rate.rate != element.value) \
                and element.last_updated is not None:
            new_charging_rate: ChargingRate = ChargingRate(vin=self.vehicle.vin, first_date=element.last_updated,
                                                           last_date=element.last_updated, rate=element.value)
            try:
                self.session.add(new_charging_rate)
                LOG.debug('Added new charging rate %s for vehicle %s to database', element.value, self.vehicle.vin)
                self.last_charging_rate = new_charging_rate
            except DatabaseError as err:
                self.session.rollback()
                LOG.error('DatabaseError while adding charging rate for vehicle %s to database: %s', self.vehicle.vin, err)
        elif self.last_charging_rate is not None and self.last_charging_rate.rate == element.value and element.last_updated is not None:
            if self.last_charging_rate.last_date is None or element.last_updated > self.last_charging_rate.last_date:
                try:
                    self.last_charging_rate.last_date = element.last_updated
                    LOG.debug('Updated charging rate %s for vehicle %s in database', element.value, self.vehicle.vin)
                except DatabaseError as err:
                    self.session.rollback()
                    LOG.error('DatabaseError while updating charging rate for vehicle %s in database: %s', self.vehicle.vin, err)

    def __on_charging_power_change(self, element: PowerAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.vehicle.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
        if self.last_charging_power is not None:
            self.session.refresh(self.last_charging_power)
        if (self.last_charging_power is None or self.last_charging_power.power != element.value) \
                and element.last_updated is not None:
            new_charging_power: ChargingPower = ChargingPower(vin=self.vehicle.vin, first_date=element.last_updated,
                                                              last_date=element.last_updated, power=element.value)
            try:
                self.session.add(new_charging_power)
                LOG.debug('Added new charging power %s for vehicle %s to database', element.value, self.vehicle.vin)
                self.last_charging_power = new_charging_power
            except DatabaseError as err:
                self.session.rollback()
                LOG.error('DatabaseError while adding charging power for vehicle %s to database: %s', self.vehicle.vin, err)
        elif self.last_charging_power is not None and self.last_charging_power.power == element.value and element.last_updated is not None:
            if self.last_charging_power.last_date is None or element.last_updated > self.last_charging_power.last_date:
                try:
                    self.last_charging_power.last_date = element.last_updated
                    LOG.debug('Updated charging power %s for vehicle %s in database', element.value, self.vehicle.vin)
                except DatabaseError as err:
                    self.session.rollback()
                    LOG.error('DatabaseError while updating charging power for vehicle %s in database: %s', self.vehicle.vin, err)
