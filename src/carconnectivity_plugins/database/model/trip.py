""" This module contains the Vehicle trip database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from datetime import datetime

from sqlalchemy import ForeignKey, Table, Column, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from sqlalchemy_utc import UtcDateTime

from carconnectivity_plugins.database.model.base import Base

if TYPE_CHECKING:
    from sqlalchemy import Constraint


trip_tag_association_table = Table('trips_tags', Base.metadata,
                                   Column('trips_id', ForeignKey('trips.id')),
                                   Column('tags_name', ForeignKey('tags.name'))
                                   )


class Trip(Base):  # pylint: disable=too-few-public-methods
    """
    Represents a vehicle trip in the database.

    A Trip records information about a journey made by a vehicle, including start and
    destination details such as timestamps, positions, and mileage readings. Trips can
    be associated with tags for categorization and filtering.

    Attributes:
        id (int): Primary key identifier for the trip.
        vin (str): Vehicle Identification Number, foreign key to vehicles table.
        vehicle (Vehicle): Relationship to the associated Vehicle object.
        start_date (datetime): UTC timestamp when the trip started.
        destination_date (datetime, optional): UTC timestamp when the trip ended.
        start_position_latitude (float, optional): Latitude coordinate of trip start location.
        start_position_longitude (float, optional): Longitude coordinate of trip start location.
        destination_position_latitude (float, optional): Latitude coordinate of trip destination.
        destination_position_longitude (float, optional): Longitude coordinate of trip destination.
        start_odometer (float, optional): Vehicle mileage in kilometers at trip start.
        destination_odometer (float, optional): Vehicle mileage in kilometers at trip end.
        tags (list[Tag]): List of tags associated with this trip for categorization.

    Args:
        vin (str): Vehicle Identification Number for the trip.
        start_date (datetime): The starting timestamp of the trip.
        start_position_latitude (float, optional): Latitude coordinate of trip start location.
        start_position_longitude (float, optional): Longitude coordinate of trip start location.
        start_odometer (float, optional): Vehicle mileage in kilometers at trip start.
    """
    __tablename__: str = 'trips'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "start_date", name="vin_start_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    start_date: Mapped[datetime] = mapped_column(UtcDateTime)
    destination_date: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    start_position_latitude: Mapped[Optional[float]]
    start_position_longitude: Mapped[Optional[float]]
    start_location_uid: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.uid"))
    start_location: Mapped[Optional["Location"]] = relationship("Location", foreign_keys=[start_location_uid])
    destination_position_latitude: Mapped[Optional[float]]
    destination_position_longitude: Mapped[Optional[float]]
    destination_location_uid: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.uid"))
    destination_location: Mapped[Optional["Location"]] = relationship("Location", foreign_keys=[destination_location_uid])
    start_odometer: Mapped[Optional[float]]
    destination_odometer: Mapped[Optional[float]]

    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=trip_tag_association_table, backref=backref("trips"))

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, vin: str, start_date: datetime, start_position_latitude: Optional[float] = None,
                 start_position_longitude: Optional[float] = None, start_odometer: Optional[float] = None) -> None:
        self.vin = vin
        self.start_date = start_date
        self.start_position_latitude = start_position_latitude
        self.start_position_longitude = start_position_longitude
        self.start_odometer = start_odometer

    def is_completed(self) -> bool:
        """Returns True if the trip has been completed (i.e., has a destination date)."""
        return self.destination_date is not None
