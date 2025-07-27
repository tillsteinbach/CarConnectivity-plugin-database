""" User interface for the Database plugin in the Car Connectivity application. """
from __future__ import annotations
from typing import TYPE_CHECKING

import os

import flask
import flask_login

from carconnectivity_plugins.base.plugin import BasePlugin
from carconnectivity_plugins.base.ui.plugin_ui import BasePluginUI

if TYPE_CHECKING:
    from typing import Optional, List, Dict, Union, Literal


class PluginUI(BasePluginUI):
    """
    A user interface class for the Database plugin in the Car Connectivity application.
    """
    def __init__(self, plugin: BasePlugin):
        blueprint: Optional[flask.Blueprint] = flask.Blueprint(name=plugin.id, import_name='carconnectivity-plugin-database', url_prefix=f'/{plugin.id}',
                                                               template_folder=os.path.dirname(__file__) + '/templates')
        super().__init__(plugin, blueprint=blueprint)

        @self.blueprint.route('/', methods=['GET'])
        def root():
            return flask.redirect(flask.url_for('plugins.database.status'))

        @self.blueprint.route('/status', methods=['GET'])
        @flask_login.login_required
        def status():
            return flask.render_template('database/status.html', current_app=flask.current_app, plugin=self.plugin)

    def get_nav_items(self) -> List[Dict[Literal['text', 'url', 'sublinks', 'divider'], Union[str, List]]]:
        """
        Generates a list of navigation items for the Database plugin UI.
        """
        return super().get_nav_items() + [{"text": "Status", "url": flask.url_for('plugins.database.status')}]

    def get_title(self) -> str:
        """
        Returns the title of the plugin.

        Returns:
            str: The title of the plugin, which is "Database".
        """
        return "Database"
