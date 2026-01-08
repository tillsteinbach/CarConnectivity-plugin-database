""" This module contains the Vehicle outside temperature database model"""
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
class OutsideTemperature(Base):  # pylint: disable=too-few-public-methods
    """
    SQLAlchemy model representing outside temperature measurements for vehicles.
    This class stores outside temperature data associated with a vehicle, including
    the time period when the measurement was recorded.
    Attributes:
        id (int): Primary key identifier for the temperature record.
        vin (str): Vehicle Identification Number, foreign key referencing vehicles table.
        vehicle (Vehicle): Relationship to the Vehicle model.
        first_date (datetime): The timestamp when this temperature measurement was first recorded.
        last_date (datetime): The timestamp when this temperature measurement was last updated.
        outside_temperature (float, optional): The outside temperature value in degrees (unit depends on system configuration).
            Can be None if the temperature is not available.
    Args:
        vin (str): Vehicle Identification Number for the associated vehicle.
        first_date (datetime): Initial timestamp for the temperature measurement.
        last_date (datetime): Last update timestamp for the temperature measurement.
        outside_temperature (float, optional): The measured outside temperature value.
    """
    __tablename__: str = 'outside_temperatures'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "first_date", name="outside_temperatures_vin_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[datetime] = mapped_column(UtcDateTime)
    outside_temperature: Mapped[Optional[float]]

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, vin: str, first_date: datetime, last_date: datetime, outside_temperature: Optional[float]) -> None:
        self.vin = vin
        self.first_date = first_date
        self.last_date = last_date
        self.outside_temperature = outside_temperature
