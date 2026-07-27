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


# Size of the server-side reply_path buffer (uint8_t reply_path[64] in
# simple_repeater/MyMesh.h). It is memcpy'd into without a length check.
MAX_REPLY_PATH_BYTES = 64
# reply_path_len is the low 6 bits of the header byte.
MAX_REPLY_PATH_HOPS = 63


def encode_reply_path(out_path_len: int, out_path_hex: str, out_path_hash_mode: int) -> bytes:
    """Encode the reply path a server should use when answering us.

    The leading byte packs two fields, which the server unpacks as:

        reply_path_len       = byte & 63
        reply_path_hash_size = (byte >> 6) + 1

    so the hash mode has to travel in the top two bits. Omitting it makes the
    server read a hash size of 1 regardless of the real mode, take the wrong
    number of bytes per hop, and route its reply to hops that do not exist.

    The path itself is reversed by *hop*, not by byte: a return path visits the
    same hops in the opposite order, and each hop's multi-byte hash must stay
    intact. (For single-byte hops the two are indistinguishable, which is most
    of why this went unnoticed - mode 0 is the default.)
    """
    hash_mode = max(out_path_hash_mode, 0)      # -1 means "flood", i.e. no path
    if hash_mode > 2:
        # The server computes hash_size = mode + 1, and Packet::isValidPathLen
        # rejects 4-byte hops outright, so such a path is unusable on the wire.
        logger.warning(
            f"Unsupported out_path_hash_mode {out_path_hash_mode}; "
            "requesting a zero-hop reply path instead"
        )
        return b"\x00"
    hash_size = hash_mode + 1
    # Saturate rather than mask: `& 63` would silently wrap a 64-hop path to
    # zero hops, i.e. a zero-hop reply for a distant node.
    hops = min(max(out_path_len, 0), MAX_REPLY_PATH_HOPS)

    raw = bytes.fromhex(out_path_hex or "")
    # Never read past what the contact actually carries; a truncated or padded
    # field would otherwise yield short trailing hops.
    hops = min(hops, len(raw) // hash_size)
    # The server memcpys into a fixed 64-byte reply_path with no bounds check
    # (simple_repeater/MyMesh.cpp), so never describe more than fits.
    max_hops = min(MAX_REPLY_PATH_HOPS, MAX_REPLY_PATH_BYTES // hash_size)
    if hops > max_hops:
        logger.warning(
            f"Reply path of {hops} hops x {hash_size}B exceeds the "
            f"{MAX_REPLY_PATH_BYTES}B the server can hold; truncating to {max_hops}"
        )
        hops = max_hops

    path = b"".join(
        raw[i * hash_size:(i + 1) * hash_size] for i in range(hops - 1, -1, -1)
    )
    return bytes([hops | (hash_mode << 6)]) + path


class CommandHandlerBase:
    """Base class for command handlers.

    .. note::
        The internal ``asyncio.Lock`` is created lazily on first access
        so that it binds to the correct running event loop (required for
        Python 3.9/3.10 compatibility).
    """

    DEFAULT_TIMEOUT = 15.0

    def __init__(self, default_timeout: Optional[float] = None):
        self._sender_func: Optional[Callable[[bytes], Coroutine[Any, Any, None]]] = None
        self._reader: Optional[MessageReader] = None
        self.dispatcher: Optional[EventDispatcher] = None
        self.__mesh_request_lock: Optional[asyncio.Lock] = None
        self.default_timeout = (
            default_timeout if default_timeout is not None else self.DEFAULT_TIMEOUT
        )

    @property
    def _mesh_request_lock(self) -> asyncio.Lock:
        """Lazy-init lock so it binds to the running loop, not import-time."""
        if self.__mesh_request_lock is None:
            self.__mesh_request_lock = asyncio.Lock()
        return self.__mesh_request_lock

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
        """Wait for the first of *expected_events* to arrive.

        Returns the first matched ``Event``.  When ``EventType.ERROR`` is
        among the expected types, the caller **must** check
        ``result.is_error()`` before accessing command-specific payload
        keys — an ERROR payload is ``{"reason": "..."}`` and will
        ``KeyError`` on any other key.
        """
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
            Event: The full event object that was received in response to
            the command.

        Important:
            When ``EventType.ERROR`` is included in *expected_events*, the
            returned event may be an error response.  Callers **must**
            check ``result.is_error()`` before accessing command-specific
            payload keys to avoid ``KeyError``.
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

            loop = asyncio.get_running_loop()
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

        # Pre-register a placeholder binary request before send() to close the race
        # window where a BINARY_RESPONSE could arrive between send() returning and
        # registration. The placeholder tag is patched to the real tag once MSG_SENT
        # returns. If send() fails, the placeholder is cleaned up.
        placeholder_tag = None
        if self._reader is not None and request_type is not None:
            placeholder_tag = f"_pending_{id(data)}"
            actual_timeout = timeout if timeout is not None and timeout > 0 else self.default_timeout
            actual_timeout = min_timeout if actual_timeout < min_timeout else actual_timeout
            self._reader.register_binary_request(pubkey_prefix.hex(), placeholder_tag, request_type, actual_timeout, context=context)

        result = await self.send(data, [EventType.MSG_SENT, EventType.ERROR])

        # Patch the placeholder tag with the real tag from MSG_SENT, or clean up on failure
        if placeholder_tag is not None and self._reader is not None:
            # Remove the placeholder entry
            self._reader.pending_binary_requests.pop(placeholder_tag, None)
            if (result.type == EventType.MSG_SENT and
                    request_type is not None):
                exp_tag = result.payload["expected_ack"].hex()
                # Use suggested_timeout from the result if available
                actual_timeout = timeout if timeout is not None and timeout > 0 else result.payload.get("suggested_timeout", 4000) / 800.0
                actual_timeout = min_timeout if actual_timeout < min_timeout else actual_timeout
                # Register with the real tag
                self._reader.register_binary_request(pubkey_prefix.hex(), exp_tag, request_type, actual_timeout, context=context)

        return result

    async def send_anon_req(self, dst: DestinationType, request_type: AnonReqType, data: Optional[bytes] = None, context={}, timeout=None, min_timeout=0) -> Event:
        """Send an anonymous request to *dst*.

        *dst* need not be a known contact. When it is, that contact's out path is
        used as the reply path; otherwise a zero-hop direct reply path is
        requested (see the comment below).

        Note: *data* is currently ignored -- the request body is the reply path,
        which is derived here rather than supplied by the caller.
        """
        dst_bytes = _validate_destination(dst, prefix_length=32)
        pubkey_prefix = _validate_destination(dst, prefix_length=6)
        logger.debug(f"Anon Binary request to {dst_bytes.hex()}")

        # The contact is consulted only to build the reply path appended to the
        # request; it is not required to send one. Companion firmware from
        # FIRMWARE_VER_CODE 13 synthesises a transient anon contact for an unknown
        # pubkey (out_path_len = 0, zero-hop direct), so an unknown destination is
        # reachable as long as we ask it to reply zero-hop. Refusing here would
        # block probing any node the client has not already added - for instance
        # asking a freshly discovered neighbour for its regions.
        contact = self._get_contact_by_prefix(dst_bytes.hex())

        zero_hop = False
        if contact is None:
            logger.debug("No contact found, requesting a zero-hop direct reply path")
            out_path_len = 0
            reply_path = encode_reply_path(0, "", 0)
        else:
            if contact["out_path_len"] == -1:
                logger.info("No path set trying zero hop")
                zero_hop = True
                path_res = await self.change_contact_path(contact, "")
                if path_res is not None and path_res.type == EventType.ERROR:
                    # The device still has this contact as flood, so sendAnonReq
                    # will flood the request -- and the server gates REGIONS,
                    # OWNER and BASIC behind isRouteDirect(), silently dropping
                    # it. Better to fail here than to wait out a full timeout
                    # for a reply that cannot come.
                    logger.error("Could not set zero-hop path, aborting anon request")
                    return Event(EventType.ERROR, {"reason": "path_reset_failed"})
            # update_contact() normally reflects the change back onto the dict, so
            # out_path_len reads 0 here. Clamp anyway: if that call failed (e.g. the
            # device query inside it errored) the dict is still -1, and the unsigned
            # to_bytes below would raise OverflowError -- which would skip the
            # reset_path at the end of this method and leave the contact pinned to
            # zero-hop on the device. Zero is the right value to send regardless,
            # since zero-hop is exactly what we just asked for.
            out_path_len = max(contact["out_path_len"], 0)
            reply_path = encode_reply_path(
                out_path_len,
                contact["out_path"],
                contact.get("out_path_hash_mode", 0),
            )

        data = b"\x39" + dst_bytes + request_type.value.to_bytes(1, "little", signed=False) + reply_path

        result = await self.send(data, [EventType.MSG_SENT, EventType.ERROR])

        # Register the request with the reader if we have both reader and request_type
        if (result.type == EventType.MSG_SENT and
            self._reader is not None and
            request_type is not None):

            exp_tag = result.payload["expected_ack"].hex()
            # Use provided timeout or fallback to suggested timeout (with 5s default)
            emitted_hops = reply_path[0] & 63   # what actually went on the wire
            result.payload["suggested_timeout"] = result.payload.get("suggested_timeout", 4000) * (emitted_hops + 1) # update timeout from path_len
            actual_timeout = timeout if timeout is not None and timeout > 0 else result.payload.get("suggested_timeout", 4000) / 800.0
            actual_timeout = min_timeout if actual_timeout < min_timeout else actual_timeout
            self._reader.register_binary_request(pubkey_prefix.hex(), exp_tag, request_type, actual_timeout, context=context, is_anon=True)

        if zero_hop:
            await self.reset_path(contact)

        return result
