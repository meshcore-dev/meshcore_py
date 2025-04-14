import asyncio
import logging
from typing import Optional, Dict, Any, Union

from .events import EventDispatcher, EventType
from .reader import MessageReader
from .commands import CommandHandler


# Setup default logger
logger = logging.getLogger("meshcore")

class MeshCore:
    """
    Interface to a MeshCore device
    """
    def __init__(self, cx, debug=False, default_timeout=None):
        self.cx = cx
        self.dispatcher = EventDispatcher()
        self._reader = MessageReader(self.dispatcher)
        self.commands = CommandHandler(default_timeout=default_timeout)
        
        # Set up logger
        if debug:
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)
        
        # Set up connections
        self.commands.set_connection(cx)
        
        # Set the dispatcher in the command handler
        self.commands.set_dispatcher(self.dispatcher)
        self.commands.set_reader(self._reader)
        
        # Initialize state (private)
        self._contacts = {}
        self._self_info = {}
        self._time = 0
        
        # Set up event subscriptions to track data
        self._setup_data_tracking()
        
        cx.set_reader(self._reader)
    
    @classmethod
    async def create_tcp(cls, host: str, port: int, debug: bool = False, default_timeout=None) -> 'MeshCore':
        """Create and connect a MeshCore instance using TCP connection"""
        from .tcp_cx import TCPConnection
        
        connection = TCPConnection(host, port)
        await connection.connect()
        
        mc = cls(connection, debug=debug, default_timeout=default_timeout)
        await mc.connect()
        return mc
    
    @classmethod
    async def create_serial(cls, port: str, baudrate: int = 115200, debug: bool = False, default_timeout=None) -> 'MeshCore':
        """Create and connect a MeshCore instance using serial connection"""
        from .serial_cx import SerialConnection
        import asyncio
        
        connection = SerialConnection(port, baudrate)
        await connection.connect()
        await asyncio.sleep(0.1)  # Time for transport to establish
        
        mc = cls(connection, debug=debug, default_timeout=default_timeout)
        await mc.connect()
        return mc
    
    @classmethod
    async def create_ble(cls, address: Optional[str] = None, debug: bool = False, default_timeout=None) -> 'MeshCore':
        """Create and connect a MeshCore instance using BLE connection
        
        If address is None, it will scan for and connect to the first available MeshCore device.
        """
        from .ble_cx import BLEConnection
        
        connection = BLEConnection(address)
        result = await connection.connect()
        if result is None:
            raise ConnectionError("Failed to connect to BLE device")
        
        mc = cls(connection, debug=debug, default_timeout=default_timeout)
        await mc.connect()
        return mc
        
    async def connect(self):
        await self.dispatcher.start()
        return await self.commands.send_appstart()
    
    async def disconnect(self):
        await self.dispatcher.stop()
    
    def stop(self):
        """Synchronously stop the event dispatcher task"""
        if self.dispatcher._task and not self.dispatcher._task.done():
            self.dispatcher.running = False
            self.dispatcher._task.cancel()
    
    def subscribe(self, event_type: EventType, callback, attribute_filters: Optional[Dict[str, Any]] = None):
        """
        Subscribe to events using EventType enum with optional attribute filtering
        
        Args:
            event_type: Type of event to subscribe to, from EventType enum
            callback: Async function to call when event occurs
            attribute_filters: Dictionary of attribute key-value pairs that must match for the event to trigger the callback
            
        Returns:
            Subscription object that can be used to unsubscribe
            
        Example:
            # Subscribe to ACK events where the 'code' attribute has a specific value
            mc.subscribe(
                EventType.ACK, 
                my_callback_function,
                attribute_filters={'code': 'SUCCESS'}
            )
        """
        return self.dispatcher.subscribe(event_type, callback, attribute_filters)
    
    def unsubscribe(self, subscription):
        """
        Unsubscribe from events using a subscription object
        
        Args:
            subscription: Subscription object returned from subscribe()
        """
        if subscription:
            subscription.unsubscribe()
    
    async def wait_for_event(self, event_type: EventType, attribute_filters: Optional[Dict[str, Any]] = None, timeout=None):
        """
        Wait for an event using EventType enum with optional attribute filtering
        
        Args:
            event_type: Type of event to wait for, from EventType enum
            attribute_filters: Dictionary of attribute key-value pairs to match against the event
            timeout: Maximum time to wait in seconds, or None to use default_timeout
            
        Returns:
            Event object or None if timeout
            
        Example:
            # Wait for an ACK event where the 'code' attribute has a specific value
            await mc.wait_for_event(
                EventType.ACK, 
                attribute_filters={'code': 'SUCCESS'},
                timeout=30.0
            )
        """
        # Use the provided timeout or fall back to default_timeout
        if timeout is None:
            timeout = self.default_timeout
            
        return await self.dispatcher.wait_for_event(event_type, attribute_filters, timeout)
    
    def _setup_data_tracking(self):
        """Set up event subscriptions to track data internally"""
        async def _update_contacts(event):
            self._contacts = event.payload
            
        async def _update_self_info(event):
            self._self_info = event.payload
            
        async def _update_time(event):
            self._time = event.payload.get("time", 0)
            
        # Subscribe to events to update internal state
        self.subscribe(EventType.CONTACTS, _update_contacts)
        self.subscribe(EventType.SELF_INFO, _update_self_info)
        self.subscribe(EventType.CURRENT_TIME, _update_time)
    
    # Getter methods for state
    @property
    def contacts(self):
        """Get the current contacts"""
        return self._contacts
        
    @property
    def self_info(self):
        """Get device self info"""
        return self._self_info
        
    @property
    def time(self):
        """Get the current device time"""
        return self._time
        
    @property
    def default_timeout(self):
        """Get the default timeout for commands"""
        return self.commands.default_timeout
        
    @default_timeout.setter
    def default_timeout(self, value):
        """Set the default timeout for commands"""
        self.commands.default_timeout = value
        
    def get_contact_by_name(self, name) -> Optional[Dict[str, Any]]:
        """
        Find a contact by its name (adv_name field)
        
        Args:
            name: The name to search for
            
        Returns:
            Contact dictionary or None if not found
        """
        if not self._contacts:
            return None
            
        for _, contact in self._contacts.items():
            if contact.get("adv_name", "").lower() == name.lower():
                return contact
                
        return None
        
    def get_contact_by_key_prefix(self, prefix) -> Optional[Dict[str, Any]]:
        """
        Find a contact by its public key prefix
        
        Args:
            prefix: The public key prefix to search for (can be a partial prefix)
            
        Returns:
            Contact dictionary or None if not found
        """
        if not self._contacts or not prefix:
            return None
            
        # Convert the prefix to lowercase for case-insensitive matching
        prefix = prefix.lower()
        
        for contact_id, contact in self._contacts.items():
            public_key = contact.get("public_key", "").lower()
            if public_key.startswith(prefix):
                return contact
                
        return None
    
    async def start_auto_message_fetching(self):
        """
        Start automatically fetching messages when messages_waiting events are received.
        This will continuously check for new messages when the device indicates 
        messages are waiting.
        """
        self._auto_fetch_task = None
        self._auto_fetch_running = True
        
        async def _handle_messages_waiting(event):
            # Only start a new fetch task if one isn't already running
            if not self._auto_fetch_task or self._auto_fetch_task.done():
                self._auto_fetch_task = asyncio.create_task(_fetch_messages_loop())
        
        async def _fetch_messages_loop():
            while self._auto_fetch_running:
                try:
                    # Request the next message
                    result = await self.commands.get_msg()
                    
                    # If we got a NO_MORE_MSGS event or an error, stop fetching
                    if result.type == EventType.NO_MORE_MSGS or result.type == EventType.ERROR:
                        logger.debug("No more messages or error occurred, stopping auto-fetch.")
                        break
                    
                    # Small delay to prevent overwhelming the device
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Error fetching messages: {e}")
                    break
        
        # Subscribe to MESSAGES_WAITING events
        self._auto_fetch_subscription = self.subscribe(EventType.MESSAGES_WAITING, _handle_messages_waiting)
        
        # Check for any pending messages immediately
        await self.commands.get_msg()
        
        return self._auto_fetch_subscription
    
    async def stop_auto_message_fetching(self):
        """
        Stop automatically fetching messages when messages_waiting events are received.
        """
        if hasattr(self, '_auto_fetch_subscription') and self._auto_fetch_subscription:
            self.unsubscribe(self._auto_fetch_subscription)
            self._auto_fetch_subscription = None
        
        if hasattr(self, '_auto_fetch_running'):
            self._auto_fetch_running = False
            
        if hasattr(self, '_auto_fetch_task') and self._auto_fetch_task and not self._auto_fetch_task.done():
            self._auto_fetch_task.cancel()
            try:
                await self._auto_fetch_task # type: ignore
            except asyncio.CancelledError:
                pass
            self._auto_fetch_task = None
    
    async def ensure_contacts(self):
        """Ensure contacts are fetched"""
        if not self._contacts:
            await self.commands.get_contacts()
            return True
        return False