"""This module contains the vehicle odometer database model."""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy_utc import UtcDateTime

from carconnectivity_plugins.database.model.base import Base

if TYPE_CHECKING:
    from sqlalchemy import Constraint


class Odometer(Base):  # pylint: disable=too-few-public-methods
    """Represents one odometer measurement received from a vehicle."""

    __tablename__: str = 'odometer'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "first_date", name="odometer_vin_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    odometer: Mapped[Optional[float]]

    def __init__(self, vin: str, first_date: datetime, last_date: Optional[datetime] = None,
                 odometer: Optional[float] = None) -> None:
        self.vin = vin
        self.first_date = first_date
        self.last_date = last_date
        self.odometer = odometer