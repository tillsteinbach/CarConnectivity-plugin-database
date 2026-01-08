""" This module contains the charging stations database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Mapped, mapped_column

from carconnectivity_plugins.database.model.base import Base

if TYPE_CHECKING:
    from carconnectivity.charging_station import ChargingStation as CarConnectivityChargingStation


class ChargingStation(Base):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """
    SQLAlchemy model representing a charging station in the database.
    This class maps charging station data to the 'charging_stations' database table,
    storing information about electric vehicle charging locations and their properties.
    Attributes:
        uid (str): Unique identifier for the charging station (primary key).
        source (Optional[str]): Source or provider of the charging station data.
        name (Optional[str]): Name or title of the charging station.
        latitude (Optional[float]): Geographic latitude coordinate of the station.
        longitude (Optional[float]): Geographic longitude coordinate of the station.
        address (Optional[str]): Physical address of the charging station.
        max_power (Optional[float]): Maximum power output in kilowatts (kW).
        num_spots (Optional[int]): Number of available charging spots.
        operator_id (Optional[str]): Identifier of the charging station operator.
        operator_name (Optional[str]): Name of the charging station operator.
        raw (Optional[str]): Raw data from the original source in string format.
    Methods:
        from_carconnectivity_charging_station: Class method to create an instance from a
            CarConnectivity ChargingStation object.
    """
    __tablename__: str = 'charging_stations'

    uid: Mapped[str] = mapped_column(primary_key=True)
    source: Mapped[Optional[str]]
    name: Mapped[Optional[str]]
    latitude: Mapped[Optional[float]]
    longitude: Mapped[Optional[float]]
    address: Mapped[Optional[str]]
    max_power: Mapped[Optional[float]]
    num_spots: Mapped[Optional[int]]
    operator_id: Mapped[Optional[str]]
    operator_name: Mapped[Optional[str]]
    raw: Mapped[Optional[str]]

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, uid: str) -> None:
        self.uid = uid

    @classmethod
    def from_carconnectivity_charging_station(cls, charging_station: CarConnectivityChargingStation) -> ChargingStation:
        """Create a ChargingStation instance from a carconnectivity ChargingStation object."""
        if charging_station.uid.value is None:
            raise ValueError("ChargingStation uid cannot be None")
        cs: ChargingStation = ChargingStation(uid=charging_station.uid.value)
        cs.source = charging_station.source.value
        cs.name = charging_station.name.value
        cs.latitude = charging_station.latitude.value
        cs.longitude = charging_station.longitude.value
        cs.address = charging_station.address.value
        cs.max_power = charging_station.max_power.value
        cs.num_spots = charging_station.num_spots.value
        cs.operator_id = charging_station.operator_id.value
        cs.operator_name = charging_station.operator_name.value
        cs.raw = charging_station.raw.value
        return cs
