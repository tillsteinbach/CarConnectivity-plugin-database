"""
Agent for monitoring and persisting drive levels to safe refuel sessions to the database.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging

from sqlalchemy.exc import DatabaseError, IntegrityError

from carconnectivity.observable import Observable
from carconnectivity.vehicle import GenericVehicle
from carconnectivity.drive import CombustionDrive
from carconnectivity.location import Location as CarConnectivityLocation
from carconnectivity.position import Position
from carconnectivity_services.base.service import BaseService, ServiceType
from carconnectivity_services.location.location_service import LocationService

from carconnectivity_plugins.database.agents.base_agent import BaseAgent

from carconnectivity_plugins.database.model.refuel_session import RefuelSession
from carconnectivity_plugins.database.model.location import Location

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import LevelAttribute, FloatAttribute

    from carconnectivity_plugins.database.plugin import Plugin


LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.climatization_agent")


# pylint: disable=duplicate-code
# pylint: disable-next=too-few-public-methods,too-many-instance-attributes
class RefuelAgent(BaseAgent):
    """
    Agent responsible for tracking and recording vehicle refueling sessions.
    This agent monitors fuel level changes in combustion vehicles and automatically
    creates database records when a refueling event is detected (fuel level increase
    of more than 5%). It also enriches refuel sessions with additional data such as
    odometer readings, GPS position, and gas station location information.
    Attributes:
        database_plugin (Plugin): Reference to the database plugin instance.
        session_factory (scoped_session[Session]): SQLAlchemy session factory for database operations.
        carconnectivity_drive (CombustionDrive): The combustion drive system being monitored.
        carconnectivity_vehicle (GenericVehicle): The vehicle containing the drive system.
        last_level (Optional[float]): The last recorded fuel level percentage.
    Raises:
        ValueError: If carconnectivity_drive is None, not a CombustionDrive instance,
                    not within a Vehicle, or the vehicle doesn't have a VIN value set.
    Note:
        The agent uses a 5% threshold to avoid false positives from minor fuel level
        fluctuations reported by the vehicle.
    """

    def __init__(self, database_plugin: Plugin, session_factory: scoped_session[Session], carconnectivity_drive: CombustionDrive) -> None:
        if carconnectivity_drive is None:
            raise ValueError("carconnectivity_drive attribute is None")
        self.database_plugin: Plugin = database_plugin
        self.session_factory: scoped_session[Session] = session_factory
        if not isinstance(carconnectivity_drive, CombustionDrive):
            raise ValueError("carconnectivity_drive needs to be a CombustionDrive")
        self.carconnectivity_drive: CombustionDrive = carconnectivity_drive
        if carconnectivity_drive.parent is None or not isinstance(carconnectivity_drive.parent.parent, GenericVehicle):
            raise ValueError("carconnectivity_drive is not within a Vehicle")
        self.carconnectivity_vehicle: GenericVehicle = carconnectivity_drive.parent.parent
        if not self.carconnectivity_vehicle.vin.enabled or self.carconnectivity_vehicle.vin.value is None:
            raise ValueError("carconnectivity_drive is not within a Vehicle that has a VIN value set")

        self.last_level: Optional[float] = None
        self.last_latitude: Optional[float] = None
        self.last_longitude: Optional[float] = None

        self.carconnectivity_drive.level.add_observer(self.__on_level_change, Observable.ObserverEvent.UPDATED)
        if self.carconnectivity_drive.level.enabled:
            self.__on_level_change(self.carconnectivity_drive.level, Observable.ObserverEvent.UPDATED)

        self.carconnectivity_vehicle.position.longitude.add_observer(self.__on_longitude_change, Observable.ObserverEvent.UPDATED)

    def __del__(self) -> None:
        self.carconnectivity_drive.level.remove_observer(self.__on_level_change)
        self.carconnectivity_vehicle.position.longitude.remove_observer(self.__on_longitude_change)

    def __on_level_change(self, element: LevelAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled and element.value is not None:
            # Sometimes the car finds a few percent of fuel somewhere. Better give it a 5% margin
            if self.last_level is not None and self.last_level < (element.value - 5) and self.carconnectivity_vehicle.vin.value is not None:
                new_session: RefuelSession = RefuelSession(vin=self.carconnectivity_vehicle.vin.value, session_date=element.last_changed,
                                                           start_level=self.last_level, end_level=element.value)
                with self.session_factory() as session:
                    try:
                        session.add(new_session)
                        self._update_session_odometer(session, new_session)
                        self._update_session_position(session, new_session)
                        session.commit()
                        LOG.debug('Added new refuel session for vehicle %s to database', self.carconnectivity_vehicle.vin.value)
                        self.last_refuel_session = new_session
                    except IntegrityError as err:
                        session.rollback()
                        LOG.error('IntegrityError while adding refuel session for vehicle %s to database: %s', self.carconnectivity_vehicle.vin.value, err)
                    except DatabaseError as err:
                        session.rollback()
                        LOG.error('DatabaseError while adding refuel session for vehicle %s to database: %s', self.carconnectivity_vehicle.vin.value, err)
                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()
            self.last_level = element.value

    def __on_longitude_change(self, element: FloatAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled and element.value is not None:
            self.last_longitude = element.value
            if isinstance(element.parent, Position) and element.parent.latitude.enabled and element.parent.latitude.value is not None:
                self.last_latitude = element.parent.latitude.value

    def _update_session_odometer(self, session: Session, refuel_session: RefuelSession) -> None:
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
        if self.carconnectivity_vehicle.odometer.enabled:
            if refuel_session.session_odometer is None:
                try:
                    refuel_session.session_odometer = self.carconnectivity_vehicle.odometer.in_locale(locale=self.database_plugin.locale)[0]
                except DatabaseError as err:
                    session.rollback()
                    LOG.error('DatabaseError while updating odometer for refuel session of vehicle %s in database: %s',
                              self.carconnectivity_vehicle.vin.value, err)
                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access

    def _update_session_position(self, session: Session, refuel_session: RefuelSession) -> None:
        if self.carconnectivity_vehicle is None:
            raise ValueError("Vehicle's carconnectivity_vehicle attribute is None")
        if self.last_latitude is not None and self.last_longitude is not None:
            if refuel_session.session_position_latitude is None and refuel_session.session_position_longitude is None:
                try:
                    refuel_session.session_position_latitude = self.last_latitude
                    refuel_session.session_position_longitude = self.last_longitude
                except DatabaseError as err:
                    session.rollback()
                    LOG.error('DatabaseError while updating position for refuel session of vehicle %s in database: %s',
                              self.carconnectivity_vehicle.vin.value, err)
                    self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
            if refuel_session.location is None and self.carconnectivity_vehicle.position.enabled \
                    and refuel_session.session_position_latitude is not None and refuel_session.session_position_longitude is not None:
                location_services: Optional[list[BaseService]] = self.database_plugin.car_connectivity.get_services_for(ServiceType.LOCATION_GAS_STATION)
                if location_services is None or len(location_services) == 0:
                    LOG.debug('No LocationService available to resolve location from position for refuel session')
                    return
                location_result: Optional[CarConnectivityLocation] = None
                for location_service in location_services:
                    if location_service is not None and isinstance(location_service, LocationService):
                        location_result = location_service.gas_station_from_lat_lon(
                            latitude=refuel_session.session_position_latitude,
                            longitude=refuel_session.session_position_longitude,
                            radius=150,
                            location=None)
                        if location_result is not None:
                            break
                if location_result is not None:
                    LOG.debug('Resolved location from position (%s, %s)', refuel_session.session_position_latitude,
                              refuel_session.session_position_longitude)
                    location: Location = Location.from_carconnectivity_location(location=location_result)
                    try:
                        location = session.merge(location)
                        refuel_session.location = location
                    except DatabaseError as err:
                        session.rollback()
                        LOG.error('DatabaseError while merging location for refuel session of vehicle %s in database: %s',
                                  self.carconnectivity_vehicle.vin.value, err)
                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
