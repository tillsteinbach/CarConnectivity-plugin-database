from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Mapped, mapped_column

from carconnectivity.vehicle import GenericVehicle
from carconnectivity.observable import Observable

from carconnectivity_plugins.database.model.base import Base


class Vehicle(Base):
    __tablename__ = 'vehicles'
    __allow_unmapped__ = True

    vin: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[Optional[str]]
    manufacturer: Mapped[Optional[str]]
    model: Mapped[Optional[str]]
    model_year: Mapped[Optional[int]]
    type: Mapped[Optional[GenericVehicle.Type]]
    license_plate: Mapped[Optional[str]]

    carconnectivity_vehicle: Optional[GenericVehicle] = None

    def __init__(self, vin) -> None:
        self.vin = vin

    def connect(self, carconnectivity_vehicle: GenericVehicle) -> None:
        self.carconnectivity_vehicle = carconnectivity_vehicle
        self.carconnectivity_vehicle.name.add_observer(self.__on_name_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
        if self.carconnectivity_vehicle.name.enabled and self.name != self.carconnectivity_vehicle.name.value:
            self.name = self.carconnectivity_vehicle.name.value
        self.carconnectivity_vehicle.manufacturer.add_observer(self.__on_manufacturer_change, Observable.ObserverEvent.VALUE_CHANGED,
                                                               on_transaction_end=True)
        if self.carconnectivity_vehicle.manufacturer.enabled and self.manufacturer != self.carconnectivity_vehicle.manufacturer.value:
            self.manufacturer = self.carconnectivity_vehicle.manufacturer.value
        self.carconnectivity_vehicle.model.add_observer(self.__on_model_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
        if self.carconnectivity_vehicle.model.enabled and self.model != self.carconnectivity_vehicle.model.value:
            self.model = self.carconnectivity_vehicle.model.value
        self.carconnectivity_vehicle.model_year.add_observer(self.__on_model_year_change, Observable.ObserverEvent.VALUE_CHANGED,
                                                             on_transaction_end=True)
        if self.carconnectivity_vehicle.model_year.enabled and self.model_year != self.carconnectivity_vehicle.model_year.value:
            self.model_year = self.carconnectivity_vehicle.model_year.value
        self.carconnectivity_vehicle.type.add_observer(self.__on_type_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
        if self.carconnectivity_vehicle.type.enabled and self.carconnectivity_vehicle.type.value is not None and self.type != self.carconnectivity_vehicle.type.value:
            self.type = self.carconnectivity_vehicle.type.value
        self.carconnectivity_vehicle.license_plate.add_observer(self.__on_license_plate_change, Observable.ObserverEvent.VALUE_CHANGED,
                                                                on_transaction_end=True)
        if self.carconnectivity_vehicle.license_plate.enabled and self.license_plate != self.carconnectivity_vehicle.license_plate.value:
            self.license_plate = self.carconnectivity_vehicle.license_plate.value

    def __on_name_change(self, element, flags) -> None:
        del flags
        if self.name != element.value:
            self.name = element.value

    def __on_manufacturer_change(self, element, flags) -> None:
        del flags
        if self.manufacturer != element.value:
            self.manufacturer = element.value

    def __on_model_change(self, element, flags) -> None:
        del flags
        if self.model != element.value:
            self.model = element.value

    def __on_model_year_change(self, element, flags) -> None:
        del flags
        if self.model_year != element.value:
            self.model_year = element.value

    def __on_type_change(self, element, flags) -> None:
        del flags
        if element.value is not None and self.type != element.value:
            self.type = element.value

    def __on_license_plate_change(self, element, flags) -> None:
        del flags
        if self.license_plate != element.value:
            self.license_plate = element.value
