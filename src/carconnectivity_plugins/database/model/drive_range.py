""" This module contains the Drive range database model"""
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
class DriveRange(Base):  # pylint: disable=too-few-public-methods
    """
    Represents a drive range record in the database.
    This class models the range information for a specific drive, tracking the first and last
    date of the range measurement along with the range value itself.
    Attributes:
        id (int): Primary key identifier for the drive range record.
        drive_id (int): Foreign key reference to the associated drive record.
        drive (Drive): Relationship to the Drive model.
        first_date (datetime): The timestamp when the range measurement started.
        last_date (datetime): The timestamp when the range measurement ended.
        range (Optional[float]): The measured range value in appropriate units (e.g., kilometers or miles).
            Can be None if the range data is not available.
    Args:
        drive_id (int): The identifier of the associated drive.
        first_date (datetime): The start timestamp of the range measurement.
        last_date (datetime): The end timestamp of the range measurement.
        range (Optional[float]): The range value, or None if unavailable.
    """

    __tablename__: str = 'drive_ranges'
    __table_args__: tuple[Constraint] = (UniqueConstraint("drive_id", "first_date", name="drive_ranges_drive_id_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    drive_id: Mapped[int] = mapped_column(ForeignKey("drives.id"))
    drive: Mapped["Drive"] = relationship("Drive")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[datetime] = mapped_column(UtcDateTime)
    range: Mapped[Optional[float]]

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments, redefined-builtin
    def __init__(self, drive_id: Mapped[int], first_date: datetime, last_date: datetime, range: Optional[float]) -> None:
        self.drive_id = drive_id
        self.first_date = first_date
        self.last_date = last_date
        self.range = range
