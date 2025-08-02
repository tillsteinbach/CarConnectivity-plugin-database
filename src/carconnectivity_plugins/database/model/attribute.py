"""Module implements the database model for attributes"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Mapped, mapped_column

from carconnectivity_plugins.database.model.base import Base

if TYPE_CHECKING:
    from carconnectivity.attributes import GenericAttribute


# pylint: disable-next=too-few-public-methods
class Attribute(Base):
    """Model for storing attributes in the database."""
    __tablename__: str = 'attribute'
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[Optional[str]] = mapped_column(unique=True, nullable=True)

    def __init__(self, path: str) -> None:
        self.path = path

    @classmethod
    def from_generic_attribute(cls, attribute: GenericAttribute) -> Attribute:
        """Create an Attribute instance from a GenericAttribute.
        Args:
            attribute (GenericAttribute): The generic attribute to convert.
        Returns:
            Attribute: An instance of the Attribute class."""
        return cls(path=attribute.get_absolute_path())
