"""Agent for persisting vehicle odometer measurements."""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

import logging

from carconnectivity.observable import Observable
from carconnectivity.utils.timeout_lock import TimeoutLock
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm.exc import ObjectDeletedError

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.odometer import Odometer

if TYPE_CHECKING:
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session
    from carconnectivity.attributes import FloatAttribute
    from carconnectivity.vehicle import GenericVehicle

    from carconnectivity_plugins.database.model.vehicle import Vehicle
    from carconnectivity_plugins.database.plugin import Plugin


LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.odometer_agent")


class OdometerAgent(BaseAgent):  # pylint: disable=too-few-public-methods
    """Persist every enabled odometer update received from a vehicle."""

    def __init__(self, database_plugin: Plugin, session_factory: scoped_session[Session], vehicle: Vehicle,
                 carconnectivity_vehicle: GenericVehicle) -> None:
        if vehicle is None or carconnectivity_vehicle is None:
            raise ValueError("Vehicle or its carconnectivity_vehicle attribute is None")
        self.database_plugin: Plugin = database_plugin
        self.session_factory: scoped_session[Session] = session_factory
        self.vehicle: Vehicle = vehicle
        self.carconnectivity_vehicle: GenericVehicle = carconnectivity_vehicle

        with self.session_factory() as session:
            self.vehicle = session.merge(self.vehicle)
            session.refresh(self.vehicle)
            self.last_odometer: Optional[Odometer] = session.query(Odometer).filter(Odometer.vehicle == self.vehicle) \
                .order_by(Odometer.first_date.desc()).first()
            self.last_odometer_lock: TimeoutLock = TimeoutLock()
            self.carconnectivity_vehicle.odometer.add_observer(self.__on_odometer_change, Observable.ObserverEvent.UPDATED)
            self.__on_odometer_change(self.carconnectivity_vehicle.odometer, Observable.ObserverEvent.UPDATED)
        self.session_factory.remove()

    def __del__(self) -> None:
        self.carconnectivity_vehicle.odometer.remove_observer(self.__on_odometer_change)

    def __on_odometer_change(self, element: FloatAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            converted_value: Optional[float] = element.in_locale(locale=self.database_plugin.locale)[0]
            with self.last_odometer_lock:
                with self.session_factory() as session:
                    self.vehicle = session.merge(self.vehicle)
                    session.refresh(self.vehicle)
                    if self.last_odometer is not None:
                        try:
                            self.last_odometer = session.merge(self.last_odometer)
                            session.refresh(self.last_odometer)
                        except ObjectDeletedError:
                            self.last_odometer = session.query(Odometer).filter(Odometer.vehicle == self.vehicle) \
                                .order_by(Odometer.first_date.desc()).first()
                    if element.last_updated is not None \
                            and (self.last_odometer is None or (converted_value is not None
                                                                and self.last_odometer.odometer is not None
                                                                and converted_value > self.last_odometer.odometer
                                                                and element.last_updated > self.last_odometer.last_date)):
                        new_odometer = Odometer(vin=self.vehicle.vin, first_date=element.last_updated,
                                                last_date=element.last_updated, odometer=converted_value)
                        try:
                            session.add(new_odometer)
                            session.commit()
                            self.last_odometer = new_odometer
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding odometer for vehicle %s to database: %s', self.vehicle.vin, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding odometer for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_odometer is not None and element.last_updated is not None \
                            and (self.last_odometer.last_date is None or element.last_updated > self.last_odometer.last_date):
                        try:
                            self.last_odometer.last_date = element.last_updated
                            session.commit()
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while updating odometer for vehicle %s to database: %s', self.vehicle.vin, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()