"""Decorator for handling timedelta objects in SQLAlchemy models.
This decorator ensures that duration values are stored in microsecond format"""
from __future__ import annotations
from typing import TYPE_CHECKING

from datetime import timedelta
import sqlalchemy

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.engine.interfaces import Dialect


# pylint: disable=too-many-ancestors
class TimedeltaDecorator(sqlalchemy.types.TypeDecorator):
    """Decorator for handling timedelta objects in SQLAlchemy models."""
    impl = sqlalchemy.types.Float
    cache_ok = True

    @property
    def python_type(self) -> type[timedelta]:
        """Return the Python type handled by this decorator."""
        return timedelta

    def process_bind_param(self, value: Optional[timedelta], dialect: Dialect) -> Optional[float]:
        del dialect  # Unused parameter
        if value is None:
            return value

        return value.total_seconds()

    def process_result_value(self, value: Optional[float], dialect: Dialect) -> Optional[timedelta]:
        del dialect  # Unused parameter
        if value is None:
            return value

        return timedelta(seconds=value)

    def process_literal_param(self, value: Optional[timedelta], dialect: Dialect) -> str:
        del dialect  # Unused parameter
        if value is None:
            raise ValueError("Timedelta value cannot be None as a literal parameter")
        return str(value.total_seconds())
