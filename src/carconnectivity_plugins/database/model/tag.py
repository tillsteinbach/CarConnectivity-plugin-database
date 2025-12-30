""" This module contains the Tag database model"""
from __future__ import annotations
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from carconnectivity_plugins.database.model.base import Base


class Tag(Base):  # pylint: disable=too-few-public-methods
    """
    Represents a tag in the database.
    A tag is a label that can be associated with various entities in the system.
    Each tag has a unique name and an optional description.
    Attributes:
        name (str): The unique name of the tag. Acts as the primary key.
        description (str, optional): An optional description providing more context about the tag.
    Args:
        name (str): The unique name for the tag.
        description (str, optional): An optional description for the tag. Defaults to None.
    """

    __tablename__: str = 'tags'

    name: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[Optional[str]]

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, name: str, description: Optional[str] = None) -> None:
        self.name = name
        self.description = description
