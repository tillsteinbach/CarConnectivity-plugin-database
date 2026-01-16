""" This module contains the Vehicle database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

import logging

from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from carconnectivity.vehicle import GenericVehicle, ElectricVehicle
from carconnectivity.observable import Observable
from carconnectivity.attributes import StringAttribute, IntegerAttribute, EnumAttribute

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.agents.state_agent import StateAgent
from carconnectivity_plugins.database.agents.charging_agent import ChargingAgent
from carconnectivity_plugins.database.agents.climatization_agent import ClimatizationAgent
from carconnectivity_plugins.database.agents.trip_agent import TripAgent
from carconnectivity_plugins.database.model.base import Base
from carconnectivity_plugins.database.model.drive import Drive

if TYPE_CHECKING:
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session

    from carconnectivity_plugins.database.plugin import Plugin

LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.model.vehicle")


# pylint: disable-next=too-few-public-methods
class Vehicle(Base):
    """
    SQLAlchemy model representing a vehicle in the database.

    This class maps vehicle data from the CarConnectivity framework to database records,
    maintaining synchronization between the CarConnectivity vehicle objects and their
    corresponding database entries.

    Attributes:
        vin (str): Vehicle Identification Number, used as the primary key.
        name (Optional[str]): The name or nickname of the vehicle.
        manufacturer (Optional[str]): The manufacturer of the vehicle.
        model (Optional[str]): The model name of the vehicle.
        model_year (Optional[int]): The model year of the vehicle.
        type (Optional[GenericVehicle.Type]): The type of vehicle (e.g., electric, hybrid).
        license_plate (Optional[str]): The license plate number of the vehicle.
        carconnectivity_vehicle (Optional[GenericVehicle]): Reference to the associated
            CarConnectivity GenericVehicle object (not persisted in database).

    Methods:
        __init__(vin): Initialize a new Vehicle instance with the given VIN.
        connect(carconnectivity_vehicle): Connect this database model to a CarConnectivity
            vehicle object and set up observers to sync changes.

    Notes:
        The class uses SQLAlchemy's mapped_column and Mapped types for database mapping.
        Observer callbacks are registered to automatically update database fields when
        corresponding values change in the CarConnectivity vehicle object.
    """
    __tablename__ = 'vehicles'
    __allow_unmapped__ = True

    vin: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[Optional[str]]
    manufacturer: Mapped[Optional[str]]
    model: Mapped[Optional[str]]
    model_year: Mapped[Optional[int]]
    type: Mapped[Optional[GenericVehicle.Type]]
    license_plate: Mapped[Optional[str]]

    agents: list[BaseAgent] = []

    def __init__(self, vin) -> None:
        self.vin = vin

    # pylint: disable-next=too-many-branches,too-many-statements
    def connect(self, database_plugin: Plugin, session_factory: scoped_session[Session], carconnectivity_vehicle: GenericVehicle) -> None:
        """
        Connect a CarConnectivity vehicle instance to this database vehicle model and set up observers.
        This method establishes a connection between a CarConnectivity vehicle object and this database vehicle model.
        It registers observers for various vehicle attributes (name, manufacturer, model, model_year, type, and license_plate)
        to monitor changes and synchronize them with the database. If the attributes are enabled and have values that differ
        from the current database values, they are immediately synchronized.
        Args:
            carconnectivity_vehicle (GenericVehicle): The CarConnectivity vehicle instance to connect and observe.
        Returns:
            None
        Note:
            - Observers are triggered on transaction end to batch updates
            - Only enabled attributes are synchronized
            - The type attribute is only synchronized if it's not None
        """
        if self.agents:
            raise ValueError("Can only connect once! Vehicle already connected with database model")
        vin: str = self.vin
        carconnectivity_vehicle.name.add_observer(self.__on_name_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
        if carconnectivity_vehicle.name.enabled and self.name != carconnectivity_vehicle.name.value:
            self.name = carconnectivity_vehicle.name.value
        carconnectivity_vehicle.manufacturer.add_observer(self.__on_manufacturer_change, Observable.ObserverEvent.VALUE_CHANGED,
                                                          on_transaction_end=True)
        if carconnectivity_vehicle.manufacturer.enabled and self.manufacturer != carconnectivity_vehicle.manufacturer.value:
            self.manufacturer = carconnectivity_vehicle.manufacturer.value
        carconnectivity_vehicle.model.add_observer(self.__on_model_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
        if carconnectivity_vehicle.model.enabled and self.model != carconnectivity_vehicle.model.value:
            self.model = carconnectivity_vehicle.model.value
        carconnectivity_vehicle.model_year.add_observer(self.__on_model_year_change, Observable.ObserverEvent.VALUE_CHANGED,
                                                        on_transaction_end=True)
        if carconnectivity_vehicle.model_year.enabled and self.model_year != carconnectivity_vehicle.model_year.value:
            self.model_year = carconnectivity_vehicle.model_year.value
        carconnectivity_vehicle.type.add_observer(self.__on_type_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
        if carconnectivity_vehicle.type.enabled and carconnectivity_vehicle.type.value is not None \
                and self.type != carconnectivity_vehicle.type.value:
            self.type = carconnectivity_vehicle.type.value
        carconnectivity_vehicle.license_plate.add_observer(self.__on_license_plate_change, Observable.ObserverEvent.VALUE_CHANGED,
                                                           on_transaction_end=True)
        if carconnectivity_vehicle.license_plate.enabled and self.license_plate != carconnectivity_vehicle.license_plate.value:
            self.license_plate = carconnectivity_vehicle.license_plate.value

        with session_factory() as session:
            for drive_id, drive in carconnectivity_vehicle.drives.drives.items():
                drive_db: Optional[Drive] = session.query(Drive).filter(Drive.vin == vin, Drive.drive_id == drive_id).first()
                if drive_db is None:
                    drive_db = Drive(vin=vin, drive_id=drive_id)
                    try:
                        session.add(drive_db)
                        session.commit()
                        LOG.debug('Added new drive %s for vehicle %s to database', drive_id, vin)
                        drive_db.connect(database_plugin, session_factory, drive)
                    except IntegrityError as err:
                        session.rollback()
                        LOG.error('IntegrityError while adding drive %s for vehicle %s to database, likely due to concurrent addition: %s', drive_id, vin,
                                  err)
                        database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    except DatabaseError as err:
                        session.rollback()
                        LOG.error('DatabaseError while adding drive %s for vehicle %s to database: %s', drive_id, vin, err)
                        database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                else:
                    drive_db.connect(database_plugin, session_factory, drive)
                    LOG.debug('Connecting drive %s for vehicle %s', drive_id, vin)
            state_agent: StateAgent = StateAgent(database_plugin, session_factory, self, carconnectivity_vehicle)
            self.agents.append(state_agent)
            LOG.debug("Adding StateAgent to vehicle %s", vin)
            climazination_agent: ClimatizationAgent = ClimatizationAgent(database_plugin, session_factory, self, carconnectivity_vehicle)
            self.agents.append(climazination_agent)
            LOG.debug("Adding ClimatizationAgent to vehicle %s", vin)
            trip_agent: TripAgent = TripAgent(database_plugin, session_factory, self, carconnectivity_vehicle)
            self.agents.append(trip_agent)
            LOG.debug("Adding TripAgent to vehicle %s", vin)

            if isinstance(carconnectivity_vehicle, ElectricVehicle):
                charging_agent: ChargingAgent = ChargingAgent(database_plugin, session_factory, self, carconnectivity_vehicle)
                self.agents.append(charging_agent)
                LOG.debug("Adding ChargingAgent to vehicle %s", vin)
        session_factory.remove()

    def __on_name_change(self, element: StringAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.name != element.value:
            self.name = element.value

    def __on_manufacturer_change(self, element: StringAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.manufacturer != element.value:
            self.manufacturer = element.value

    def __on_model_change(self, element: StringAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.model != element.value:
            self.model = element.value

    def __on_model_year_change(self, element: IntegerAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.model_year != element.value:
            self.model_year = element.value

    def __on_type_change(self, element: EnumAttribute[GenericVehicle.Type], flags: Observable.ObserverEvent) -> None:
        del flags
        if element.value is not None and self.type != element.value:
            self.type = element.value

    def __on_license_plate_change(self, element: StringAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.license_plate != element.value:
            self.license_plate = element.value
