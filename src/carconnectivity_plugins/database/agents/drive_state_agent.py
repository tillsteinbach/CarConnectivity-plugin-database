from __future__ import annotations
from typing import TYPE_CHECKING

import threading

import logging

from sqlalchemy.exc import DatabaseError

from carconnectivity.observable import Observable

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.drive_level import DriveLevel
from carconnectivity_plugins.database.model.drive_range import DriveRange
from carconnectivity_plugins.database.model.drive_range_full import DriveRangeEstimatedFull

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm import scoped_session
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import LevelAttribute, RangeAttribute

    from carconnectivity_plugins.database.model.drive import Drive


LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.drive_state_agent")


class DriveStateAgent(BaseAgent):
    def __init__(self, session_factory: scoped_session[Session], drive: Drive) -> None:
        if drive is None or drive.carconnectivity_drive is None:
            raise ValueError("Drive or its carconnectivity_drive attribute is None")
        self.session_factory: scoped_session[Session] = session_factory
        self.drive: Drive = drive

        with self.session_factory() as session:
            self.last_level: Optional[DriveLevel] = session.query(DriveLevel).filter(DriveLevel.drive_id == drive.id) \
                .order_by(DriveLevel.first_date.desc()).first()
            self.last_level_lock: threading.RLock = threading.RLock()
            self.last_range: Optional[DriveRange] = session.query(DriveRange).filter(DriveRange.drive_id == drive.id) \
                .order_by(DriveRange.first_date.desc()).first()
            self.last_range_lock: threading.RLock = threading.RLock()
            self.last_range_estimated_full: Optional[DriveRangeEstimatedFull] = session.query(DriveRangeEstimatedFull) \
                .filter(DriveRangeEstimatedFull.drive_id == drive.id).order_by(DriveRangeEstimatedFull.first_date.desc()).first()
            self.last_range_estimated_full_lock: threading.RLock = threading.RLock()

            drive.carconnectivity_drive.level.add_observer(self.__on_level_change, Observable.ObserverEvent.UPDATED)
            if drive.carconnectivity_drive.level.enabled:
                self.__on_level_change(drive.carconnectivity_drive.level, Observable.ObserverEvent.UPDATED)

            drive.carconnectivity_drive.range.add_observer(self.__on_range_change, Observable.ObserverEvent.UPDATED)
            if drive.carconnectivity_drive.range.enabled:
                self.__on_range_change(drive.carconnectivity_drive.range, Observable.ObserverEvent.UPDATED)

            drive.carconnectivity_drive.range_estimated_full.add_observer(self.__on_range_estimated_full_change, Observable.ObserverEvent.UPDATED)
            if drive.carconnectivity_drive.range_estimated_full.enabled:
                self.__on_range_estimated_full_change(drive.carconnectivity_drive.range_estimated_full, Observable.ObserverEvent.UPDATED)
        session_factory.remove()

    def __on_level_change(self, element: LevelAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            with self.last_level_lock:
                with self.session_factory() as session:
                    if self.last_level is not None:
                        self.last_level = session.merge(self.last_level)
                        session.refresh(self.last_level)
                    if (self.last_level is None or self.last_level.level != element.value) \
                            and element.last_updated is not None:
                        new_level: DriveLevel = DriveLevel(drive_id=self.drive.id, first_date=element.last_updated, last_date=element.last_updated,
                                                           level=element.value)
                        try:
                            session.add(new_level)
                            session.commit()
                            LOG.debug('Added new level %s for drive %s to database', element.value, self.drive.id)
                            self.last_level = new_level
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding level for drive %s to database: %s', self.drive.id, err)
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
                self.session_factory.remove()

    def __on_range_change(self, element: RangeAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            with self.last_range_lock:
                with self.session_factory() as session:
                    if self.last_range is not None:
                        self.last_range = session.merge(self.last_range)
                        session.refresh(self.last_range)
                    if (self.last_range is None or self.last_range.range != element.value) \
                            and element.last_updated is not None:
                        new_range: DriveRange = DriveRange(drive_id=self.drive.id, first_date=element.last_updated, last_date=element.last_updated,
                                                           range=element.value)
                        try:
                            session.add(new_range)
                            session.commit()
                            LOG.debug('Added new range %s for drive %s to database', element.value, self.drive.id)
                            self.last_range = new_range
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding range for drive %s to database: %s', self.drive.id, err)
                    elif self.last_range is not None and self.last_range.range == element.value \
                            and element.last_updated is not None:
                        if self.last_range.last_date is None or element.last_updated > self.last_range.last_date:
                            try:
                                self.last_range.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated range %s for drive %s in database', element.value, self.drive.id)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating range for drive %s in database: %s', self.drive.id, err)
                self.session_factory.remove()

    def __on_range_estimated_full_change(self, element: RangeAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if element.enabled:
            with self.last_range_estimated_full_lock:
                with self.session_factory() as session:
                    if self.last_range_estimated_full is not None:
                        self.last_range_estimated_full = session.merge(self.last_range_estimated_full)
                        session.refresh(self.last_range_estimated_full)
                    if (self.last_range_estimated_full is None or self.last_range_estimated_full.range_estimated_full != element.value) \
                            and element.last_updated is not None:
                        new_range: DriveRangeEstimatedFull = DriveRangeEstimatedFull(drive_id=self.drive.id, first_date=element.last_updated,
                                                                                     last_date=element.last_updated, range_estimated_full=element.value)
                        try:
                            session.add(new_range)
                            session.commit()
                            LOG.debug('Added new range_estimated_full %s for drive %s to database', element.value, self.drive.id)
                            self.last_range_estimated_full = new_range
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding range_estimated_full for drive %s to database: %s', self.drive.id, err)
                    elif self.last_range_estimated_full is not None and self.last_range_estimated_full.range_estimated_full == element.value \
                            and element.last_updated is not None:
                        if self.last_range_estimated_full.last_date is None or element.last_updated > self.last_range_estimated_full.last_date:
                            try:
                                self.last_range_estimated_full.last_date = element.last_updated
                                session.commit()
                                LOG.debug('Updated range_estimated_full %s for drive %s in database', element.value, self.drive.id)
                            except DatabaseError as err:
                                session.rollback()
                                LOG.error('DatabaseError while updating range_estimated_full for drive %s in database: %s', self.drive.id, err)
                self.session_factory.remove()
