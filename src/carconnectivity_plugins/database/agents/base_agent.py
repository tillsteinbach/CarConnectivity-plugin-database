"""
Base agent class for database plugin agents.

This module provides the foundational BaseAgent class that serves as a parent
for all database agent implementations in the CarConnectivity database plugin.
Agents are responsible for handling specific database operations and interactions.

Classes:
    BaseAgent: Abstract base class for database agents.

"""


# pylint: disable-next=too-few-public-methods
class BaseAgent():
    """
    Base class for database agents in the CarConnectivity plugin system.
    This class serves as an abstract base for implementing specific database agents
    that handle data persistence and retrieval operations for vehicle connectivity data.
    Agents extending this class should implement the necessary methods for interacting
    with their respective database backends.
    """
