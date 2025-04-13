import logging

# Setup default logger
logging.basicConfig(level=logging.INFO)

from meshcore.events import EventType
from meshcore.meshcore import MeshCore, logger
from meshcore.tcp_cx import TCPConnection
from meshcore.ble_cx import BLEConnection
from meshcore.serial_cx import SerialConnection
