import asyncio
import logging
import random
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

from meshcore.packets import BinaryReqType, AnonReqType

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
        if len(dst)<prefix_length:
            raise ValueError(f"Invalid prefix len, expecting {prefix_length}, got {len(dst)}")
        return dst[:prefix_length]
    elif isinstance(dst, str):
        # Hex string, convert to bytes
        try:
            if len(dst)<2*prefix_length:
                raise ValueError(f"Invalid prefix len, expecting {prefix_length}, got {len(dst)/2}")
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

    def __init__(self, default_timeout: Optional[float] = None):
        self._sender_func: Optional[Callable[[bytes], Coroutine[Any, Any, None]]] = None
        self._reader: Optional[MessageReader] = None
        self.dispatcher: Optional[EventDispatcher] = None
        self.default_timeout = (
            default_timeout if default_timeout is not None else self.DEFAULT_TIMEOUT
        )

    def set_connection(self, connection: Any) -> None:
        async def sender(data: bytes) -> None:
            await connection.send(data)

        self._sender_func = sender

    def set_reader(self, reader: MessageReader) -> None:
        self._reader = reader

    def set_dispatcher(self, dispatcher: EventDispatcher) -> None:
        self.dispatcher = dispatcher

    def set_contact_getter_by_prefix(self, func: Callable[[str], Optional[Dict[str,Any]]]
        )-> None:
        self._get_contact_by_prefix = func

    async def wait_for_events(
        self,
        expected_events: Optional[Union[EventType, List[EventType]]] = None,
        timeout: Optional[float] = None,
    ) -> Event:
        try:
            # Convert single event to list if needed
            if not isinstance(expected_events, list):
                expected_events = [expected_events]

            logger.debug(f"Waiting for events {expected_events}, timeout={timeout}")

            # Create futures for all expected events
            futures = []
            for event_type in expected_events:
                future = asyncio.create_task(
                    self.dispatcher.wait_for_event(event_type, {}, timeout)
                )
                futures.append(future)

            # Wait for the first event to complete or all to timeout
            done, pending = await asyncio.wait(
                futures, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel all pending futures
            for future in pending:
                future.cancel()

            # Check if any future completed successfully
            for future in done:
                event = await future
                if event:
                    return event

            # Create an error event when no event is received
            return Event(EventType.ERROR, {"reason": "no_event_received"})
        except asyncio.TimeoutError:
            logger.debug(f"Command timed out waiting for events {expected_events}")
            return Event(EventType.ERROR, {"reason": "timeout"})
        except Exception as e:
            logger.debug(f"Command error: {e}")
            return Event(EventType.ERROR, {"error": str(e)})

        return Event(EventType.ERROR, {})


    async def send(
        self,
        data: bytes,
        expected_events: Optional[Union[EventType, List[EventType]]] = None,
        timeout: Optional[float] = None,
    ) -> Event:
        """
        Send a command and wait for expected event responses.

        Uses subscribe-before-send to avoid race conditions where the
        device responds before the event listener is registered.  This
        mirrors the pattern used by the companion apps (JS/iOS/Android).

        Args:
            data: The data to send
            expected_events: EventType or list of EventTypes to wait for
            timeout: Timeout in seconds, or None to use default_timeout

        Returns:
            Event: The full event object that was received in response to the command
        """
        if not self.dispatcher:
            raise RuntimeError("Dispatcher not set, cannot send commands")

        # Use the provided timeout or fall back to default_timeout
        timeout = timeout if timeout is not None else self.default_timeout

        if expected_events:
            # ── Subscribe BEFORE sending ──────────────────────────
            # Register event listeners first so we never miss a fast
            # device response, even on a busy mesh network where the
            # asyncio event loop processes RX_LOG events in between.
            if not isinstance(expected_events, list):
                expected_events = [expected_events]

            futures: List[asyncio.Future] = []
            subscriptions = []

            loop = asyncio.get_event_loop()
            for event_type in expected_events:
                future = loop.create_future()

                def _handler(event: Event, f: asyncio.Future = future) -> None:
                    if not f.done():
                        f.set_result(event)

                sub = self.dispatcher.subscribe(event_type, _handler)
                futures.append(future)
                subscriptions.append(sub)

            try:
                # ── Now send the command ──────────────────────────
                if self._sender_func:
                    logger.debug(
                        f"Sending raw data: "
                        f"{data.hex() if isinstance(data, bytes) else data}"
                    )
                    await self._sender_func(data)

                # ── Wait for the first matching event ─────────────
                done, pending = await asyncio.wait(
                    futures,
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Cancel futures we no longer need
                for f in pending:
                    f.cancel()

                # Return the first successfully received event
                for f in done:
                    try:
                        event = f.result()
                        if event:
                            return event
                    except (asyncio.CancelledError, asyncio.InvalidStateError):
                        pass

                return Event(EventType.ERROR, {"reason": "no_event_received"})

            except asyncio.TimeoutError:
                logger.debug(
                    f"Command timed out waiting for events {expected_events}"
                )
                return Event(EventType.ERROR, {"reason": "timeout"})
            except Exception as e:
                logger.debug(f"Command error: {e}")
                return Event(EventType.ERROR, {"error": str(e)})
            finally:
                # Always clean up subscriptions
                for sub in subscriptions:
                    sub.unsubscribe()

        else:
            # Fire-and-forget commands (no expected response)
            if self._sender_func:
                logger.debug(
                    f"Sending raw data: "
                    f"{data.hex() if isinstance(data, bytes) else data}"
                )
                await self._sender_func(data)
            return Event(EventType.OK, {})

    # attached at base because its a common method
    async def send_binary_req(self, dst: DestinationType, request_type: BinaryReqType, data: Optional[bytes] = None, context={}, timeout=None, min_timeout=0) -> Event:
        dst_bytes = _validate_destination(dst, prefix_length=32)
        pubkey_prefix = _validate_destination(dst, prefix_length=6)
        logger.debug(f"Binary request to {dst_bytes.hex()}")
        data = b"\x32" + dst_bytes + request_type.value.to_bytes(1, "little", signed=False) + (data if data else b"")

        result = await self.send(data, [EventType.MSG_SENT, EventType.ERROR])
        
        # Register the request with the reader if we have both reader and request_type
        if (result.type == EventType.MSG_SENT and 
            self._reader is not None and 
            request_type is not None):
            
            exp_tag = result.payload["expected_ack"].hex()
            # Use provided timeout or fallback to suggested timeout (with 5s default)
            actual_timeout = timeout if timeout is not None and timeout > 0 else result.payload.get("suggested_timeout", 4000) / 800.0
            actual_timeout = min_timeout if actual_timeout < min_timeout else actual_timeout
            self._reader.register_binary_request(pubkey_prefix.hex(), exp_tag, request_type, actual_timeout, context=context)

        return result

    async def send_anon_req(self, dst: DestinationType, request_type: AnonReqType, data: Optional[bytes] = None, context={}, timeout=None, min_timeout=0) -> Event:
        dst_bytes = _validate_destination(dst, prefix_length=32)
        pubkey_prefix = _validate_destination(dst, prefix_length=6)
        logger.debug(f"Anon Binary request to {dst_bytes.hex()}")

        contact = self._get_contact_by_prefix(dst_bytes.hex()) # need a contact for return path
        if contact is None:
            logger.error("No contact found")

        zero_hop = False
        if contact["out_path_len"] == -1: 
            logger.info("No path set trying zero hop")
            zero_hop = True
            await self.change_contact_path(contact, "")

        data = contact["out_path_len"].to_bytes(1, "little") + bytes.fromhex(contact["out_path"])[::-1]
        data = b"\x39" + dst_bytes + request_type.value.to_bytes(1, "little", signed=False) + (data if data else b"")

        result = await self.send(data, [EventType.MSG_SENT, EventType.ERROR])
        
        # Register the request with the reader if we have both reader and request_type
        if (result.type == EventType.MSG_SENT and 
            self._reader is not None and 
            request_type is not None):
            
            exp_tag = result.payload["expected_ack"].hex()
            # Use provided timeout or fallback to suggested timeout (with 5s default)
            result.payload["suggested_timeout"] = result.payload.get("suggested_timeout", 4000) * (contact["out_path_len"] + 1) # update timeout from path_len
            actual_timeout = timeout if timeout is not None and timeout > 0 else result.payload.get("suggested_timeout", 4000) / 800.0
            actual_timeout = min_timeout if actual_timeout < min_timeout else actual_timeout
            self._reader.register_binary_request(pubkey_prefix.hex(), exp_tag, request_type, actual_timeout, context=context, is_anon=True)

        if zero_hop:
            await self.reset_path(contact)

        return result
