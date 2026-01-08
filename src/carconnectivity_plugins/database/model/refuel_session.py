""" This module contains the Vehicle refueling sessions database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from datetime import datetime

from sqlalchemy import ForeignKey, Table, Column, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from sqlalchemy_utc import UtcDateTime

from carconnectivity_plugins.database.model.base import Base


if TYPE_CHECKING:
    from sqlalchemy import Constraint


refuel_tag_association_table = Table('refuel_sessions_tags', Base.metadata,
                                     Column('refuel_sessions_id', ForeignKey('refuel_sessions.id')),
                                     Column('tags_name', ForeignKey('tags.name'))
                                     )


class RefuelSession(Base):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """
    Represents a refueling session for a vehicle.
    This class models a refueling session, tracking the fuel level changes and associated
    metadata such as location, odometer reading, and cost information. It captures the
    session details including start and end fuel levels, position data, and optional
    pricing information.
    Attributes:
        id (int): Primary key identifier for the refueling session.
        vin (str): Vehicle Identification Number, foreign key to the vehicles table.
        vehicle (Vehicle): Relationship to the associated Vehicle object.
        session_date (datetime, optional): Timestamp when the refueling occurred.
        start_level (float, optional): Fuel level percentage before refueling.
        end_level (float, optional): Fuel level percentage after refueling.
        session_position_latitude (float, optional): Latitude coordinate of refueling location.
        session_position_longitude (float, optional): Longitude coordinate of refueling location.
        session_odometer (float, optional): Odometer reading at the time of refueling.
        location_uid (str, optional): Unique identifier for the location, foreign key to locations table.
        location (Location, optional): Relationship to the associated Location object.
        price_per_l (float, optional): Price per liter of fuel.
        real_refueled (float, optional): Actual amount of fuel added in liters.
        real_cost (float, optional): Total cost of the refueling session.
        tags (list[Tag]): Associated tags for categorizing or labeling the session.
    """

    __tablename__: str = 'refuel_sessions'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "session_date", name="vin_session_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    session_date: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    start_level: Mapped[Optional[float]]
    end_level: Mapped[Optional[float]]
    session_position_latitude: Mapped[Optional[float]]
    session_position_longitude: Mapped[Optional[float]]
    session_odometer: Mapped[Optional[float]]
    location_uid: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.uid"))
    location: Mapped[Optional["Location"]] = relationship("Location")
    price_per_l: Mapped[Optional[float]]
    real_refueled: Mapped[Optional[float]]
    real_cost: Mapped[Optional[float]]
    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=refuel_tag_association_table, backref=backref("refuel_sessions"))

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, vin: str, session_date: Optional[datetime] = None, start_level: Optional[float] = None,
                 end_level: Optional[float] = None, session_position_latitude: Optional[float] = None,
                 session_position_longitude: Optional[float] = None, session_odometer: Optional[float] = None,
                 location_uid: Optional[str] = None, price_per_l: Optional[float] = None,
                 real_refueled: Optional[float] = None, real_cost: Optional[float] = None) -> None:
        self.vin = vin
        self.session_date = session_date
        self.start_level = start_level
        self.end_level = end_level
        self.session_position_latitude = session_position_latitude
        self.session_position_longitude = session_position_longitude
        self.session_odometer = session_odometer
        self.location_uid = location_uid
        self.price_per_l = price_per_l
        self.real_refueled = real_refueled
        self.real_cost = real_cost
