"""Decorator for handling datetime objects in SQLAlchemy models.
This decorator ensures that datetime values are stored in UTC and retrieved in UTC,
while also converting naive datetime objects to the local timezone before storing.
It is designed to work with SQLAlchemy's DateTime type."""
from __future__ import annotations
from typing import TYPE_CHECKING

from datetime import datetime, timezone
import sqlalchemy

if TYPE_CHECKING:
    from typing import Optional
    from datetime import tzinfo
    from sqlalchemy.engine.interfaces import Dialect


# pylint: disable=too-many-ancestors
class DatetimeDecorator(sqlalchemy.types.TypeDecorator):
    """Decorator for handling datetime objects in SQLAlchemy models."""
    impl = sqlalchemy.types.DateTime
    cache_ok = True

    def process_literal_param(self, value: Optional[datetime], dialect: Dialect) -> str:
        """Process literal parameter for SQLAlchemy."""
        del dialect  # Unused parameter
        if value is None:
            raise ValueError("Datetime value cannot be None as a literal parameter")
        return f"'{value.isoformat()}'"

    @property
    def python_type(self) -> type[datetime]:
        """Return the Python type handled by this decorator."""
        return datetime

    LOCAL_TIMEZONE: Optional[tzinfo] = datetime.now(timezone.utc).astimezone().tzinfo

    def process_bind_param(self, value: Optional[datetime], dialect: Dialect) -> None | datetime:
        del dialect  # Unused parameter
        if value is None:
            return value
        if not isinstance(value, datetime):
            return value

        if value.tzinfo is None:
            value = value.astimezone(self.LOCAL_TIMEZONE)

        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Optional[datetime], dialect: Dialect) -> Optional[datetime]:
        del dialect  # Unused parameter
        if value is None:
            return value
        if not isinstance(value, datetime):
            return value

        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)
