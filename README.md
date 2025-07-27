

# CarConnectivity Plugin for Database storage
[![GitHub sourcecode](https://img.shields.io/badge/Source-GitHub-green)](https://github.com/tillsteinbach/CarConnectivity-plugin-database/)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/tillsteinbach/CarConnectivity-plugin-database)](https://github.com/tillsteinbach/CarConnectivity-plugin-database/releases/latest)
[![GitHub](https://img.shields.io/github/license/tillsteinbach/CarConnectivity-plugin-database)](https://github.com/tillsteinbach/CarConnectivity-plugin-database/blob/master/LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/tillsteinbach/CarConnectivity-plugin-database)](https://github.com/tillsteinbach/CarConnectivity-plugin-database/issues)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/carconnectivity-plugin-database?label=PyPI%20Downloads)](https://pypi.org/project/carconnectivity-plugin-database/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/carconnectivity-plugin-database)](https://pypi.org/project/carconnectivity-plugin-database/)
[![Donate at PayPal](https://img.shields.io/badge/Donate-PayPal-2997d8)](https://www.paypal.com/donate?hosted_button_id=2BVFF5GJ9SXAJ)
[![Sponsor at Github](https://img.shields.io/badge/Sponsor-GitHub-28a745)](https://github.com/sponsors/tillsteinbach)

[CarConnectivity](https://github.com/tillsteinbach/CarConnectivity) is a python API to connect to various car services. If you want to store the data collected from your vehicle to a relational database (e.g. MySQL, PostgreSQL, or SQLite) this plugin will help you.

### Install using PIP
If you want to use the CarConnectivity Plugin for Databases, the easiest way is to obtain it from [PyPI](https://pypi.org/project/carconnectivity-plugin-database/). Just install it using:
```bash
pip3 install carconnectivity-plugin-database
```
after you installed CarConnectivity

## Configuration
In your carconnectivity.json configuration add a section for the database plugin like this. A documentation of all possible config options can be found [here](https://github.com/tillsteinbach/CarConnectivity-plugin-database/tree/main/doc/Config.md).
```
{
    "carConnectivity": {
        "connectors": [
            ...
        ]
        "plugins": [
            {
                "type": "database",
                "config": {
                    "db_url": "sqlite:///carconnectivity.db"
                }
            }
        ]
    }
}
```

## Updates
If you want to update, the easiest way is:
```bash
pip3 install carconnectivity-plugin-database --upgrade
```
