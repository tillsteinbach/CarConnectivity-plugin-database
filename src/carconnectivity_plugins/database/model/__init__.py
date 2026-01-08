""" This module contains the database model for car connectivity plugins."""

from .battery_temperature import BatteryTemperature  # noqa: F401
from .charging_state import ChargingState  # noqa: F401
from .charging_rate import ChargingRate  # noqa: F401
from .charging_power import ChargingPower  # noqa: F401
from .charging_session import ChargingSession  # noqa: F401
from .charging_station import ChargingStation  # noqa: F401
from .climatization_state import ClimatizationState  # noqa: F401
from .connection_state import ConnectionState  # noqa: F401
from .drive import Drive  # noqa: F401
from .drive_level import DriveLevel  # noqa: F401
from .drive_range import DriveRange  # noqa: F401
from .drive_range_full import DriveRangeEstimatedFull  # noqa: F401
from .location import Location  # noqa: F401
from .outside_temperature import OutsideTemperature  # noqa: F401
from .refuel_session import RefuelSession  # noqa: F401
from .state import State  # noqa: F401
from .tag import Tag  # noqa: F401
from .trip import Trip  # noqa: F401
from .vehicle import Vehicle  # noqa: F401
