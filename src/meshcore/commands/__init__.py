from typing import Any, Optional

from ..events import EventDispatcher
from ..reader import MessageReader
from .base import CommandHandlerBase
from .binary import BinaryCommandHandler
from .contact import ContactCommands
from .device import DeviceCommands
from .messaging import MessagingCommands


class CommandHandler(
    DeviceCommands, ContactCommands, MessagingCommands, BinaryCommandHandler
):
    pass


__all__ = ["CommandHandler"]
