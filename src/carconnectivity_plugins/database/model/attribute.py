from sqlalchemy import Column, String, Integer

from carconnectivity_plugins.database.model.base import Base
from carconnectivity_plugins.database.model.datetime_decorator import DatetimeDecorator


class Attribute(Base):
    __tablename__ = 'attribute'
    id: Column[int] = Column(Integer, primary_key=True)
    path: Column[str] = Column(String, nullable=False, unique=True, index=True)

    def __init__(self, path: str) -> None:
        self.path: str = path
