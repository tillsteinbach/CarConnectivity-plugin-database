"""Module implements the plugin to connect with Database"""
from __future__ import annotations
from typing import TYPE_CHECKING

import threading
import logging

from sqlalchemy import Engine, create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm.session import Session

from carconnectivity.errors import ConfigurationError
from carconnectivity.util import config_remove_credentials

from carconnectivity.observable import Observable

from carconnectivity.attributes import GenericAttribute, IntegerAttribute, BooleanAttribute, FloatAttribute, StringAttribute, DateAttribute, EnumAttribute, \
    DurationAttribute

from carconnectivity_plugins.base.plugin import BasePlugin

from carconnectivity_plugins.database._version import __version__
from carconnectivity_plugins.database.model.migrations import run_database_migrations

from carconnectivity_plugins.database.model.base import Base
from carconnectivity_plugins.database.model.attribute import Attribute
from carconnectivity_plugins.database.model.attribute_value import AttributeIntegerValue, AttributeBooleanValue, AttributeFloatValue, AttributeStringValue, \
    AttributeDatetimeValue, AttributeDurationValue, AttributeEnumValue

if TYPE_CHECKING:
    from typing import Dict, Optional, Any
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
        self.engine: Engine = create_engine(self.active_config['db_url'], pool_pre_ping=True, connect_args=connect_args)
        session_factory: sessionmaker[Session] = sessionmaker(bind=self.engine)
        scoped_session_factory: scoped_session[Session] = scoped_session(session_factory)
        self.session: Session = scoped_session_factory()

        self.attribute_map: Dict[GenericAttribute, Attribute] = {}

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
        while not self._stop_event.is_set():
            try:
                self.session.execute(text('SELECT 1')).all()
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
                        run_database_migrations(dsn=self.active_config['db_url'])
                        LOG.info('Database upgrade done')

                    self.car_connectivity.add_observer(observer=self.__on_attribute_update, flag=Observable.ObserverEvent.ALL, on_transaction_end=True)

                    for attribute in self.car_connectivity.get_attributes(recursive=True):
                        self.register_attribute(attribute, commit=False)
                    self.session.commit()

            except OperationalError as err:
                LOG.error('Could not establish a connection to database, will try again after 10 seconds: %s', err)
                self.healthy._set_value(value=False)  # pylint: disable=protected-access
            self._stop_event.wait(10)

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

    def __on_attribute_update(self, element: Any, flags: Observable.ObserverEvent):
        """
        Callback for attribute updates.
        Args:
            element (Any): The updated element.
            flags (Observable.ObserverEvent): Flags indicating the type of update.
        """
        if isinstance(element, GenericAttribute):
            if flags & Observable.ObserverEvent.ENABLED:
                LOG.debug('Attribute %s enabled', element.name)
                self.register_attribute(element, commit=True)
            elif flags & Observable.ObserverEvent.DISABLED:
                LOG.debug('Attribute %s disabled', element.name)
                if element in self.attribute_map:
                    del self.attribute_map[element]
            elif flags & Observable.ObserverEvent.VALUE_CHANGED:
                LOG.debug('Attribute %s value changed', element.name)
                self.update_value(element, commit=True)

    def register_attribute(self, attribute: GenericAttribute, commit: bool = True) -> Attribute:
        """ Register an attribute in the database.
        Args:
            attribute (GenericAttribute): The attribute to register.
            commit (bool): Whether to commit the session after registering.
        Returns:
            Attribute: The database attribute instance."""
        database_attribute: Optional[Attribute] = self.session.query(Attribute).filter(Attribute.path == attribute.get_absolute_path()).first()
        if database_attribute is None:
            database_attribute = Attribute.from_generic_attribute(attribute)
            self.session.add(database_attribute)
        self.attribute_map[attribute] = database_attribute
        LOG.debug('Registering attribute %s', attribute.name)
        self.update_value(attribute=attribute, commit=commit)
        LOG.debug('Updated value for attribute %s to %s', attribute.name, attribute.value)
        if commit:
            self.session.commit()
        return database_attribute

    # pylint: disable-next=too-many-branches, too-many-statements
    def update_value(self, attribute: GenericAttribute, commit: bool = True) -> None:
        """ Update the value of an attribute in the database.
        Args:
            attribute (GenericAttribute): The attribute to update.
            commit (bool): Whether to commit the session after updating."""
        if attribute not in self.attribute_map:
            database_attribute: Attribute = self.register_attribute(attribute, commit=commit)
        else:
            database_attribute = self.attribute_map[attribute]
        if attribute.last_updated is not None:
            if isinstance(attribute, IntegerAttribute):
                last_integer_value: Optional[AttributeIntegerValue] = self.session.query(AttributeIntegerValue) \
                    .filter(AttributeIntegerValue.attribute == database_attribute) \
                    .order_by(AttributeIntegerValue.start_date.desc()).first()
                if last_integer_value is None or last_integer_value.value != attribute.value:
                    last_integer_value = AttributeIntegerValue(attribute=database_attribute, start_date=attribute.last_updated, value=attribute.value)
                    last_integer_value.end_date = attribute.last_updated
                    self.session.add(last_integer_value)
                    LOG.debug('Updating value for attribute %s to %s', attribute.name, attribute.value)
                else:
                    last_integer_value.value = attribute.value
                    last_integer_value.end_date = attribute.last_updated
            elif isinstance(attribute, BooleanAttribute):
                last_boolean_value: Optional[AttributeBooleanValue] = self.session.query(AttributeBooleanValue) \
                    .filter(AttributeBooleanValue.attribute == database_attribute) \
                    .order_by(AttributeBooleanValue.start_date.desc()).first()
                if last_boolean_value is None or last_boolean_value.value != attribute.value:
                    last_boolean_value = AttributeBooleanValue(attribute=database_attribute, start_date=attribute.last_updated, value=attribute.value)
                    last_boolean_value.end_date = attribute.last_updated
                    self.session.add(last_boolean_value)
                    LOG.debug('Updating value for attribute %s to %s', attribute.name, attribute.value)
                else:
                    last_boolean_value.value = attribute.value
                    last_boolean_value.end_date = attribute.last_updated
            elif isinstance(attribute, FloatAttribute):
                last_float_value: Optional[AttributeFloatValue] = self.session.query(AttributeFloatValue) \
                    .filter(AttributeFloatValue.attribute == database_attribute) \
                    .order_by(AttributeFloatValue.start_date.desc()).first()
                if last_float_value is None or last_float_value.value != attribute.value:
                    last_float_value = AttributeFloatValue(attribute=database_attribute, start_date=attribute.last_updated, value=attribute.value)
                    last_float_value.end_date = attribute.last_updated
                    self.session.add(last_float_value)
                    LOG.debug('Updating value for attribute %s to %s', attribute.name, attribute.value)
                else:
                    last_float_value.value = attribute.value
                    last_float_value.end_date = attribute.last_updated
            elif isinstance(attribute, StringAttribute):
                last_string_value: Optional[AttributeStringValue] = self.session.query(AttributeStringValue) \
                    .filter(AttributeStringValue.attribute == database_attribute) \
                    .order_by(AttributeStringValue.start_date.desc()).first()
                if last_string_value is None or last_string_value.value != attribute.value:
                    last_string_value = AttributeStringValue(attribute=database_attribute, start_date=attribute.last_updated, value=attribute.value)
                    last_string_value.end_date = attribute.last_updated
                    self.session.add(last_string_value)
                    LOG.debug('Updating value for attribute %s to %s', attribute.name, attribute.value)
                else:
                    last_string_value.value = attribute.value
                    last_string_value.end_date = attribute.last_updated
            elif isinstance(attribute, DateAttribute):
                last_datetime_value: Optional[AttributeDatetimeValue] = self.session.query(AttributeDatetimeValue) \
                    .filter(AttributeDatetimeValue.attribute == database_attribute) \
                    .order_by(AttributeDatetimeValue.start_date.desc()).first()
                if last_datetime_value is None or last_datetime_value.value != attribute.value:
                    last_datetime_value = AttributeDatetimeValue(attribute=database_attribute, start_date=attribute.last_updated, value=attribute.value)
                    last_datetime_value.end_date = attribute.last_updated
                    self.session.add(last_datetime_value)
                    LOG.debug('Updating value for attribute %s to %s', attribute.name, attribute.value)
                else:
                    last_datetime_value.value = attribute.value
                    last_datetime_value.end_date = attribute.last_updated
            elif isinstance(attribute, DurationAttribute):
                last_duration_value: Optional[AttributeDurationValue] = self.session.query(AttributeDurationValue) \
                    .filter(AttributeDurationValue.attribute == database_attribute) \
                    .order_by(AttributeDurationValue.start_date.desc()).first()
                if last_duration_value is None or last_duration_value.value != attribute.value:
                    last_duration_value = AttributeDurationValue(attribute=database_attribute, start_date=attribute.last_updated, value=attribute.value)
                    last_duration_value.end_date = attribute.last_updated
                    self.session.add(last_duration_value)
                    LOG.debug('Updating value for attribute %s to %s', attribute.name, attribute.value)
                else:
                    last_duration_value.value = attribute.value
                    last_duration_value.end_date = attribute.last_updated
            elif isinstance(attribute, EnumAttribute):
                last_enum_value: Optional[AttributeEnumValue] = self.session.query(AttributeEnumValue) \
                    .filter(AttributeEnumValue.attribute == database_attribute) \
                    .order_by(AttributeEnumValue.start_date.desc()).first()
                if attribute.value is None:
                    value: Optional[str] = None
                else:
                    value = attribute.value.value
                if last_enum_value is None or last_enum_value.value != value:
                    last_enum_value = AttributeEnumValue(attribute=database_attribute, start_date=attribute.last_updated, value=value)
                    last_enum_value.end_date = attribute.last_updated
                    self.session.add(last_enum_value)
                    LOG.debug('Updating value for attribute %s to %s', attribute.name, attribute.value)
                else:
                    last_enum_value.value = value
                    last_enum_value.end_date = attribute.last_updated
            else:
                LOG.debug('Attribute type %s is not supported for database storage', type(attribute).__name__)
                return
            if commit:
                self.session.commit()
