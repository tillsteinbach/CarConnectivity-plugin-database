""" Connectors UI module for the web UI"""
from __future__ import annotations
from typing import TYPE_CHECKING, List

import flask
from flask_login import login_required

from carconnectivity_plugins.database.model.vehicle import Vehicle

if TYPE_CHECKING:
    from flask_sqlalchemy import SQLAlchemy

    from carconnectivity.carconnectivity import CarConnectivity

bp_database_edit = flask.Blueprint('edit', __name__, url_prefix='/edit')


@bp_database_edit.route('/overview', methods=['GET'])
@login_required
def overview():
    if 'car_connectivity' not in flask.current_app.extensions or flask.current_app.extensions['car_connectivity'] is None:
        flask.abort(500, "car_connectivity instance not connected")
    car_connectivity: CarConnectivity = flask.current_app.extensions['car_connectivity']
    return flask.render_template('database/edit/overview.html', current_app=flask.current_app)

@bp_database_edit.route('/vehicles', methods=['GET'])
@login_required
def vehicles():
    if 'car_connectivity' not in flask.current_app.extensions or flask.current_app.extensions['car_connectivity'] is None:
        flask.abort(500, "car_connectivity instance not connected")
    car_connectivity: CarConnectivity = flask.current_app.extensions['car_connectivity']
    db: SQLAlchemy = flask.current_app.extensions['db']
    vehicles: List[Vehicle] = db.session.query(Vehicle).order_by(Vehicle.name.asc()).all()
    return flask.render_template('database/edit/vehicles.html', current_app=flask.current_app, vehicles=vehicles or [])