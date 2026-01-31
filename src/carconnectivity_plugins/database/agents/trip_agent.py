"""
Agent for tracking vehicle trips and persisting trip data to the database.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging
from datetime import datetime, timezone, timedelta

from carconnectivity.objects import GenericObject
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm.exc import ObjectDeletedError

from carconnectivity.observable import Observable
from carconnectivity.vehicle import GenericVehicle
from carconnectivity.utils.timeout_lock import TimeoutLock

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.trip import Trip
from carconnectivity_plugins.database.model.location import Location

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import EnumAttribute, FloatAttribute, StringAttribute

    from carconnectivity_plugins.database.plugin import Plugin
    from carconnectivity_plugins.database.model.vehicle import Vehicle

LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.trip_agent")


#  pylint: disable=duplicate-code
# pylint: disable-next=too-many-instance-attributes, too-few-public-methods
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
        ValueError: If vehicle or self.carconnectivity_vehicle is None during initialization.
    Notes:
        - A new trip is started when the vehicle transitions to IGNITION_ON or DRIVING state.
        - A trip is ended when the vehicle transitions from IGNITION_ON/DRIVING to another state.
        - If a previous trip is still open during startup or when starting a new trip,
          it will be logged and closed.
        - Trip records include start/end dates and odometer readings when available.
    """

    def __init__(self, database_plugin: Plugin, session_factory: scoped_session[Session], vehicle: Vehicle, carconnectivity_vehicle: GenericVehicle) -> None:
        if vehicle is None or carconnectivity_vehicle is None:
            raise ValueError("Vehicle or its carconnectivity_vehicle attribute is None")
        self.database_plugin: Plugin = database_plugin
        self.session_factory: scoped_session[Session] = session_factory
        self.vehicle: Vehicle = vehicle
        self.carconnectivity_vehicle: GenericVehicle = carconnectivity_vehicle

        self.last_carconnectivity_state: Optional[GenericVehicle.State] = None
        self.last_parked_position_latitude: Optional[float] = None
        self.last_parked_position_longitude: Optional[float] = None
        self.last_parked_position_time: Optional[datetime] = None
        self.last_parked_location: Optional[Location] = None

        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            self.trip: Optional[Trip] = session.query(Trip).filter(Trip.vehicle == self.vehicle).order_by(Trip.start_date.desc()).first()
            self.trip_lock: TimeoutLock = TimeoutLock()
            if self.trip is not None:
                if self.trip.destination_date is None:
                    LOG.info("Last trip for vehicle %s is still open during startup, closing it now", self.vehicle.vin)
        self.session_factory.remove()

        self.carconnectivity_vehicle.state.add_observer(self.__on_state_change, Observable.ObserverEvent.UPDATED, on_transaction_end=True)
        self.__on_state_change(self.carconnectivity_vehicle.state, Observable.ObserverEvent.UPDATED)

        self.carconnectivity_vehicle.position.latitude.add_observer(self._on_position_latitude_change, Observable.ObserverEvent.UPDATED,
                                                                    on_transaction_end=True)
        self._on_position_latitude_change(self.carconnectivity_vehicle.position.latitude, Observable.ObserverEvent.UPDATED)

        self.carconnectivity_vehicle.position.longitude.add_observer(self._on_position_longitude_change, Observable.ObserverEvent.UPDATED,
                                                                     on_transaction_end=True)
        self._on_position_longitude_change(self.carconnectivity_vehicle.position.longitude, Observable.ObserverEvent.UPDATED)

        self.carconnectivity_vehicle.position.location.uid.add_observer(self._on_position_location_change, Observable.ObserverEvent.UPDATED,
                                                                        on_transaction_end=True)
        self._on_position_location_change(self.carconnectivity_vehicle.position.location.uid, Observable.ObserverEvent.UPDATED)

    def __del__(self) -> None:
        self.carconnectivity_vehicle.state.remove_observer(self.__on_state_change)
        self.carconnectivity_vehicle.position.latitude.remove_observer(self._on_position_latitude_change)
        self.carconnectivity_vehicle.position.longitude.remove_observer(self._on_position_longitude_change)
        self.carconnectivity_vehicle.position.location.uid.remove_observer(self._on_position_location_change)

    # pylint: disable-next=too-many-branches,too-many-statements
    def __on_state_change(self, element: EnumAttribute[GenericVehicle.State], flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            if self.carconnectivity_vehicle is None:
                raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
            if element.enabled and element.value is not None:
                if self.last_carconnectivity_state is not None:
                    with self.session_factory() as session:
                        self.vehicle = session.merge(self.vehicle)
                        session.refresh(self.vehicle)
                        with self.trip_lock:
                            if self.trip is not None:
                                try:
                                    self.trip = session.merge(self.trip)
                                    session.refresh(self.trip)
                                except ObjectDeletedError:
                                    self.trip = session.query(Trip).filter(Trip.vehicle == self.vehicle) \
                                        .order_by(Trip.start_date.desc()).first()
                                    if self.trip is not None:
                                        LOG.info('Last trip for vehicle %s was deleted from database, reloaded last trip', self.vehicle.vin)
                                    else:
                                        LOG.info('Last trip for vehicle %s was deleted from database, no more trips found', self.vehicle.vin)
                            if self.last_carconnectivity_state not in (GenericVehicle.State.IGNITION_ON, GenericVehicle.State.DRIVING) \
                                    and element.value in (GenericVehicle.State.IGNITION_ON, GenericVehicle.State.DRIVING):
                                if self.trip is not None:
                                    LOG.warning("Starting new trip for vehicle %s while previous trip is still open, closing previous trip first",
                                                self.vehicle.vin)
                                    self.trip = None
                                LOG.info("Starting new trip for vehicle %s", self.vehicle.vin)
                                start_date: datetime = element.last_updated if element.last_updated is not None else datetime.now(tz=timezone.utc)
                                new_trip: Trip = Trip(vin=self.vehicle.vin, start_date=start_date)
                                if self.carconnectivity_vehicle.odometer.enabled and \
                                        self.carconnectivity_vehicle.odometer.value is not None:
                                    new_trip.start_odometer = self.carconnectivity_vehicle.odometer.in_locale(locale=self.database_plugin.locale)[0]
                                if not self._update_trip_position(session=session, trip=new_trip, start=True):
                                    # if now no position is available try the last known position
                                    if self.last_parked_position_latitude is not None and self.last_parked_position_longitude is not None:
                                        self._update_trip_position(session=session, trip=new_trip, start=True,
                                                                   latitude=self.last_parked_position_latitude,
                                                                   longitude=self.last_parked_position_longitude,
                                                                   location=self.last_parked_location)
                                try:
                                    session.add(new_trip)
                                    session.commit()
                                    LOG.debug('Added new trip for vehicle %s to database', self.vehicle.vin)
                                    self.trip = new_trip
                                except IntegrityError as err:
                                    session.rollback()
                                    LOG.error('IntegrityError while adding state for vehicle %s to database: %s', self.vehicle.vin, err)
                                except DatabaseError as err:
                                    session.rollback()
                                    LOG.error('DatabaseError while adding trip for vehicle %s to database: %s', self.vehicle.vin, err)
                                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                            elif self.last_carconnectivity_state in (GenericVehicle.State.IGNITION_ON, GenericVehicle.State.DRIVING) \
                                    and element.value not in (GenericVehicle.State.IGNITION_ON, GenericVehicle.State.DRIVING):
                                if self.trip is not None and not self.trip.is_completed():
                                    LOG.info("Ending trip for vehicle %s", self.vehicle.vin)
                                    try:
                                        self.trip.destination_date = element.last_updated if element.last_updated is not None else datetime.now(tz=timezone.utc)
                                        if self.carconnectivity_vehicle.odometer.enabled and \
                                                self.carconnectivity_vehicle.odometer.value is not None:
                                            self.trip.destination_odometer = \
                                                self.carconnectivity_vehicle.odometer.in_locale(locale=self.database_plugin.locale)[0]
                                            LOG.debug('Set destination odometer %.2f for trip of vehicle %s', self.trip.destination_odometer, self.vehicle.vin)
                                        if self._update_trip_position(session=session, trip=self.trip, start=False):
                                            self.trip = None
                                        session.commit()
                                    except DatabaseError as err:
                                        session.rollback()
                                        LOG.error('DatabaseError while ending trip for vehicle %s in database: %s', self.vehicle.vin, err)
                                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    self.session_factory.remove()
                self.last_carconnectivity_state = element.value

    def _on_position_latitude_change(self, element: FloatAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled and element.value is not None:
            self.last_parked_position_latitude = element.value
            self.last_parked_position_time = element.last_changed or element.last_updated
            self._on_position_change()

    def _on_position_longitude_change(self, element: FloatAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled and element.value is not None:
            self.last_parked_position_longitude = element.value
            self.last_parked_position_time = element.last_changed or element.last_updated
            self._on_position_change()

    def _on_position_location_change(self, element: StringAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled and element.value is not None:
            location_object: GenericObject = element.parent
            if isinstance(location_object, Location):
                self.last_parked_location = Location.from_carconnectivity_location(location=location_object)
            self._on_location_change()

    def _on_position_change(self) -> None:
        # Check if there is a finished trip that lacks destination position. We allow 5min after destination_date to set the position.
        if self.trip is not None:
            with self.session_factory() as session:
                self.vehicle = session.merge(self.vehicle)
                session.refresh(self.vehicle)
                with self.trip_lock:
                    try:
                        self.trip = session.merge(self.trip)
                        session.refresh(self.trip)
                    except ObjectDeletedError:
                        self.trip = session.query(Trip).filter(Trip.vehicle == self.vehicle) \
                            .order_by(Trip.start_date.desc()).first()
                        if self.trip is not None:
                            LOG.info('Last trip for vehicle %s was deleted from database, reloaded last trip', self.vehicle.vin)
                        else:
                            LOG.info('Last trip for vehicle %s was deleted from database, no more trips found', self.vehicle.vin)
                    if self.trip is not None and self.trip.destination_date is not None and self.trip.destination_position_latitude is None \
                            and self.last_parked_position_time is not None \
                            and self.last_parked_position_time < (self.trip.destination_date + timedelta(minutes=5)):
                        self._update_trip_position(session, self.trip, start=False,
                                                   latitude=self.last_parked_position_latitude,
                                                   longitude=self.last_parked_position_longitude,
                                                   location=self.last_parked_location)
            self.session_factory.remove()

    def _on_location_change(self) -> None:
        # Check if there is a finished trip that lacks destination location. We allow 5min after destination_date to set the position.
        if self.trip is not None and self.last_parked_location is not None:
            with self.session_factory() as session:
                self.vehicle = session.merge(self.vehicle)
                session.refresh(self.vehicle)
                with self.trip_lock:
                    try:
                        self.trip = session.merge(self.trip)
                        session.refresh(self.trip)
                    except ObjectDeletedError:
                        self.trip = session.query(Trip).filter(Trip.vehicle == self.vehicle) \
                            .order_by(Trip.start_date.desc()).first()
                        if self.trip is not None:
                            LOG.info('Last trip for vehicle %s was deleted from database, reloaded last trip', self.vehicle.vin)
                        else:
                            LOG.info('Last trip for vehicle %s was deleted from database, no more trips found', self.vehicle.vin)
                    if self.trip is not None and self.trip.destination_date is not None and self.trip.destination_location is None \
                            and self.last_parked_position_time is not None \
                            and self.last_parked_position_time < (self.trip.destination_date + timedelta(minutes=5)):
                        location: Location = Location.from_carconnectivity_location(location=self.last_parked_location)
                        try:
                            location = session.merge(location)
                            self.trip.destination_location = location
                            session.commit()
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while merging location for trip of vehicle %s in database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
            self.session_factory.remove()

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments,too-many-branches
    def _update_trip_position(self, session: Session, trip: Trip, start: bool,
                              latitude: Optional[float] = None, longitude: Optional[float] = None, location: Optional[Location] = None) -> bool:
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
        if latitude is None or longitude is None:
            if self.carconnectivity_vehicle.position.enabled and self.carconnectivity_vehicle.position.latitude.enabled \
                    and self.carconnectivity_vehicle.position.longitude.enabled \
                    and self.carconnectivity_vehicle.position.latitude.value is not None \
                    and self.carconnectivity_vehicle.position.longitude.value is not None:
                latitude = self.carconnectivity_vehicle.position.latitude.value
                longitude = self.carconnectivity_vehicle.position.longitude.value
        if latitude is not None and longitude is not None:
            if start:
                if trip.start_position_latitude is None and trip.start_position_longitude is None:
                    try:
                        trip.start_position_latitude = latitude
                        trip.start_position_longitude = longitude
                        session.commit()
                    except DatabaseError as err:
                        session.rollback()
                        LOG.error('DatabaseError while updating position for trip of vehicle %s in database: %s', self.vehicle.vin, err)
                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                if location is None:
                    if trip.start_location is None and self.carconnectivity_vehicle.position.location.enabled:
                        location = Location.from_carconnectivity_location(location=self.carconnectivity_vehicle.position.location)
                if location is not None:
                    try:
                        location = session.merge(location)
                        trip.start_location = location
                        session.commit()
                    except DatabaseError as err:
                        session.rollback()
                        LOG.error('DatabaseError while merging location for trip of vehicle %s in database: %s', self.vehicle.vin, err)
                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                return True
            if trip.destination_position_latitude is None and trip.destination_position_longitude is None:
                try:
                    trip.destination_position_latitude = self.carconnectivity_vehicle.position.latitude.value
                    trip.destination_position_longitude = self.carconnectivity_vehicle.position.longitude.value
                    session.commit()
                except DatabaseError as err:
                    session.rollback()
                    LOG.error('DatabaseError while updating position for trip of vehicle %s in database: %s', self.vehicle.vin, err)
                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
            if location is None:
                if trip.destination_location is None and self.carconnectivity_vehicle.position.location.enabled:
                    location = Location.from_carconnectivity_location(location=self.carconnectivity_vehicle.position.location)
            if location is not None:
                try:
                    location = session.merge(location)
                    trip.destination_location = location
                    session.commit()
                except DatabaseError as err:
                    session.rollback()
                    LOG.error('DatabaseError while merging location for trip of vehicle %s in database: %s', self.vehicle.vin, err)
                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
            return True
        return False
