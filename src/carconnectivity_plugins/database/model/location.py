""" This module contains the location database model"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Mapped, mapped_column

from carconnectivity_plugins.database.model.base import Base

if TYPE_CHECKING:
    from carconnectivity.location import Location as CarConnectivityLocation


class Location(Base):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """
    SQLAlchemy model representing a geographical location.
    This class maps to the 'locations' table in the database and stores
    geographical and address information for a specific location.
    Attributes:
        uid (str): Unique identifier for the location (primary key).
        source (Optional[str]): The data source providing the location information.
        latitude (Optional[float]): Latitude coordinate of the location.
        longitude (Optional[float]): Longitude coordinate of the location.
        display_name (Optional[str]): Human-readable display name of the location.
        name (Optional[str]): Name of the location.
        amenity (Optional[str]): Type of amenity at the location.
        house_number (Optional[str]): House or building number.
        road (Optional[str]): Street or road name.
        neighbourhood (Optional[str]): Neighbourhood or area name.
        city (Optional[str]): City name.
        postcode (Optional[str]): Postal code.
        county (Optional[str]): County name.
        country (Optional[str]): Country name.
        state (Optional[str]): State or province name.
        state_district (Optional[str]): State district name.
        raw (Optional[str]): Raw location data as received from the source.
    Methods:
        from_carconnectivity_location: Class method to create a Location instance
            from a CarConnectivity Location object.
    """

    __tablename__: str = 'locations'

    uid: Mapped[str] = mapped_column(primary_key=True)
    source: Mapped[Optional[str]]
    latitude: Mapped[Optional[float]]
    longitude: Mapped[Optional[float]]
    display_name: Mapped[Optional[str]]
    name: Mapped[Optional[str]]
    amenity: Mapped[Optional[str]]
    house_number: Mapped[Optional[str]]
    road: Mapped[Optional[str]]
    neighbourhood: Mapped[Optional[str]]
    city: Mapped[Optional[str]]
    postcode: Mapped[Optional[str]]
    county: Mapped[Optional[str]]
    country: Mapped[Optional[str]]
    state: Mapped[Optional[str]]
    state_district: Mapped[Optional[str]]
    raw: Mapped[Optional[str]]

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def __init__(self, uid: str) -> None:
        self.uid = uid

    @classmethod
    def from_carconnectivity_location(cls, location: CarConnectivityLocation) -> Location:
        """Create a Location instance from a carconnectivity Location object."""
        loc = cls(uid=location.uid.value)
        loc.source = location.source.value
        loc.latitude = location.latitude.value
        loc.longitude = location.longitude.value
        loc.display_name = location.display_name.value
        loc.name = location.name.value
        loc.amenity = location.amenity.value
        loc.house_number = location.house_number.value
        loc.road = location.road.value
        loc.neighbourhood = location.neighbourhood.value
        loc.city = location.city.value
        loc.postcode = location.postcode.value
        loc.county = location.county.value
        loc.country = location.country.value
        loc.state = location.state.value
        loc.state_district = location.state_district.value
        loc.raw = location.raw.value
        return loc
