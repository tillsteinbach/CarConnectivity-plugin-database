"""
Agent for monitoring and persisting drive state changes to the database.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging

from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm.exc import ObjectDeletedError

from carconnectivity.observable import Observable
from carconnectivity.drive import ElectricDrive, CombustionDrive
from carconnectivity.utils.timeout_lock import TimeoutLock

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.drive_level import DriveLevel
from carconnectivity_plugins.database.model.drive_range import DriveRange
from carconnectivity_plugins.database.model.drive_consumption import DriveConsumption
from carconnectivity_plugins.database.model.drive_range_full import DriveRangeEstimatedFull

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import LevelAttribute, RangeAttribute, EnumAttribute, EnergyAttribute, VolumeAttribute, EnergyConsumptionAttribute, \
        FuelConsumptionAttribute
    from carconnectivity.drive import GenericDrive

    from carconnectivity_plugins.database.plugin import Plugin
    from carconnectivity_plugins.database.model.drive import Drive


LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.drive_state_agent")


#  pylint: disable=duplicate-code
# pylint: disable-next=too-many-instance-attributes, too-few-public-methods
class DriveStateAgent(BaseAgent):
    """
    Agent responsible for monitoring and persisting drive state changes to the database.
    This agent observes various attributes of a vehicle's drive system (electric or combustion)
    and records changes to the database, including:
    - Drive type
    - Battery/fuel levels
    - Range estimates (current and estimated full)
    - WLTP range
    - Battery/fuel capacities
    - Energy/fuel consumption
    The agent uses locks to ensure thread-safe database operations and maintains references
    to the last recorded values to avoid duplicate entries. It automatically updates existing
    records when values remain unchanged but timestamps advance.
    Attributes:
        database_plugin (Plugin): Reference to the database plugin for health status updates.
        session_factory (scoped_session[Session]): SQLAlchemy session factory for database operations.
        drive (Drive): Database model representing the drive being monitored.
        drive_lock (TimeoutLock): Lock for thread-safe drive access.
        carconnectivity_drive (GenericDrive): CarConnectivity drive object being observed.
        type_lock (TimeoutLock): Lock for drive type updates.
        range_wltp_lock (TimeoutLock): Lock for WLTP range updates.
        total_capacity_lock (TimeoutLock): Lock for total capacity updates (electric drives).
        available_capacity_lock (TimeoutLock): Lock for available capacity updates.
        fuel_available_capacity_lock (TimeoutLock): Lock for fuel capacity updates (combustion drives).
        last_electric_consumption (Optional[DriveConsumption]): Most recent electric consumption record.
        last_electric_consumption_lock (TimeoutLock): Lock for electric consumption updates.
        last_fuel_consumption (Optional[DriveConsumption]): Most recent fuel consumption record.
        last_fuel_consumption_lock (TimeoutLock): Lock for fuel consumption updates.
        last_level (Optional[DriveLevel]): Most recent level record.
        last_level_lock (TimeoutLock): Lock for level updates.
        last_range (Optional[DriveRange]): Most recent range record.
        last_range_lock (TimeoutLock): Lock for range updates.
        last_range_estimated_full (Optional[DriveRangeEstimatedFull]): Most recent estimated full range record.
        last_range_estimated_full_lock (TimeoutLock): Lock for estimated full range updates.
    Raises:
        ValueError: If drive or carconnectivity_drive is None during initialization.
    """
    # pylint: disable=too-many-statements
    def __init__(self, database_plugin: Plugin, session_factory: scoped_session[Session], drive: Drive, carconnectivity_drive: GenericDrive) -> None:
        self.database_plugin: Plugin = database_plugin
        self.session_factory: scoped_session[Session] = session_factory
        self.drive: Drive = drive
        self.drive_lock: TimeoutLock = TimeoutLock()
        self.carconnectivity_drive: GenericDrive = carconnectivity_drive
        with self.drive_lock:
            with self.session_factory() as session:
                self.drive = session.merge(self.drive)
                session.refresh(self.drive)

                if self.drive is None or self.carconnectivity_drive is None:
                    raise ValueError("Drive or its carconnectivity_drive attribute is None")

                self.carconnectivity_drive.type.add_observer(self.__on_type_change, Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
                self.type_lock: TimeoutLock = TimeoutLock()
                self.__on_type_change(self.carconnectivity_drive.type, Observable.ObserverEvent.VALUE_CHANGED)

                self.carconnectivity_drive.range_wltp.add_observer(self.__on_range_wltp_change, Observable.ObserverEvent.VALUE_CHANGED,
                                                                   on_transaction_end=True)
                self.range_wltp_lock: TimeoutLock = TimeoutLock()
                self.__on_range_wltp_change(self.carconnectivity_drive.range_wltp, Observable.ObserverEvent.VALUE_CHANGED)

                if isinstance(self.carconnectivity_drive, ElectricDrive):
                    self.carconnectivity_drive.battery.total_capacity.add_observer(self.__on_electric_total_capacity_change,
                                                                                   Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
                    self.total_capacity_lock: TimeoutLock = TimeoutLock()
                    self.__on_electric_total_capacity_change(self.carconnectivity_drive.battery.total_capacity, Observable.ObserverEvent.VALUE_CHANGED)

                    self.carconnectivity_drive.battery.available_capacity.add_observer(self.__on_electric_available_capacity_change,
                                                                                       Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
                    self.available_capacity_lock: TimeoutLock = TimeoutLock()
                    self.__on_electric_available_capacity_change(self.carconnectivity_drive.battery.available_capacity,
                                                                 Observable.ObserverEvent.VALUE_CHANGED)

                    self.last_electric_consumption: Optional[DriveConsumption] = session.query(DriveConsumption) \
                        .filter(DriveConsumption.drive_id == self.drive.id).order_by(DriveConsumption.first_date.desc()).first()
                    self.last_electric_consumption_lock: TimeoutLock = TimeoutLock()
                    self.carconnectivity_drive.consumption.add_observer(self.__on_electric_consumption_change,
                                                                        Observable.ObserverEvent.VALUE_CHANGED)
                    self.__on_electric_consumption_change(self.carconnectivity_drive.consumption, Observable.ObserverEvent.UPDATED)

                elif isinstance(self.carconnectivity_drive, CombustionDrive):
                    self.carconnectivity_drive.fuel_tank.available_capacity.add_observer(self.__on_fuel_available_capacity_change,
                                                                                         Observable.ObserverEvent.VALUE_CHANGED, on_transaction_end=True)
                    self.fuel_available_capacity_lock: TimeoutLock = TimeoutLock()
                    self.__on_fuel_available_capacity_change(self.carconnectivity_drive.fuel_tank.available_capacity, Observable.ObserverEvent.VALUE_CHANGED)

                    self.last_fuel_consumption: Optional[DriveConsumption] = session.query(DriveConsumption) \
                        .filter(DriveConsumption.drive_id == self.drive.id).order_by(DriveConsumption.first_date.desc()).first()
                    self.last_fuel_consumption_lock: TimeoutLock = TimeoutLock()
                    self.carconnectivity_drive.consumption.add_observer(self.__on_fuel_consumption_change,
                                                                        Observable.ObserverEvent.VALUE_CHANGED)
                    self.__on_fuel_consumption_change(self.carconnectivity_drive.consumption, Observable.ObserverEvent.UPDATED)

                self.last_level: Optional[DriveLevel] = session.query(DriveLevel).filter(DriveLevel.drive_id == self.drive.id) \
                    .order_by(DriveLevel.first_date.desc()).first()
                self.last_level_lock: TimeoutLock = TimeoutLock()
                self.last_range: Optional[DriveRange] = session.query(DriveRange).filter(DriveRange.drive_id == self.drive.id) \
                    .order_by(DriveRange.first_date.desc()).first()
                self.last_range_lock: TimeoutLock = TimeoutLock()
                self.last_range_estimated_full: Optional[DriveRangeEstimatedFull] = session.query(DriveRangeEstimatedFull) \
                    .filter(DriveRangeEstimatedFull.drive_id == self.drive.id).order_by(DriveRangeEstimatedFull.first_date.desc()).first()
                self.last_range_estimated_full_lock: TimeoutLock = TimeoutLock()

                if self.carconnectivity_drive is not None:
                    self.carconnectivity_drive.level.add_observer(self.__on_level_change, Observable.ObserverEvent.UPDATED)
                    if self.carconnectivity_drive.level.enabled:
                        self.__on_level_change(self.carconnectivity_drive.level, Observable.ObserverEvent.UPDATED)

                    self.carconnectivity_drive.range.add_observer(self.__on_range_change, Observable.ObserverEvent.UPDATED)
                    if self.carconnectivity_drive.range.enabled:
                        self.__on_range_change(self.carconnectivity_drive.range, Observable.ObserverEvent.UPDATED)

                    self.carconnectivity_drive.range_estimated_full.add_observer(self.__on_range_estimated_full_change, Observable.ObserverEvent.UPDATED)
                    if self.carconnectivity_drive.range_estimated_full.enabled:
                        self.__on_range_estimated_full_change(self.carconnectivity_drive.range_estimated_full, Observable.ObserverEvent.UPDATED)
            session_factory.remove()

    def __del__(self) -> None:
        self.carconnectivity_drive.type.remove_observer(self.__on_type_change)
        self.carconnectivity_drive.range_wltp.remove_observer(self.__on_range_wltp_change)

        if isinstance(self.carconnectivity_drive, ElectricDrive):
            self.carconnectivity_drive.battery.total_capacity.remove_observer(self.__on_electric_total_capacity_change)
            self.carconnectivity_drive.battery.available_capacity.remove_observer(self.__on_electric_available_capacity_change)
            self.carconnectivity_drive.consumption.remove_observer(self.__on_electric_consumption_change)

        elif isinstance(self.carconnectivity_drive, CombustionDrive):
            self.carconnectivity_drive.fuel_tank.available_capacity.remove_observer(self.__on_fuel_available_capacity_change)
            self.carconnectivity_drive.consumption.remove_observer(self.__on_fuel_consumption_change)

        self.carconnectivity_drive.level.remove_observer(self.__on_level_change)
        self.carconnectivity_drive.range.remove_observer(self.__on_range_change)
        self.carconnectivity_drive.range_estimated_full.remove_observer(self.__on_range_estimated_full_change)

    def __on_level_change(self, element: LevelAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            with self.last_level_lock, self.drive_lock:
                with self.session_factory() as session:
                    self.drive = session.merge(self.drive)
                    session.refresh(self.drive)
                    if self.last_level is not None:
                        try:
                            self.last_level = session.merge(self.last_level)
                            session.refresh(self.last_level)
                        except ObjectDeletedError:
                            self.last_level = session.query(DriveLevel).filter(DriveLevel.drive_id == self.drive.id) \
                                .order_by(DriveLevel.first_date.desc()).first()
                            if self.last_level is not None:
                                LOG.info('Last level for drive %s was deleted from database, reloaded last level', self.drive.id)
                            else:
                                LOG.info('Last level for drive %s was deleted from database, no more levels found', self.drive.id)
                    if element.last_updated is not None \
                            and (self.last_level is None or (self.last_level.level != element.value
                                                             and element.last_updated > self.last_level.last_date)):
                        new_level: DriveLevel = DriveLevel(drive_id=self.drive.id, first_date=element.last_updated, last_date=element.last_updated,
                                                           level=element.value)
                        try:
                            session.add(new_level)
                            session.commit()
                            LOG.debug('Added new level %s for drive %s to database', element.value, self.drive.id)
                            self.last_level = new_level
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding drive level for drive %s to database: %s', self.drive.id, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding level for drive %s to database: %s', self.drive.id, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_level is not None and self.last_level.level == element.value \
                            and element.last_updated is not None:
                        if self.last_level.last_date is None or element.last_updated > self.last_level.last_date:
                            try:
                                self.last_level.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated level %s for drive %s in database', element.value, self.drive.id)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating level for drive %s in database: %s', self.drive.id, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_range_change(self, element: RangeAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            converted_value: Optional[float] = element.in_locale(locale=self.database_plugin.locale)[0]
            with self.last_range_lock, self.drive_lock:
                with self.session_factory() as session:
                    self.drive = session.merge(self.drive)
                    session.refresh(self.drive)
                    if self.last_range is not None:
                        try:
                            self.last_range = session.merge(self.last_range)
                            session.refresh(self.last_range)
                        except ObjectDeletedError:
                            self.last_range = session.query(DriveRange).filter(DriveRange.drive_id == self.drive.id) \
                                .order_by(DriveRange.first_date.desc()).first()
                            if self.last_range is not None:
                                LOG.info('Last range for drive %s was deleted from database, reloaded last range', self.drive.id)
                            else:
                                LOG.info('Last range for drive %s was deleted from database, no more ranges found', self.drive.id)
                    if element.last_updated is not None \
                            and (self.last_range is None or (self.last_range.range != converted_value
                                                             and element.last_updated > self.last_range.last_date)):
                        new_range: DriveRange = DriveRange(drive_id=self.drive.id, first_date=element.last_updated, last_date=element.last_updated,
                                                           range=converted_value)
                        try:
                            session.add(new_range)
                            session.commit()
                            LOG.debug('Added new range %s for drive %s to database', converted_value, self.drive.id)
                            self.last_range = new_range
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding drive range for drive %s to database: %s', self.drive.id, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding range for drive %s to database: %s', self.drive.id, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_range is not None and self.last_range.range == converted_value \
                            and element.last_updated is not None:
                        if self.last_range.last_date is None or element.last_updated > self.last_range.last_date:
                            try:
                                self.last_range.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated range %s for drive %s in database', converted_value, self.drive.id)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating range for drive %s in database: %s', self.drive.id, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_range_estimated_full_change(self, element: RangeAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            converted_value: Optional[float] = element.in_locale(locale=self.database_plugin.locale)[0]
            with self.last_range_estimated_full_lock, self.drive_lock:
                with self.session_factory() as session:
                    self.drive = session.merge(self.drive)
                    session.refresh(self.drive)
                    if self.last_range_estimated_full is not None:
                        try:
                            self.last_range_estimated_full = session.merge(self.last_range_estimated_full)
                            session.refresh(self.last_range_estimated_full)
                        except ObjectDeletedError:
                            self.last_range_estimated_full = session.query(DriveRangeEstimatedFull).filter(DriveRangeEstimatedFull.drive_id == self.drive.id) \
                                .order_by(DriveRangeEstimatedFull.first_date.desc()).first()
                            if self.last_range_estimated_full is not None:
                                LOG.info('Last range_estimated_full for drive %s was deleted from database, reloaded last range_estimated_full', self.drive.id)
                            else:
                                LOG.info('Last range_estimated_full for drive %s was deleted from database, no more range_estimated_full found', self.drive.id)
                    if element.last_updated is not None \
                            and (self.last_range_estimated_full is None or (self.last_range_estimated_full.range_estimated_full != converted_value
                                                                            and element.last_updated > self.last_range_estimated_full.last_date)):
                        new_range: DriveRangeEstimatedFull = DriveRangeEstimatedFull(drive_id=self.drive.id, first_date=element.last_updated,
                                                                                     last_date=element.last_updated, range_estimated_full=converted_value)
                        try:
                            session.add(new_range)
                            session.commit()
                            LOG.debug('Added new range_estimated_full %s for drive %s to database', converted_value, self.drive.id)
                            self.last_range_estimated_full = new_range
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding drive range for drive %s to database: %s', self.drive.id, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding range_estimated_full for drive %s to database: %s', self.drive.id, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_range_estimated_full is not None and self.last_range_estimated_full.range_estimated_full == converted_value \
                            and element.last_updated is not None:
                        if self.last_range_estimated_full.last_date is None or element.last_updated > self.last_range_estimated_full.last_date:
                            try:
                                self.last_range_estimated_full.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated range_estimated_full %s for drive %s in database', converted_value, self.drive.id)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating range_estimated_full for drive %s in database: %s', self.drive.id, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_type_change(self, element: EnumAttribute[GenericDrive.Type], flags: Observable.ObserverEvent) -> None:
        del flags
        with self.type_lock, self.drive_lock:
            with self.session_factory() as session:
                self.drive = session.merge(self.drive)
                session.refresh(self.drive)
                if element.enabled and element.value is not None and self.drive.type != element.value:
                    try:
                        self.drive.type = element.value
                        session.commit()
                    except DatabaseError as err:
                        session.rollback()
                        LOG.error('DatabaseError while updating type for drive %s to database: %s', self.drive.id, err)
                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
            self.session_factory.remove()

    def __on_electric_total_capacity_change(self, element: EnergyAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        with self.total_capacity_lock, self.drive_lock:
            with self.session_factory() as session:
                self.drive = session.merge(self.drive)
                session.refresh(self.drive)
                if element.enabled and element.value is not None and self.drive.capacity_total != element.value:
                    try:
                        self.drive.capacity_total = element.value
                        session.commit()
                    except DatabaseError as err:
                        session.rollback()
                        LOG.error('DatabaseError while updating total capacity for drive %s to database: %s', self.drive.id, err)
                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
            self.session_factory.remove()

    def __on_electric_available_capacity_change(self, element: EnergyAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        with self.available_capacity_lock, self.drive_lock:
            with self.session_factory() as session:
                self.drive = session.merge(self.drive)
                session.refresh(self.drive)
                if element.enabled and element.value is not None and self.drive.capacity != element.value:
                    try:
                        self.drive.capacity = element.value
                        session.commit()
                    except DatabaseError as err:
                        session.rollback()
                        LOG.error('DatabaseError while updating available capacity for drive %s to database: %s', self.drive.id, err)
                        self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
            self.session_factory.remove()

    def __on_range_wltp_change(self, element: RangeAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            converted_value: Optional[float] = element.in_locale(locale=self.database_plugin.locale)[0]
            with self.range_wltp_lock, self.drive_lock:
                with self.session_factory() as session:
                    self.drive = session.merge(self.drive)
                    session.refresh(self.drive)
                    if converted_value is not None and self.drive.wltp_range != converted_value:
                        try:
                            self.drive.wltp_range = converted_value
                            session.commit()
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while updating WLTP range for drive %s to database: %s', self.drive.id, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_fuel_available_capacity_change(self, element: VolumeAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            converted_value: Optional[float] = element.in_locale(locale=self.database_plugin.locale)[0]
            with self.fuel_available_capacity_lock, self.drive_lock:
                with self.session_factory() as session:
                    self.drive = session.merge(self.drive)
                    session.refresh(self.drive)
                    if converted_value is not None and self.drive.capacity != converted_value:
                        try:
                            self.drive.capacity = converted_value
                            session.commit()
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while updating available capacity for drive %s to database: %s', self.drive.id, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_electric_consumption_change(self, element: EnergyConsumptionAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            converted_value: Optional[float] = element.in_locale(locale=self.database_plugin.locale)[0]
            with self.last_electric_consumption_lock, self.drive_lock:
                with self.session_factory() as session:
                    self.drive = session.merge(self.drive)
                    session.refresh(self.drive)
                    if self.last_electric_consumption is not None:
                        try:
                            self.last_electric_consumption = session.merge(self.last_electric_consumption)
                            session.refresh(self.last_electric_consumption)
                        except ObjectDeletedError:
                            self.last_electric_consumption = session.query(DriveConsumption).filter(DriveConsumption.drive_id == self.drive.id) \
                                .order_by(DriveConsumption.first_date.desc()).first()
                            if self.last_electric_consumption is not None:
                                LOG.info('Last electric consumption for drive %s was deleted from database, reloaded last electric consumption', self.drive.id)
                            else:
                                LOG.info('Last electric consumption for drive %s was deleted from database, no more electric consumptions found', self.drive.id)
                    if element.last_updated is not None \
                            and (self.last_electric_consumption is None or (self.last_electric_consumption.consumption != converted_value
                                                                            and element.last_updated > self.last_electric_consumption.last_date)):
                        new_consumption: DriveConsumption = DriveConsumption(drive_id=self.drive.id, first_date=element.last_updated,
                                                                             last_date=element.last_updated, consumption=converted_value)
                        try:
                            session.add(new_consumption)
                            session.commit()
                            LOG.debug('Added new consumption %s for drive %s to database', converted_value, self.drive.id)
                            self.last_electric_consumption = new_consumption
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding drive consumption for drive %s to database: %s', self.drive.id, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding consumption for drive %s to database: %s', self.drive.id, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_electric_consumption is not None and self.last_electric_consumption.consumption == converted_value \
                            and element.last_updated is not None:
                        if self.last_electric_consumption.last_date is None or element.last_updated > self.last_electric_consumption.last_date:
                            try:
                                self.last_electric_consumption.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated consumption %s for drive %s in database', converted_value, self.drive.id)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating consumption for drive %s in database: %s', self.drive.id, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()

    def __on_fuel_consumption_change(self, element: FuelConsumptionAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            with self.last_fuel_consumption_lock, self.drive_lock:
                with self.session_factory() as session:
                    self.drive = session.merge(self.drive)
                    session.refresh(self.drive)
                    if self.last_fuel_consumption is not None:
                        try:
                            self.last_fuel_consumption = session.merge(self.last_fuel_consumption)
                            session.refresh(self.last_fuel_consumption)
                        except ObjectDeletedError:
                            self.last_fuel_consumption = session.query(DriveConsumption).filter(DriveConsumption.drive_id == self.drive.id) \
                                .order_by(DriveConsumption.first_date.desc()).first()
                            if self.last_fuel_consumption is not None:
                                LOG.info('Last fuel consumption for drive %s was deleted from database, reloaded last fuel consumption', self.drive.id)
                            else:
                                LOG.info('Last fuel consumption for drive %s was deleted from database, no more fuel consumptions found', self.drive.id)
                    if element.last_updated is not None \
                            and (self.last_fuel_consumption is None or (self.last_fuel_consumption.consumption != element.value
                                                                        and element.last_updated > self.last_fuel_consumption.last_date)):
                        new_consumption: DriveConsumption = DriveConsumption(drive_id=self.drive.id, first_date=element.last_updated,
                                                                             last_date=element.last_updated, consumption=element.value)
                        try:
                            session.add(new_consumption)
                            session.commit()
                            LOG.debug('Added new consumption %s for drive %s to database', element.value, self.drive.id)
                            self.last_fuel_consumption = new_consumption
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding drive consumption for drive %s to database: %s', self.drive.id, err)
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding consumption for drive %s to database: %s', self.drive.id, err)
                            self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                    elif self.last_fuel_consumption is not None and self.last_fuel_consumption.consumption == element.value \
                            and element.last_updated is not None:
                        if self.last_fuel_consumption.last_date is None or element.last_updated > self.last_fuel_consumption.last_date:
                            try:
                                self.last_fuel_consumption.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated consumption %s for drive %s in database', element.value, self.drive.id)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating consumption for drive %s in database: %s', self.drive.id, err)
                                self.database_plugin.healthy._set_value(value=False)  # pylint: disable=protected-access
                self.session_factory.remove()
