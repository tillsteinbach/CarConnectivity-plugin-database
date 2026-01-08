""" This module contains the Vehicle charging sessions database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from datetime import datetime

from sqlalchemy import ForeignKey, Table, Column, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from sqlalchemy_utc import UtcDateTime

from carconnectivity.charging import Charging

from carconnectivity_plugins.database.model.base import Base


if TYPE_CHECKING:
    from sqlalchemy import Constraint


charging_tag_association_table = Table('charging_sessions_tags', Base.metadata,
                                       Column('charging_sessions_id', ForeignKey('charging_sessions.id')),
                                       Column('tags_name', ForeignKey('tags.name'))
                                       )


class ChargingSession(Base):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """
    Represents a charging session for an electric vehicle.
    This class models a complete charging session lifecycle, tracking various timestamps
    and metrics from when the vehicle is plugged in until it is disconnected. It captures
    connection events (plug, lock, charge start/end, unlock, unplug) along with session
    metadata such as battery levels, charge type, location, and odometer readings.
    Attributes:
        id (int): Primary key identifier for the charging session.
        vin (str): Vehicle Identification Number, foreign key to the vehicles table.
        vehicle (Vehicle): Relationship to the associated Vehicle object.
        plug_connected_date (datetime, optional): Timestamp when the plug was connected.
        plug_locked_date (datetime, optional): Timestamp when the plug was locked.
        plug_unlocked_date (datetime, optional): Timestamp when the plug was unlocked.
        session_start_date (datetime, optional): Timestamp when charging started.
        session_end_date (datetime, optional): Timestamp when charging ended.
        plug_disconnected_date (datetime, optional): Timestamp when the plug was disconnected.
        start_level (float, optional): Battery level percentage at session start.
        end_level (float, optional): Battery level percentage at session end.
        session_charge_type (Charging.ChargingType, optional): Type of charging (e.g., AC, DC).
        session_position_latitude (float, optional): Latitude coordinate of charging location.
        session_position_longitude (float, optional): Longitude coordinate of charging location.
        session_odometer (float, optional): Odometer reading at session start.
        charging_type (Charging.ChargingType, optional): General charging type used during session.
        tags (list[Tag]): Associated tags for categorizing or labeling the session.
    The class provides various helper methods to query the current and historical state
    of the charging session, such as whether the vehicle is currently connected, locked,
    or actively charging.
    """

    __tablename__: str = 'charging_sessions'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "session_start_date", name="vin_session_start_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    plug_connected_date: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    plug_locked_date: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    plug_unlocked_date: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    session_start_date: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    session_end_date: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    plug_disconnected_date: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    start_level: Mapped[Optional[float]]
    end_level: Mapped[Optional[float]]
    session_charge_type: Mapped[Optional[Charging.ChargingType]]
    session_position_latitude: Mapped[Optional[float]]
    session_position_longitude: Mapped[Optional[float]]
    session_odometer: Mapped[Optional[float]]
    charging_type: Mapped[Optional[Charging.ChargingType]]
    location_uid: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.uid"))
    location: Mapped[Optional["Location"]] = relationship("Location")
    charging_station_uid: Mapped[Optional[str]] = mapped_column(ForeignKey("charging_stations.uid"))
    charging_station: Mapped[Optional["ChargingStation"]] = relationship("ChargingStation")
    meter_start_kwh: Mapped[Optional[float]]
    meter_end_kwh: Mapped[Optional[float]]
    price_per_kwh: Mapped[Optional[float]]
    price_per_min: Mapped[Optional[float]]
    price_per_session: Mapped[Optional[float]]
    real_charged: Mapped[Optional[float]]
    real_cost: Mapped[Optional[float]]
    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=charging_tag_association_table, backref=backref("charging_sessions"))

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, vin: str, plug_connected_date: Optional[datetime] = None, plug_locked_date: Optional[datetime] = None,
                 session_start_date: Optional[datetime] = None, start_level: Optional[float] = None,
                 session_charge_type: Optional[Charging.ChargingType] = None, session_position_latitude: Optional[float] = None,
                 session_position_longitude: Optional[float] = None, session_odometer: Optional[float] = None,
                 charging_type: Optional[Charging.ChargingType] = None) -> None:
        self.vin = vin
        self.plug_connected_date = plug_connected_date
        self.plug_locked_date = plug_locked_date
        self.session_start_date = session_start_date
        self.start_level = start_level
        self.session_charge_type = session_charge_type
        self.session_position_latitude = session_position_latitude
        self.session_position_longitude = session_position_longitude
        self.session_odometer = session_odometer
        self.charging_type = charging_type

    def is_connected(self) -> bool:
        """Returns True if the vehicle is currently connected to a charger."""
        return self.plug_connected_date is not None and self.plug_disconnected_date is None

    def is_locked(self) -> bool:
        """Returns True if the vehicle is currently locked to a charger."""
        return self.plug_locked_date is not None and self.plug_unlocked_date is None

    def is_charging(self) -> bool:
        """Returns True if the vehicle is currently in a charging session."""
        return self.session_start_date is not None and self.session_end_date is None

    def is_closed(self) -> bool:
        """Returns True if the charging session has ended."""
        return self.session_end_date is not None or self.plug_unlocked_date is not None or self.plug_disconnected_date is not None

    def was_started(self) -> bool:
        """Returns True if the charging session was started but may also have been already ended."""
        return self.session_start_date is not None

    def was_connected(self) -> bool:
        """Returns True if the vehicle was connected to a charger during this session."""
        return self.plug_connected_date is not None

    def was_locked(self) -> bool:
        """Returns True if the vehicle was locked to a charger during this session."""
        return self.plug_locked_date is not None

    def was_ended(self) -> bool:
        """Returns True if the charging session was ended."""
        return self.session_end_date is not None

    def was_disconnected(self) -> bool:
        """Returns True if the vehicle was disconnected from a charger during this session."""
        return self.plug_disconnected_date is not None

    def was_unlocked(self) -> bool:
        """Returns True if the vehicle was unlocked from a charger during this session."""
        return self.plug_unlocked_date is not None
