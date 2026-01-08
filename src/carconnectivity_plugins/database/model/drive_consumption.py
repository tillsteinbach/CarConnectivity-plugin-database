""" This module contains the Drive consumption database model"""
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
class DriveConsumption(Base):  # pylint: disable=too-few-public-methods
    """
    SQLAlchemy model representing consumption data for a specific drive .
    This model stores consumption measurements for a drive
    tracking energy or fuel usage between two timestamps.
    Attributes:
        id (int): Primary key identifier for the drive consumption record.
        drive_id (int): Foreign key reference to the associated Drive.
        drive (Drive): Relationship to the parent Drive object.
        first_date (datetime): Start timestamp of the consumption measurement period.
        last_date (datetime): End timestamp of the consumption measurement period.
        consumption (Optional[float]): Measured consumption value for the period (e.g., kWh, liters).
    Table Constraints:
        - Unique constraint on (drive_id, first_date) to prevent duplicate entries.
    """
    __tablename__: str = 'drive_consumptions'
    __table_args__: tuple[Constraint] = (UniqueConstraint("drive_id", "first_date", name="drive_consumptions_drive_id_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    drive_id: Mapped[int] = mapped_column(ForeignKey("drives.id"))
    drive: Mapped["Drive"] = relationship("Drive")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[datetime] = mapped_column(UtcDateTime)
    consumption: Mapped[Optional[float]]

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, drive_id: Mapped[int], first_date: datetime, last_date: datetime, consumption: Optional[float]) -> None:
        self.drive_id = drive_id
        self.first_date = first_date
        self.last_date = last_date
        self.consumption = consumption
