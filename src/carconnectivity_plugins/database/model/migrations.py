""" Module for running database migrations using Alembic."""
import os

from alembic.command import upgrade, stamp
from alembic.config import Config


def run_database_migrations(dsn: str, stamp_only: bool = False):
    """Run database migrations using Alembic."""
    # retrieves the directory that *this* file is in
    migrations_dir = os.path.dirname(os.path.realpath(__file__))
    # this assumes the alembic.ini is also contained in this same directory
    config_file = os.path.join(migrations_dir, "alembic.ini")

    config = Config(file_=config_file)
    config.attributes['configure_logger'] = False
    config.set_main_option("script_location", migrations_dir + '/carconnectivity_schema')
    config.set_main_option('sqlalchemy.url', dsn)

    if stamp_only:
        stamp(config, "head")
    else:
        # upgrade the database to the latest revision
        upgrade(config, "head")
