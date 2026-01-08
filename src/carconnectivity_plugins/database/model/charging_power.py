""" This module contains the Vehicle charging power database model"""
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
class ChargingPower(Base):  # pylint: disable=too-few-public-methods
    """
    SQLAlchemy model representing a vehicle's charging power information over a time period.
    This table stores the power of charging (e.g., in kW) used by a vehicle within
    a specific date range.
    Attributes:
        id (int): Primary key identifier for the charging type record.
        vin (str): Foreign key reference to the vehicle's VIN in the vehicles table.
        vehicle (Vehicle): Relationship to the Vehicle model.
        first_date (datetime): The start date/time of this charging power period.
        last_date (datetime): The end date/time of this charging power period.
        power (float, optional): The charging power value, or None if not available.
    Args:
        vin (str): The vehicle identification number.
        first_date (datetime): The start date/time for this charging power record.
        last_date (datetime): The end date/time for this charging power record.
        power (Optional[float]): The charging power value.
    """

    __tablename__: str = 'charging_powers'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "first_date", name="charging_powers_vin_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[datetime] = mapped_column(UtcDateTime)
    power: Mapped[Optional[float]]

    def __init__(self, vin: str, first_date: datetime, last_date: datetime, power: Optional[float]) -> None:
        self.vin = vin
        self.first_date = first_date
        self.last_date = last_date
        self.power = power
