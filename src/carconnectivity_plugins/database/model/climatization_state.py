""" This module contains the Vehicle climatization state database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy_utc import UtcDateTime

from carconnectivity.climatization import Climatization

from carconnectivity_plugins.database.model.base import Base

if TYPE_CHECKING:
    from sqlalchemy import Constraint


# pylint: disable=duplicate-code
class ClimatizationState(Base):  # pylint: disable=too-few-public-methods
    """
    SQLAlchemy model representing a vehicle's climatization state over a time period.

    This model stores climatization state information for vehicles, tracking the state
    between a first and last date. It maintains a foreign key relationship with
    the Vehicle model through the VIN (Vehicle Identification Number).

    Attributes:
        id (int): Primary key for the climatization state record.
        vin (str): Foreign key reference to the vehicle's VIN in the vehicles table.
        vehicle (Vehicle): Relationship to the associated Vehicle model.
        first_date (datetime): The start datetime of this climatization state period (UTC).
        last_date (datetime): The end datetime of this climatization state period (UTC).
        state (Optional[Climatization.ClimatizationState]): The climatization state during this period,
            or None if no state is available.

    Args:
        vin (str): The vehicle identification number.
        first_date (datetime): The starting datetime for this climatization state.
        last_date (datetime): The ending datetime for this climatization state.
        state (Optional[Climatization.ClimatizationState]): The climatization state value.
    """
    __tablename__: str = 'climatization_states'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "first_date", name="climatization_states_vin_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[datetime] = mapped_column(UtcDateTime)
    state: Mapped[Optional[Climatization.ClimatizationState]]

    def __init__(self, vin: str, first_date: datetime, last_date: datetime, state: Optional[Climatization.ClimatizationState]) -> None:
        self.vin = vin
        self.first_date = first_date
        self.last_date = last_date
        self.state = state
