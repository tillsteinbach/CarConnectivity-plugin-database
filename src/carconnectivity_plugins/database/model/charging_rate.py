""" This module contains the Vehicle charging rates database model"""
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
class ChargingRate(Base):  # pylint: disable=too-few-public-methods
    """
    SQLAlchemy model representing a vehicle's charging type information over a time period.
    This table stores the type of charging (e.g., AC, DC) used by a vehicle within
    a specific date range.
    Attributes:
        id (int): Primary key identifier for the charging type record.
        vin (str): Foreign key reference to the vehicle's VIN in the vehicles table.
        vehicle (Vehicle): Relationship to the Vehicle model.
        first_date (datetime): The start date/time of this charging type period.
        last_date (datetime): The end date/time of this charging type period.
        rate (float, optional): The charging rate value, or None if not available.
    Args:
        vin (str): The vehicle identification number.
        first_date (datetime): The start date/time for this charging type record.
        last_date (datetime): The end date/time for this charging type record.
        rate (Optional[float]): The charging rate value.
    """

    __tablename__: str = 'charging_rates'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "first_date", name="charging_rates_vin_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[datetime] = mapped_column(UtcDateTime)
    rate: Mapped[Optional[float]]

    def __init__(self, vin: str, first_date: datetime, last_date: datetime, rate: Optional[float]) -> None:
        self.vin = vin
        self.first_date = first_date
        self.last_date = last_date
        self.rate = rate
