"""Module implements the plugin to connect with Database"""
from __future__ import annotations
from typing import TYPE_CHECKING

import threading
import traceback
import logging

from sqlalchemy import Engine, create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import OperationalError

from carconnectivity.errors import ConfigurationError
from carconnectivity.util import config_remove_credentials
from carconnectivity_plugins.base.plugin import BasePlugin
from sqlalchemy.orm.session import Session
from carconnectivity_plugins.database._version import __version__


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
    def __init__(self, plugin_id: str, car_connectivity: CarConnectivity, config: Dict) -> None:
        BasePlugin.__init__(self, plugin_id=plugin_id, car_connectivity=car_connectivity, config=config, log=LOG)

        self._background_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        LOG.info("Loading database plugin with config %s", config_remove_credentials(config))

        if 'db_url' in config:
            self.active_config['db_url'] = config['db_url']
        else:
            raise ConfigurationError('db_url must be configured in the plugin config')

        connect_args = {}
        if 'postgresql' in self.active_config['db_url']:
            connect_args['options'] = '-c timezone=utc'
        engine: Engine = create_engine(self.active_config['db_url'], pool_pre_ping=True, connect_args=connect_args)
        session_factory: sessionmaker[Session] = sessionmaker(bind=engine)
        scoped_session_factory: scoped_session[Session] = scoped_session(session_factory)
        self.session: Session = scoped_session_factory()

    def startup(self) -> None:
        LOG.info("Starting database plugin")
        self._background_thread = threading.Thread(target=self._background_loop, daemon=False)
        self._background_thread.name = 'carconnectivity.plugins.database-background'
        self._background_thread.start()
        self.healthy._set_value(value=True)  # pylint: disable=protected-access
        LOG.debug("Starting Database plugin done")

    def _background_loop(self) -> None:
        self._stop_event.clear()
        while not self._stop_event.is_set():
            try:
                #self.session.query(text('1')).from_statement(text('SELECT 1')).all()
                self.session.execute(text('SELECT 1')).all()
            except OperationalError as err:
                LOG.error('Could not establish a connection to database, will try again after 10 seconds: %s', err)
                self.healthy._set_value(value=False)  # pylint: disable=protected-access
                self._stop_event.wait(10)
                continue
            self.healthy._set_value(value=True)  # pylint: disable=protected-access
            break

    def shutdown(self) -> None:
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
