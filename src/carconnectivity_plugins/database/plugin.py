"""Module implements the plugin to connect with Database"""
from __future__ import annotations
from typing import TYPE_CHECKING

import threading

import locale

import logging

from sqlalchemy import Engine, create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import DatabaseError, OperationalError, IntegrityError
from sqlalchemy.orm.session import Session

from carconnectivity.errors import ConfigurationError
from carconnectivity.util import config_remove_credentials
from carconnectivity.observable import Observable
from carconnectivity.vehicle import GenericVehicle
from carconnectivity.utils.timeout_lock import TimeoutLock

from carconnectivity_plugins.base.plugin import BasePlugin

from carconnectivity_plugins.database._version import __version__
from carconnectivity_plugins.database.model.migrations import run_database_migrations
from carconnectivity_plugins.database.model.vehicle import Vehicle

from carconnectivity_plugins.database.model.base import Base


if TYPE_CHECKING:
    from typing import Dict, Optional
    from carconnectivity.carconnectivity import CarConnectivity

LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.database")


class Plugin(BasePlugin):  # pylint: disable=too-many-instance-attributes
    """
    Plugin class for Database connectivity.
    Args:
        car_connectivity (CarConnectivity): An instance of CarConnectivity.
        config (Dict): Configuration dictionary containing connection details.
    """
    def __init__(self, plugin_id: str, car_connectivity: CarConnectivity, config: Dict, *args, initialization: Optional[Dict] = None, **kwargs) -> None:
        BasePlugin.__init__(self, plugin_id=plugin_id, car_connectivity=car_connectivity, config=config, log=LOG, *args, initialization=initialization,
                            **kwargs)

        self._background_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        LOG.info("Loading database plugin with config %s", config_remove_credentials(config))

        if 'db_url' in config:
            self.active_config['db_url'] = config['db_url']
        else:
            raise ConfigurationError('db_url must be configured in the plugin config')

        if 'locale' in config and config['locale'] is not None:
            self.active_config['locale'] = config['locale']
            try:
                locale.setlocale(locale.LC_ALL, self.active_config['locale'])
                if self.active_config['time_format'] is None or self.active_config['time_format'] == '':
                    self.active_config['time_format'] = locale.nl_langinfo(locale.D_T_FMT)
            except locale.Error as err:
                LOG.warning('Invalid locale specified in config ("locale" must be a valid locale): %s', err)
        elif 'locale' in self.car_connectivity.active_config and self.car_connectivity.active_config['locale'] is not None:
            self.active_config['locale'] = self.car_connectivity.active_config['locale']
            try:
                if 'time_format' in self.car_connectivity.active_config \
                        and (self.car_connectivity.active_config['time_format'] is None or self.car_connectivity.active_config['time_format'] == ''):
                    self.active_config['time_format'] = locale.nl_langinfo(locale.D_T_FMT)
            except locale.Error as err:
                LOG.warning('Invalid locale specified in config ("locale" must be a valid locale): %s', err)
        else:
            self.active_config['locale'] = locale.getlocale()[0]
        self.locale: str = self.active_config['locale'] or ''

        connect_args = {}
        if 'postgresql' in self.active_config['db_url']:
            connect_args['options'] = '-c timezone=utc'
        self.engine: Engine = create_engine(self.active_config['db_url'], pool_pre_ping=True, connect_args=connect_args)
        session_factory: sessionmaker[Session] = sessionmaker(bind=self.engine, autoflush=True, expire_on_commit=False)
        self.scoped_session_factory: scoped_session[Session] = scoped_session(session_factory)

        self.vehicles: Dict[str, Vehicle] = {}
        self.vehicles_lock: TimeoutLock = TimeoutLock()

    def startup(self) -> None:
        LOG.info("Starting database plugin")
        self._background_thread = threading.Thread(target=self._background_loop, daemon=False)
        self._background_thread.name = 'carconnectivity.plugins.database-background'
        self._background_thread.start()
        self.healthy._set_value(value=True)  # pylint: disable=protected-access
        LOG.debug("Starting Database plugin done")
        return super().startup()

    def _background_loop(self) -> None:
        self._stop_event.clear()
        first_run: bool = True
        with self.scoped_session_factory() as session:
            while not self._stop_event.is_set():
                try:
                    session.execute(text('SELECT 1')).all()
                    self.healthy._set_value(value=True)  # pylint: disable=protected-access
                    if first_run:
                        LOG.info('Database connection established successfully')
                        first_run = False
                        if not inspect(self.engine).has_table("alembic_version"):
                            LOG.info('It looks like you have an empty database will create all tables')
                            Base.metadata.create_all(self.engine)
                            run_database_migrations(dsn=self.active_config['db_url'], stamp_only=True)
                        else:
                            LOG.info('It looks like you have an existing database will check if an upgrade is necessary')
                            Base.metadata.create_all(self.engine)  # TODO: remove after some time
                            run_database_migrations(dsn=self.active_config['db_url'])
                            LOG.info('Database upgrade done')
                        session.commit()
                        self.car_connectivity.garage.add_observer(self.__on_add_vehicle, flag=Observable.ObserverEvent.ENABLED, on_transaction_end=True)
                        with self.vehicles_lock:
                            for garage_vehicle in self.car_connectivity.garage.list_vehicles():
                                if garage_vehicle.vin.value is not None and garage_vehicle.vin.value not in self.vehicles:
                                    LOG.debug('New vehicle found in garage during startup: %s', garage_vehicle.vin.value)
                                    new_vehicle: Vehicle = session.get(Vehicle, garage_vehicle.vin.value)
                                    if new_vehicle is None:
                                        new_vehicle: Vehicle = Vehicle(vin=garage_vehicle.vin.value)
                                        try:
                                            session.add(new_vehicle)
                                            session.commit()
                                            LOG.debug('Added new vehicle %s to database', garage_vehicle.vin.value)
                                            new_vehicle.connect(self, self.scoped_session_factory, garage_vehicle)
                                            self.vehicles[garage_vehicle.vin.value] = new_vehicle
                                        except IntegrityError as err:
                                            session.rollback()
                                            LOG.error('IntegrityError while adding vehicle %s to database: %s', garage_vehicle.vin.value, err)
                                            self.healthy._set_value(value=False)  # pylint: disable=protected-access
                                        except DatabaseError as err:
                                            session.rollback()
                                            LOG.error('DatabaseError while adding vehicle %s to database: %s', garage_vehicle.vin.value, err)
                                            self.healthy._set_value(value=False)  # pylint: disable=protected-access
                                    else:
                                        new_vehicle.connect(self, self.scoped_session_factory, garage_vehicle)
                                        self.vehicles[garage_vehicle.vin.value] = new_vehicle
                except OperationalError as err:
                    LOG.error('Could not establish a connection to database, will try again after 10 seconds: %s', err)
                    self.healthy._set_value(value=False)  # pylint: disable=protected-access
                self._stop_event.wait(10)
        self.scoped_session_factory.remove()

    def shutdown(self) -> None:
        self.car_connectivity.garage.remove_observer(self.__on_add_vehicle)
        self._stop_event.set()
        if self._background_thread is not None:
            self._background_thread.join()
        return super().shutdown()

    def get_version(self) -> str:
        return __version__

    def get_type(self) -> str:
        return "carconnectivity-plugin-database"

    def get_name(self) -> str:
        return "Database Plugin"

    def __on_add_vehicle(self, element, flags) -> None:
        del flags
        with self.vehicles_lock:
            if isinstance(element, GenericVehicle) and element.vin.value is not None and element.vin.value not in self.vehicles:
                LOG.debug('New vehicle added to garage: %s', element.vin)
                with self.scoped_session_factory() as session:
                    vehicle: Vehicle = session.get(Vehicle, element.vin.value)
                    if vehicle is None:
                        vehicle = Vehicle(vin=element.vin.value)
                        try:
                            session.add(vehicle)
                            session.commit()
                            vehicle.connect(self, self.scoped_session_factory, element)
                        except IntegrityError as err:
                            session.rollback()
                            LOG.error('IntegrityError while adding vehicle %s to database: %s', element.vin.value, err)
                            self.healthy._set_value(value=False)  # pylint: disable=protected-access
                        except DatabaseError as err:
                            session.rollback()
                            LOG.error('DatabaseError while adding vehicle %s to database: %s', element.vin.value, err)
                            self.healthy._set_value(value=False)  # pylint: disable=protected-access
                    else:
                        vehicle.connect(self, self.scoped_session_factory, element)
                    self.vehicles[element.vin.value] = vehicle
                self.scoped_session_factory.remove()
