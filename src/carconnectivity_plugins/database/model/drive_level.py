""" This module contains the Drive level database model"""
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
class DriveLevel(Base):  # pylint: disable=too-few-public-methods
    """
    SQLAlchemy model representing energy levels for a drive.
    This class maps to the 'drive_levels' database table and tracks the level.
    Attributes:
        id (int): Primary key identifier for the drive level record.
        drive_id (str): Foreign key referencing the associated drive
        drive (Drive): Relationship to the Drive model.
        first_date (datetime): Timestamp when this level measurement started.
        last_date (datetime): Timestamp when this level measurement ended.
        level (Optional[float]): Battery level value (percentage or absolute value).
    Args:
        drive_id (str): The identifier of the associated drive.
        first_date (datetime): Start timestamp for this level measurement.
        last_date (datetime): End timestamp for this level measurement.
        level (Optional[float]): The battery level value, can be None if unavailable.
    """
    __tablename__: str = 'drive_levels'
    __table_args__: tuple[Constraint] = (UniqueConstraint("drive_id", "first_date", name="drive_levels_drive_id_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    drive_id: Mapped[int] = mapped_column(ForeignKey("drives.id"))
    drive: Mapped["Drive"] = relationship("Drive")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[datetime] = mapped_column(UtcDateTime)
    level: Mapped[Optional[float]]

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, drive_id: Mapped[int], first_date: datetime, last_date: datetime, level: Optional[float]) -> None:
        self.drive_id = drive_id
        self.first_date = first_date
        self.last_date = last_date
        self.level = level
