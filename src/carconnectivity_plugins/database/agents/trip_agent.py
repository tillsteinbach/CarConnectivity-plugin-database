from __future__ import annotations
from typing import TYPE_CHECKING

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import DatabaseError

from carconnectivity.observable import Observable

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.trip import Trip
from carconnectivity.vehicle import GenericVehicle

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import EnumAttribute

    from carconnectivity_plugins.database.model.vehicle import Vehicle

LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.trip_agent")


class TripAgent(BaseAgent):
    """
    Agent responsible for tracking vehicle trips based on vehicle state changes.
    This agent monitors the vehicle's state (ignition on/off, driving) and automatically
    creates and manages trip records in the database. It tracks trip start/end times and
    odometer readings.
    Attributes:
        session (Session): SQLAlchemy database session for persisting trip data.
        vehicle (Vehicle): The vehicle being monitored for trip tracking.
        last_carconnectivity_state (Optional[GenericVehicle.State]): The last known state
            of the vehicle to detect state transitions.
        trip (Optional[Trip]): The currently active trip, if any.
    Raises:
        ValueError: If vehicle or vehicle.carconnectivity_vehicle is None during initialization.
    Notes:
        - A new trip is started when the vehicle transitions to IGNITION_ON or DRIVING state.
        - A trip is ended when the vehicle transitions from IGNITION_ON/DRIVING to another state.
        - If a previous trip is still open during startup or when starting a new trip,
          it will be logged and closed.
        - Trip records include start/end dates and odometer readings when available.
    """

    def __init__(self, session: Session, vehicle: Vehicle) -> None:
        if vehicle is None or vehicle.carconnectivity_vehicle is None:
            raise ValueError("Vehicle or its carconnectivity_vehicle attribute is None")
        self.session: Session = session
        self.vehicle: Vehicle = vehicle
        self.last_carconnectivity_state: Optional[GenericVehicle.State] = None

        self.trip: Optional[Trip] = session.query(Trip).filter(Trip.vehicle == vehicle).order_by(Trip.start_date.desc()).first()
        if self.trip is not None:
            if self.trip.destination_date is None:
                LOG.info("Last trip for vehicle %s is still open during startup, closing it now", vehicle.vin)

        vehicle.carconnectivity_vehicle.state.add_observer(self.__on_state_change, Observable.ObserverEvent.UPDATED)
        self.__on_state_change(vehicle.carconnectivity_vehicle.state, Observable.ObserverEvent.UPDATED)

    def __on_state_change(self, element: EnumAttribute[GenericVehicle.State], flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            if self.vehicle.carconnectivity_vehicle is None:
                raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
            if element.enabled and element.value is not None:
                if self.last_carconnectivity_state is not None:
                    if self.last_carconnectivity_state not in (GenericVehicle.State.IGNITION_ON, GenericVehicle.State.DRIVING) \
                            and element.value in (GenericVehicle.State.IGNITION_ON, GenericVehicle.State.DRIVING):
                        if self.trip is not None:
                            LOG.warning("Starting new trip for vehicle %s while previous trip is still open, closing previous trip first", self.vehicle.vin)
                            self.trip = None
                        LOG.info("Starting new trip for vehicle %s", self.vehicle.vin)
                        start_date: datetime = element.last_updated if element.last_updated is not None else datetime.now(tz=timezone.utc)
                        new_trip: Trip = Trip(vin=self.vehicle.vin, start_date=start_date)
                        if self.vehicle.carconnectivity_vehicle.odometer.enabled and \
                                self.vehicle.carconnectivity_vehicle.odometer.value is not None:
                            new_trip.start_odometer = self.vehicle.carconnectivity_vehicle.odometer.value
                        try:
                            self.session.add(new_trip)
                            LOG.debug('Added new trip for vehicle %s to database', self.vehicle.vin)
                            self.trip = new_trip
                        except DatabaseError as err:
                            self.session.rollback()
                            LOG.error('DatabaseError while adding trip for vehicle %s to database: %s', self.vehicle.vin, err)
                    elif self.last_carconnectivity_state in (GenericVehicle.State.IGNITION_ON, GenericVehicle.State.DRIVING) \
                            and element.value not in (GenericVehicle.State.IGNITION_ON, GenericVehicle.State.DRIVING):
                        if self.trip is not None:
                            LOG.info("Ending trip for vehicle %s", self.vehicle.vin)
                            try:
                                self.trip.end_date = element.last_updated if element.last_updated is not None else datetime.now(tz=timezone.utc)
                                if self.vehicle.carconnectivity_vehicle.odometer.enabled and \
                                        self.vehicle.carconnectivity_vehicle.odometer.value is not None:
                                    self.trip.destination_odometer = self.vehicle.carconnectivity_vehicle.odometer.value
                                    LOG.debug('Set destination odometer %.2f for trip of vehicle %s', self.trip.destination_odometer, self.vehicle.vin)
                                self.trip = None
                            except DatabaseError as err:
                                self.session.rollback()
                                LOG.error('DatabaseError while ending trip for vehicle %s in database: %s', self.vehicle.vin, err)
                self.last_carconnectivity_state = element.value
