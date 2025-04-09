from enum import Enum
import logging
from typing import Any, Dict, Optional, Callable, List, Union
import asyncio
from dataclasses import dataclass

logger = logging.getLogger("meshcore")

# Public event types for users to subscribe to 
class EventType(Enum):
    CONTACTS = "contacts"
    SELF_INFO = "self_info"
    CONTACT_MSG_RECV = "contact_message"
    CHANNEL_MSG_RECV = "channel_message"
    CURRENT_TIME = "time_update"
    NO_MORE_MSGS = "no_more_messages"
    CONTACT_SHARE = "contact_share"
    BATTERY = "battery_info"
    DEVICE_INFO = "device_info"
    CLI_RESPONSE = "cli_response"
    MSG_SENT = "message_sent"
    
    # Push notifications
    ADVERTISEMENT = "advertisement"
    PATH_UPDATE = "path_update"
    ACK = "acknowledgement"
    MESSAGES_WAITING = "messages_waiting"
    RAW_DATA = "raw_data"
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed" 
    STATUS_RESPONSE = "status_response"
    LOG_DATA = "log_data"
    
    # Command response types
    OK = "command_ok"
    ERROR = "command_error"


@dataclass
class Event:
    type: EventType
    payload: Any
    attributes: Dict[str, Any] = {}
    
    def __post_init__(self):
        if self.attributes is None:
            self.attributes = {}


class Subscription:
    def __init__(self, dispatcher, event_type, callback):
        self.dispatcher = dispatcher
        self.event_type = event_type
        self.callback = callback
        
    def unsubscribe(self):
        self.dispatcher._remove_subscription(self)


class EventDispatcher:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.subscriptions: List[Subscription] = []
        self.running = False
        self._task = None
        
    def subscribe(self, event_type: Union[EventType, None], callback: Callable[[Event], Union[None, asyncio.Future]]) -> Subscription:
        subscription = Subscription(self, event_type, callback)
        self.subscriptions.append(subscription)
        return subscription
        
    def _remove_subscription(self, subscription: Subscription):
        if subscription in self.subscriptions:
            self.subscriptions.remove(subscription)
                
    async def dispatch(self, event: Event):
        await self.queue.put(event)
        
    async def _process_events(self):
        while self.running:
            event = await self.queue.get()
            logger.debug(f"Dispatching event: {event.type}, {event.payload}")
            for subscription in self.subscriptions.copy():
                if subscription.event_type is None or subscription.event_type == event.type:
                    try:
                        result = subscription.callback(event)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        print(f"Error in event handler: {e}")
                        
            self.queue.task_done()
            
    async def start(self):
        if not self.running:
            self.running = True
            self._task = asyncio.create_task(self._process_events())
            
    async def stop(self):
        if self.running:
            self.running = False
            if self._task:
                await self.queue.join()
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
                
    async def wait_for_event(self, event_type: EventType, timeout: float | None = None) -> Optional[Event]:
        future = asyncio.Future()
        
        def event_handler(event: Event):
            if not future.done():
                future.set_result(event)
        
        subscription = self.subscribe(event_type, event_handler)
        
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            subscription.unsubscribe()