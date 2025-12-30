from __future__ import annotations
from typing import TYPE_CHECKING

import logging

from sqlalchemy.exc import DatabaseError

from carconnectivity.observable import Observable

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.drive_level import DriveLevel
from carconnectivity_plugins.database.model.drive_range import DriveRange

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import LevelAttribute, RangeAttribute

    from carconnectivity_plugins.database.model.drive import Drive


LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database.agents.drive_state_agent")

class DriveStateAgent(BaseAgent):
    def __init__(self, session: Session, drive: Drive) -> None:
        if drive is None or drive.carconnectivity_drive is None:
            raise ValueError("Drive or its carconnectivity_drive attribute is None")
        self.session: Session = session
        self.drive: Drive = drive

        self.last_level: Optional[DriveLevel] = session.query(DriveLevel).filter(DriveLevel.drive_id == drive.id).order_by(DriveLevel.first_date.desc()).first()
        self.last_range: Optional[DriveRange] = session.query(DriveRange).filter(DriveRange.drive_id == drive.id).order_by(DriveRange.first_date.desc()).first()

        drive.carconnectivity_drive.level.add_observer(self.__on_level_change, Observable.ObserverEvent.UPDATED)
        self.__on_level_change(drive.carconnectivity_drive.level, Observable.ObserverEvent.UPDATED)

        drive.carconnectivity_drive.range.add_observer(self.__on_range_change, Observable.ObserverEvent.UPDATED)
        self.__on_range_change(drive.carconnectivity_drive.range, Observable.ObserverEvent.UPDATED)

    def __on_level_change(self, element: LevelAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.last_level is not None:
            self.session.refresh(self.last_level)
        if (self.last_level is None or self.last_level.level != element.value) \
                and element.last_updated is not None:
            new_level: DriveLevel = DriveLevel(drive_id=self.drive.id, first_date=element.last_updated, last_date=element.last_updated,
                                               level=element.value)
            try:
                self.session.add(new_level)
                self.session.flush()
                self.last_level = new_level
            except DatabaseError as err:
                self.session.rollback()
                LOG.error('DatabaseError while adding level for drive %s to database: %s', self.drive.id, err)
        elif self.last_level is not None and self.last_level.level == element.value \
                and element.last_updated is not None:
            if self.last_level.last_date is None or element.last_updated > self.last_level.last_date:
                try:
                    with self.session.begin_nested():
                        self.last_level.last_date = element.last_updated
                    self.session.commit()
                except DatabaseError as err:
                    self.session.rollback()
                    LOG.error('DatabaseError while updating level for drive %s in database: %s', self.drive.id, err)

    def __on_range_change(self, element: RangeAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.last_range is not None:
            self.session.refresh(self.last_range)
        if (self.last_range is None or self.last_range.range != element.value) \
                and element.last_updated is not None:
            new_range: DriveRange = DriveRange(drive_id=self.drive.id, first_date=element.last_updated, last_date=element.last_updated,
                                               range=element.value)
            try:
                with self.session.begin_nested():
                    self.session.add(new_range)
                self.session.commit()
                self.last_range = new_range
            except DatabaseError as err:
                self.session.rollback()
                LOG.error('DatabaseError while adding range for drive %s to database: %s', self.drive.id, err)
        elif self.last_range is not None and self.last_range.range == element.value \
                and element.last_updated is not None:
            if self.last_range.last_date is None or element.last_updated > self.last_range.last_date:
                try:
                    with self.session.begin_nested():
                        self.last_range.last_date = element.last_updated
                    self.session.commit()
                except DatabaseError as err:
                    self.session.rollback()
                    LOG.error('DatabaseError while updating range for drive %s in database: %s', self.drive.id, err)
