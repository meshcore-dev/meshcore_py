import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

from ..events import Event, EventDispatcher, EventType
from ..reader import MessageReader

# Define types for destination parameters
DestinationType = Union[bytes, str, Dict[str, Any]]

logger = logging.getLogger("meshcore")


def _validate_destination(dst: DestinationType, prefix_length: int = 6) -> bytes:
    """
    Validates and converts a destination to a bytes object.

    Args:
        dst: The destination, which can be:
            - str: Hex string representation of a public key
            - dict: Contact object with a "public_key" field
        prefix_length: The length of the prefix to use (default: 6 bytes)

    Returns:
        bytes: The destination public key as a bytes object

    Raises:
        ValueError: If dst is invalid or doesn't contain required fields
    """
    if isinstance(dst, bytes):
        # Already bytes, use directly
        return dst[:prefix_length]
    elif isinstance(dst, str):
        # Hex string, convert to bytes
        try:
            return bytes.fromhex(dst)[:prefix_length]
        except ValueError:
            raise ValueError(f"Invalid public key hex string: {dst}")
    elif isinstance(dst, dict):
        # Contact object, extract public_key
        if "public_key" not in dst:
            raise ValueError("Contact object must have a 'public_key' field")
        try:
            return bytes.fromhex(dst["public_key"])[:prefix_length]
        except ValueError:
            raise ValueError(f"Invalid public_key in contact: {dst['public_key']}")
    else:
        raise ValueError(
            f"Destination must be a public key string or contact object, got: {type(dst)}"
        )


class CommandHandlerBase:
    DEFAULT_TIMEOUT = 5.0
    MAX_QUEUE_SIZE = 100

    def __init__(self, default_timeout: Optional[float] = None, max_queue_size: Optional[int] = None):
        self._sender_func: Optional[Callable[[bytes], Coroutine[Any, Any, None]]] = None
        self._reader: Optional[MessageReader] = None
        self.dispatcher: Optional[EventDispatcher] = None
        self.default_timeout = (
            default_timeout if default_timeout is not None else self.DEFAULT_TIMEOUT
        )
        
        max_size = max_queue_size if max_queue_size is not None else self.MAX_QUEUE_SIZE
        self._command_queue = asyncio.Queue(maxsize=max_size)
        self._start_lock = asyncio.Lock()  # Only for start/stop operations
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._is_running = False

    def set_connection(self, connection: Any) -> None:
        async def sender(data: bytes) -> None:
            await connection.send(data)

        self._sender_func = sender

    def set_reader(self, reader: MessageReader) -> None:
        self._reader = reader

    def set_dispatcher(self, dispatcher: EventDispatcher) -> None:
        self.dispatcher = dispatcher

    async def send(
        self,
        data: bytes,
        expected_events: Optional[Union[EventType, List[EventType]]] = None,
        timeout: Optional[float] = None,
    ) -> Event:
        """
        Queue a command for execution and wait for the response.

        Args:
            data: The data to send
            expected_events: EventType or list of EventTypes to wait for
            timeout: Timeout in seconds, or None to use default_timeout

        Returns:
            Event: The full event object that was received in response to the command
        
        Raises:
            RuntimeError: If the command queue is full
        """
        async with self._start_lock:
            if not self._is_running:
                await self._start_queue_processor()
        
        future = asyncio.Future()
        
        try:
            await asyncio.wait_for(
                self._command_queue.put((data, expected_events, timeout, future)),
                timeout=1.0
            )
        except asyncio.TimeoutError:
            future.set_exception(RuntimeError(
                f"Command queue is full ({self._command_queue.maxsize} commands pending)"
            ))
        except Exception as e:
            future.set_exception(e)
        
        return await future

    async def _send_internal(
        self,
        data: bytes,
        expected_events: Optional[Union[EventType, List[EventType]]] = None,
        timeout: Optional[float] = None,
    ) -> Event:
        """
        Internal method that does the actual sending and waiting for events.
        This runs inside the queue processor with lock protection.

        Args:
            data: The data to send
            expected_events: EventType or list of EventTypes to wait for
            timeout: Timeout in seconds, or None to use default_timeout

        Returns:
            Event: The full event object that was received in response to the command
        """
        if not self.dispatcher:
            raise RuntimeError("Dispatcher not set, cannot send commands")

        timeout = timeout if timeout is not None else self.default_timeout

        if self._sender_func:
            logger.debug(
                f"Sending raw data: {data.hex() if isinstance(data, bytes) else data}"
            )
            await self._sender_func(data)

        if expected_events:
            try:
                if not isinstance(expected_events, list):
                    expected_events = [expected_events]

                logger.debug(f"Waiting for events {expected_events}, timeout={timeout}")

                futures = []
                for event_type in expected_events:
                    future = asyncio.create_task(
                        self.dispatcher.wait_for_event(event_type, {}, timeout)
                    )
                    futures.append(future)

                done, pending = await asyncio.wait(
                    futures, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )

                for future in pending:
                    future.cancel()

                for future in done:
                    event = await future
                    if event:
                        return event

                return Event(EventType.ERROR, {"reason": "no_event_received"})
            except asyncio.TimeoutError:
                logger.debug(f"Command timed out {data}")
                return Event(EventType.ERROR, {"reason": "timeout"})
            except Exception as e:
                logger.debug(f"Command error: {e}")
                return Event(EventType.ERROR, {"error": str(e)})
        return Event(EventType.OK, {})

    async def start_queue_processor(self):
        """
        Start the command queue processor.
        This should be called once when the connection is established.
        """
        async with self._start_lock:
            if not self._is_running:
                await self._start_queue_processor()
    
    async def _start_queue_processor(self):
        """Internal method to start the background queue processor."""
        if not self._queue_processor_task or self._queue_processor_task.done():
            self._is_running = True
            self._queue_processor_task = asyncio.create_task(self._process_queue())
            logger.debug("Started command queue processor")

    async def _process_queue(self):
        """Process commands from the queue sequentially."""
        logger.debug("Command queue processor started")
        while self._is_running:
            try:
                item = await self._command_queue.get()
                
                # kill queue signal
                if item is None:
                    logger.debug("Received shutdown sentinel")
                    break
                
                data, expected_events, timeout, future = item
                
                if future.cancelled():
                    continue
                
                try:
                    logger.debug(f"Processing queued command: {data.hex() if isinstance(data, bytes) else data}")
                    result = await self._send_internal(data, expected_events, timeout)
                    
                    if not future.cancelled():
                        future.set_result(result)
                except Exception as e:
                    logger.error(f"Error processing command: {e}")
                    if not future.cancelled():
                        future.set_exception(e)
                
                # Small delay between commands to avoid overwhelming the device
                await asyncio.sleep(0.01)
                    
            except asyncio.CancelledError:
                logger.debug("Queue processor cancelled")
                break
            except Exception as e:
                logger.error(f"Queue processor error: {e}")
                # Continue processing even if there was an error
        
        logger.debug("Command queue processor stopped")

    async def stop_queue_processor(self):
        """Stop the queue processor gracefully."""
        logger.debug("Stopping command queue processor")
        
        if not self._is_running:
            return
            
        self._is_running = False
        
        try:
            # send kill signal and wait for it to be processed
            await asyncio.wait_for(self._command_queue.put(None), timeout=1.0)
        except asyncio.TimeoutError:
            logger.warning("Could not send shutdown sentinel (queue may be full)")
        
        if self._queue_processor_task:
            try:
                await asyncio.wait_for(self._queue_processor_task, timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("Queue processor did not stop gracefully, cancelling")
                self._queue_processor_task.cancel()
                try:
                    await self._queue_processor_task
                except asyncio.CancelledError:
                    pass
            self._queue_processor_task = None
        
        cancelled_count = 0
        while not self._command_queue.empty():
            try:
                item = self._command_queue.get_nowait()
                if item is None:
                    continue
                if isinstance(item, tuple) and len(item) == 4:
                    _, _, _, future = item
                    if not future.cancelled():
                        future.cancel()
                        cancelled_count += 1
            except Exception as e:
                logger.debug(f"Error during cleanup: {e}")
                break
        
        if cancelled_count > 0:
            logger.debug(f"Cancelled {cancelled_count} pending commands")
        
        logger.debug("Command queue processor stopped")
