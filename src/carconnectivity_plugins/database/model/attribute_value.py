from __future__ import annotations
from typing import TYPE_CHECKING

from sqlalchemy import Column, Integer, ForeignKey

from carconnectivity_plugins.database.model.base import Base
from carconnectivity_plugins.database.model.datetime_decorator import DatetimeDecorator

if TYPE_CHECKING:
    from datetime import datetime
    from carconnectivity_plugins.database.model.attribute import Attribute


class AttributeIntegerValue(Base):
    __tablename__ = 'attribute_integer_value'
    id: Column[int] = Column(Integer, primary_key=True)
    attribute = Column(Integer, ForeignKey('attribute.id'), nullable=False)
    start = Column(DatetimeDecorator(timezone=True), nullable=False)
    end = Column(DatetimeDecorator(timezone=True), nullable=True)
    value = Column(Integer, nullable=True)

    def __init__(self, attribute: Attribute, start: datetime, value: int) -> None:
        self.attribute: Attribute = attribute
        self.start: datetime = start
        self.value: int = value
