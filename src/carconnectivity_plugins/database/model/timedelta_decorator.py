"""Decorator for handling timedelta objects in SQLAlchemy models.
This decorator ensures that duration values are stored in microsecond format"""
from datetime import timedelta
import sqlalchemy


# pylint: disable=too-many-ancestors
class TimedeltaDecorator(sqlalchemy.types.TypeDecorator):
    """Decorator for handling datetime objects in SQLAlchemy models."""
    impl = sqlalchemy.types.Float
    cache_ok = True

    @property
    def python_type(self):
        """Return the Python type handled by this decorator."""
        return timedelta

    def process_bind_param(self, value, dialect):
        if value is None:
            return value

        return value.total_seconds()

    def process_result_value(self, value, dialect):
        if value is None:
            return value

        return timedelta(seconds=value)

    def process_literal_param(self, value, dialect):
        if value is None:
            return value
        return value.total_seconds()
