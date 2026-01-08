""" This module contains the Vehicle battery temperature database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy_utc import UtcDateTime

from carconnectivity_plugins.database.model.base import Base

if TYPE_CHECKING:
    from sqlalchemy import Constraint


# pylint: disable=duplicate-code
class BatteryTemperature(Base):  # pylint: disable=too-few-public-methods
    """
    SQLAlchemy model representing battery temperature measurements for vehicles.
    This class stores battery temperature data associated with a vehicle, including
    the time period when the measurement was recorded.
    Attributes:
        id (int): Primary key identifier for the temperature record.
        vin (str): Vehicle Identification Number, foreign key referencing vehicles table.
        vehicle (Vehicle): Relationship to the Vehicle model.
        first_date (datetime): The timestamp when this temperature measurement was first recorded.
        last_date (datetime): The timestamp when this temperature measurement was last updated.
        battery_temperature (float, optional): The battery temperature value in degrees (unit depends on system configuration).
            Can be None if the temperature is not available.
    Args:
        vin (str): Vehicle Identification Number for the associated vehicle.
        first_date (datetime): Initial timestamp for the temperature measurement.
        last_date (datetime): Last update timestamp for the temperature measurement.
        battery_temperature (float, optional): The measured battery temperature value.
    """
    __tablename__: str = 'battery_temperatures'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "first_date", name="battery_temperatures_vin_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[datetime] = mapped_column(UtcDateTime)
    battery_temperature: Mapped[Optional[float]]

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, vin: str, first_date: datetime, last_date: datetime, battery_temperature: Optional[float]) -> None:
        self.vin = vin
        self.first_date = first_date
        self.last_date = last_date
        self.battery_temperature = battery_temperature
