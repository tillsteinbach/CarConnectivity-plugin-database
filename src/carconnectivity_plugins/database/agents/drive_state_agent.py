from __future__ import annotations
from typing import TYPE_CHECKING

from carconnectivity.observable import Observable

from carconnectivity_plugins.database.agents.base_agent import BaseAgent
from carconnectivity_plugins.database.model.drive_level import DriveLevel
from carconnectivity_plugins.database.model.drive_range import DriveRange

if TYPE_CHECKING:
    from typing import Optional
    from sqlalchemy.orm.session import Session

    from carconnectivity.attributes import LevelAttribute, RangeAttribute

    from carconnectivity_plugins.database.model.drive import Drive


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
            with self.session.begin_nested():
                self.session.add(new_level)
            self.session.commit()
            self.last_level = new_level
        elif self.last_level is not None and self.last_level.level == element.value \
                and element.last_updated is not None:
            if self.last_level.last_date is None or element.last_updated > self.last_level.last_date:
                with self.session.begin_nested():
                    self.last_level.last_date = element.last_updated
                self.session.commit()

    def __on_range_change(self, element: RangeAttribute, flags: Observable.ObserverEvent) -> None:
        del flags
        if self.last_range is not None:
            self.session.refresh(self.last_range)
        if (self.last_range is None or self.last_range.range != element.value) \
                and element.last_updated is not None:
            new_range: DriveRange = DriveRange(drive_id=self.drive.id, first_date=element.last_updated, last_date=element.last_updated,
                                               range=element.value)
            with self.session.begin_nested():
                self.session.add(new_range)
            self.session.commit()
            self.last_range = new_range
        elif self.last_range is not None and self.last_range.range == element.value \
                and element.last_updated is not None:
            if self.last_range.last_date is None or element.last_updated > self.last_range.last_date:
                with self.session.begin_nested():
                    self.last_range.last_date = element.last_updated
                self.session.commit()
