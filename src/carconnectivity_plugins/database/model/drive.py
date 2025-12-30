""" This module contains the Drive database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

import logging

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from carconnectivity.drive import GenericDrive
from carconnectivity.observable import Observable
from carconnectivity.attributes import EnumAttribute

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.agents.drive_state_agent import DriveStateAgent
from carconnectivity_plugins.database.model.base import Base

if TYPE_CHECKING:
    from sqlalchemy.orm.session import Session
    from sqlalchemy import Constraint

LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.model.drive")


class Drive(Base):
    """
    Database model representing a vehicle drive/trip.
    This class maps to the 'drives' table and stores information about individual
    vehicle drives, including their relationship to vehicles and various drive
    attributes tracked through CarConnectivity.
    Attributes:
        id (int): Primary key for the drive record.
        vin (str): Vehicle Identification Number, foreign key to vehicles table.
        vehicle (Vehicle): SQLAlchemy relationship to the associated Vehicle.
        drive_id (Optional[str]): Optional identifier for the drive.
        type (Optional[GenericDrive.Type]): Type/category of the drive.
        carconnectivity_drive (Optional[GenericDrive]): Reference to the CarConnectivity
            drive object (not persisted to database).
        agents (list[BaseAgent]): List of agents monitoring this drive (not persisted
            to database).
    Args:
        vin (str): Vehicle Identification Number to associate this drive with.
    Methods:
        connect: Establishes connection between database model and CarConnectivity
            drive object, sets up observers, and initializes agents.
    """
    __tablename__: str = 'drives'
    __allow_unmapped__: bool = True
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "drive_id", name="vin_drive_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    drive_id: Mapped[Optional[str]]
    type: Mapped[Optional[GenericDrive.Type]]

    carconnectivity_drive: Optional[GenericDrive] = None
    agents: list[BaseAgent] = []

    def __init__(self, vin, drive_id: Optional[str] = None) -> None:
        self.vin = vin
        self.drive_id = drive_id

    def connect(self, session: Session, carconnectivity_drive: GenericDrive) -> None:
        """
        Connect a CarConnectivity drive object to this database model instance.
        This method establishes a connection between the database drive model and a CarConnectivity drive object,
        sets up observers for type changes, synchronizes the drive type if available, and initializes the drive state agent.
        Args:
            session (Session): The database session to use for operations.
            carconnectivity_drive (GenericDrive): The CarConnectivity drive object to connect to this database model.
        Returns:
            None
        Note:
            - Adds an observer to monitor type changes in the vehicle
            - Automatically syncs the drive type if enabled and has a value
            - Creates and registers a DriveStateAgent for managing drive state
        """
        if self.carconnectivity_drive is not None:
            raise ValueError("Can only connect once! Drive already connected with database model")
        self.carconnectivity_drive = carconnectivity_drive
        self.carconnectivity_drive.type.add_observer(self.__on_type_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
        if self.carconnectivity_drive.type.enabled and self.carconnectivity_drive.type.value is not None \
                and self.type != self.carconnectivity_drive.type.value:
            self.type = self.carconnectivity_drive.type.value

        drive_state_agent: DriveStateAgent = DriveStateAgent(session, self)  # type: ignore[assignment]
        self.agents.append(drive_state_agent)
        LOG.debug("Adding DriveStateAgent to drive %s of vehicle %s", self.drive_id, self.vin)

    def __on_type_change(self, element: EnumAttribute[GenericDrive.Type], flags: Observable.ObserverEvent) -> None:
        del flags
        if element.value is not None and self.type != element.value:
            self.type = element.value
