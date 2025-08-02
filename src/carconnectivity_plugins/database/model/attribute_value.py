"""Module implements the database model for attribute values."""
from __future__ import annotations
from typing import Optional

from datetime import datetime, timedelta


from sqlalchemy import Integer, Boolean, Float, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship, declared_attr

from carconnectivity_plugins.database.model.base import Base
from carconnectivity_plugins.database.model.datetime_decorator import DatetimeDecorator
from carconnectivity_plugins.database.model.timedelta_decorator import TimedeltaDecorator

from carconnectivity_plugins.database.model.attribute import Attribute


# pylint: disable-next=too-few-public-methods
class AttributeValue(Base):
    """Base class for storing attribute values in the database."""
    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    attribute_id: Mapped[int] = mapped_column(Integer, ForeignKey("attribute.id"), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DatetimeDecorator(timezone=True), nullable=False)
    end_date: Mapped[Optional[datetime]] = mapped_column(DatetimeDecorator(timezone=True), nullable=True)

    @declared_attr
    # pylint: disable-next=no-self-argument
    def attribute(cls):
        """Relationship to the Attribute model."""
        return relationship("Attribute")

    def __init__(self, attribute: Attribute, start_date: datetime) -> None:
        self.attribute = attribute
        self.start_date = start_date
        self.end = None


# pylint: disable-next=too-few-public-methods
class AttributeIntegerValue(AttributeValue):
    """Model for storing integer values of attributes in the database."""
    __tablename__: str = 'attribute_integer_value'

    value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, sort_order=1)

    def __init__(self, attribute: Attribute, start_date: datetime, value: Optional[int]) -> None:
        super().__init__(attribute=attribute, start_date=start_date)
        self.value = value


# pylint: disable-next=too-few-public-methods
class AttributeBooleanValue(AttributeValue):
    """Model for storing booleans values of attributes in the database."""
    __tablename__: str = 'attribute_boolean_value'

    value: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, sort_order=1)

    def __init__(self, attribute: Attribute, start_date: datetime, value: Optional[bool]) -> None:
        super().__init__(attribute=attribute, start_date=start_date)
        self.value = value


# pylint: disable-next=too-few-public-methods
class AttributeFloatValue(AttributeValue):
    """Model for storing float values of attributes in the database."""
    __tablename__: str = 'attribute_float_value'

    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True, sort_order=1)

    def __init__(self, attribute: Attribute, start_date: datetime, value: Optional[float]) -> None:
        super().__init__(attribute=attribute, start_date=start_date)
        self.value = value


# pylint: disable-next=too-few-public-methods
class AttributeStringValue(AttributeValue):
    """Model for storing string values of attributes in the database."""
    __tablename__: str = 'attribute_string_value'

    value: Mapped[Optional[str]] = mapped_column(String, nullable=True, sort_order=1)

    def __init__(self, attribute: Attribute, start_date: datetime, value: Optional[str]) -> None:
        super().__init__(attribute=attribute, start_date=start_date)
        self.value = value


# pylint: disable-next=too-few-public-methods
class AttributeDatetimeValue(AttributeValue):
    """Model for storing datetime values of attributes in the database."""
    __tablename__: str = 'attribute_datetime_value'

    value: Mapped[Optional[datetime]] = mapped_column(DatetimeDecorator(timezone=True), nullable=True, sort_order=1)

    def __init__(self, attribute: Attribute, start_date: datetime, value: Optional[datetime]) -> None:
        super().__init__(attribute=attribute, start_date=start_date)
        self.value = value


# pylint: disable-next=too-few-public-methods
class AttributeDurationValue(AttributeValue):
    """Model for storing timedelta values of attributes in the database."""
    __tablename__: str = 'attribute_duration_value'

    value: Mapped[Optional[timedelta]] = mapped_column(TimedeltaDecorator(), nullable=True, sort_order=1)

    def __init__(self, attribute: Attribute, start_date: datetime, value: Optional[timedelta]) -> None:
        super().__init__(attribute=attribute, start_date=start_date)
        self.value = value


# pylint: disable-next=too-few-public-methods
class AttributeEnumValue(AttributeValue):
    """Model for storing enum values of attributes in the database."""
    __tablename__: str = 'attribute_enum_value'

    value: Mapped[Optional[str]] = mapped_column(String, nullable=True, sort_order=1)

    def __init__(self, attribute: Attribute, start_date: datetime, value: Optional[str]) -> None:
        super().__init__(attribute=attribute, start_date=start_date)
        self.value = value
