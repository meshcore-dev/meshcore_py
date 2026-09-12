"""A library for communicating with meshcore devices."""
import logging

from .ble_cx import BLEConnection
from .connection_manager import ConnectionManager
from .events import EventType
from .meshcore import MeshCore
from .packets import BinaryReqType
from .serial_cx import SerialConnection
from .tcp_cx import TCPConnection

# Setup default logger. Libraries must not configure the root logger (that's
# the embedding application's call) - a NullHandler just silences the "no
# handlers found" warning when the app hasn't configured logging at all.
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    "BinaryReqType",
    "BLEConnection",
    "ConnectionManager",
    "EventType",
    "MeshCore",
    "SerialConnection",
    "TCPConnection",
    "logger",
]
