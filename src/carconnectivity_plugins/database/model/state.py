""" This module contains the Vehicle state database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy_utc import UtcDateTime

from carconnectivity.vehicle import GenericVehicle

from carconnectivity_plugins.database.model.base import Base

if TYPE_CHECKING:
    from sqlalchemy import Constraint


# pylint: disable=duplicate-code
class State(Base):  # pylint: disable=too-few-public-methods
    """
    Represents a vehicle state record in the database.
    This class models the states table which tracks the historical state of vehicles over time periods.
    Attributes:
        id (int): Primary key for the state record.
        vin (str): Foreign key reference to the vehicle identification number in the parent table.
        vehicle (Vehicle): Relationship to the Vehicle model.
        first_date (datetime): The timestamp when this state period began (UTC).
        last_date (datetime, optional): The timestamp when this state period ended (UTC).
            None indicates the state is still active.
        state (GenericVehicle.State, optional): The vehicle's operational state during this period.
        connection_state (GenericVehicle.ConnectionState, optional): The vehicle's connection state
            during this period.
    Args:
        vin (str): The vehicle identification number.
        first_date (datetime): The start timestamp of the state period.
        last_date (datetime): The end timestamp of the state period.
        state (GenericVehicle.State, optional): The vehicle's operational state.
        connection_state (GenericVehicle.ConnectionState, optional): The vehicle's connection state.
    """
    __tablename__: str = 'states'
    __table_args__: tuple[Constraint] = (UniqueConstraint("vin", "first_date", name="states_vin_first_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicles.vin"))
    vehicle: Mapped["Vehicle"] = relationship("Vehicle")
    first_date: Mapped[datetime] = mapped_column(UtcDateTime)
    last_date: Mapped[datetime] = mapped_column(UtcDateTime)
    state: Mapped[Optional[GenericVehicle.State]]

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, vin: str, first_date: datetime, last_date: datetime, state: Optional[GenericVehicle.State]) -> None:
        self.vin = vin
        self.first_date = first_date
        self.last_date = last_date
        self.state = state
