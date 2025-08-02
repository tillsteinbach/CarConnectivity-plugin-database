"""Decorator for handling datetime objects in SQLAlchemy models.
This decorator ensures that datetime values are stored in UTC and retrieved in UTC,
while also converting naive datetime objects to the local timezone before storing.
It is designed to work with SQLAlchemy's DateTime type."""
from datetime import datetime, timezone
import sqlalchemy


# pylint: disable=too-many-ancestors
class DatetimeDecorator(sqlalchemy.types.TypeDecorator):
    """Decorator for handling datetime objects in SQLAlchemy models."""
    impl = sqlalchemy.types.DateTime
    cache_ok = True

    def process_literal_param(self, value, dialect):
        """Process literal parameter for SQLAlchemy."""
        if value is None:
            return None
        return f"'{value.isoformat()}'"

    @property
    def python_type(self):
        """Return the Python type handled by this decorator."""
        return datetime

    LOCAL_TIMEZONE = datetime.utcnow().astimezone().tzinfo

    def process_bind_param(self, value, dialect):
        if value is None:
            return value

        if value.tzinfo is None:
            value = value.astimezone(self.LOCAL_TIMEZONE)

        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return value

        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)
