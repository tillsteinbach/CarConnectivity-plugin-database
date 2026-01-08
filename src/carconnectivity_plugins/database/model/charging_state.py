""" This module contains the Vehicle charging state database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy_utc import UtcDateTime

from carconnectivity.charging import Charging

from carconnectivity_plugins.database.model.base import Base

if TYPE_CHECKING:
    from sqlalchemy import Constraint


# pylint: disable=duplicate-code
class ChargingState(Base):  # pylint: disable=too-few-public-methods
    """
    SQLAlchemy model representing a vehicle's charging state over a time period.

    This model stores charging state information for vehicles, tracking the state
    between a first and last date. It maintains a foreign key relationship with
    the Vehicle model through the VIN (Vehicle Identification Number).

    Attributes:
        id (int): Primary key for the charging state record.
        vin (str): Foreign key reference to the vehicle's VIN in the vehicles table.
        vehicle (Vehicle): Relationship to the associated Vehicle model.
        first_date (datetime): The start datetime of this charging state period (UTC).
        last_date (datetime): The end datetime of this charging state period (UTC).
        state (Optional[Charging.ChargingState]): The charging state during this period,
            or None if no state is available.

    Args:
        vin (str): The vehicle identification number.
        first_date (datetime): The starting datetime for this charging state.
        last_date (datetime): The ending datetime for this charging state.
        state (Optional[Charging.ChargingState]): The charging state value.
    """
    __tablename__: str = 'charging_states'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "first_date", name="charging_states_vin_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[datetime] = mapped_column(UtcDateTime)
    state: Mapped[Optional[Charging.ChargingState]]

    def __init__(self, vin: str, first_date: datetime, last_date: datetime, state: Optional[Charging.ChargingState]) -> None:
        self.vin = vin
        self.first_date = first_date
        self.last_date = last_date
        self.state = state
