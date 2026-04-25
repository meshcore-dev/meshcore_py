import asyncio
import logging
from hashlib import sha256
from typing import Optional

from ..events import Event, EventType
from ..packets import CommandType
from .base import CommandHandlerBase, DestinationType, _validate_destination

logger = logging.getLogger("meshcore")


class DeviceCommands(CommandHandlerBase):
    async def send_appstart(self) -> Event:
        logger.debug("Sending appstart command")
        b1 = bytearray(b"\x01\x03      mccli")
        return await self.send(b1, [EventType.SELF_INFO, EventType.ERROR])

    async def send_device_query(self) -> Event:
        logger.debug("Sending device query command")
        return await self.send(b"\x16\x03", [EventType.DEVICE_INFO, EventType.ERROR])

    async def send_advert(self, flood: bool = False) -> Event:
        logger.debug(f"Sending advertisement command (flood={flood})")
        if flood:
            return await self.send(b"\x07\x01", [EventType.OK, EventType.ERROR])
        else:
            return await self.send(b"\x07", [EventType.OK, EventType.ERROR])

    async def set_name(self, name: str) -> Event:
        logger.debug(f"Setting device name to: {name}")
        return await self.send(
            b"\x08" + name.encode("utf-8"), [EventType.OK, EventType.ERROR]
        )

    async def set_coords(self, lat: float, lon: float) -> Event:
        logger.debug(f"Setting coordinates to: lat={lat}, lon={lon}")
        return await self.send(
            b"\x0e"
            + int(lat * 1e6).to_bytes(4, "little", signed=True)
            + int(lon * 1e6).to_bytes(4, "little", signed=True)
            + int(0).to_bytes(4, "little"),
            [EventType.OK, EventType.ERROR],
        )

    async def reboot(self) -> Event:
        logger.debug("Sending reboot command")
        return await self.send(b"\x13reboot")

    async def get_bat(self) -> Event:
        logger.debug("Getting battery information")
        return await self.send(b"\x14", [EventType.BATTERY, EventType.ERROR])

    async def get_time(self) -> Event:
        logger.debug("Getting device time")
        return await self.send(b"\x05", [EventType.CURRENT_TIME, EventType.ERROR])

    async def set_time(self, val: int) -> Event:
        logger.debug(f"Setting device time to: {val}")
        return await self.send(
            b"\x06" + int(val).to_bytes(4, "little"), [EventType.OK, EventType.ERROR]
        )

    async def set_tx_power(self, val: int) -> Event:
        logger.debug(f"Setting TX power to: {val}")
        return await self.send(
            b"\x0c" + int(val).to_bytes(4, "little"), [EventType.OK, EventType.ERROR]
        )

    async def set_radio(self, freq: float, bw: float, sf: int, cr: int, repeat = None) -> Event:
        logger.debug(f"Setting radio params: freq={freq}, bw={bw}, sf={sf}, cr={cr}, repeat={repeat}")
        data = b"\x0b" 
        data += int(float(freq) * 1000).to_bytes(4, "little")
        data += int(float(bw) * 1000).to_bytes(4, "little")
        data += int(sf).to_bytes(1, "little")
        data += int(cr).to_bytes(1, "little")
        if not repeat is None:
            data += int(repeat).to_bytes(1,"little")
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def set_tuning(self, rx_dly: int, af: int) -> Event:
        logger.debug(f"Setting tuning params: rx_dly={rx_dly}, af={af}")
        return await self.send(
            b"\x15"
            + int(rx_dly).to_bytes(4, "little")
            + int(af).to_bytes(4, "little")
            + int(0).to_bytes(1, "little")
            + int(0).to_bytes(1, "little"),
            [EventType.OK, EventType.ERROR],
        )

    # the old set_other_params function has been replaced in
    # favour of set_other_params_from_infos to be more generic
    # stays here for backward compatibility but does not support
    # multi_acks for instance
    async def set_other_params(
            self,
            manual_add_contacts: bool,
            telemetry_mode_base: int,
            telemetry_mode_loc: int,
            telemetry_mode_env: int,
            advert_loc_policy: int,
        ) -> Event:
        telemetry_mode = (
            (telemetry_mode_base & 0b11)
            | ((telemetry_mode_loc & 0b11) << 2)
            | ((telemetry_mode_env & 0b11) << 4)
        )
        data = (
            b"\x26"
            + manual_add_contacts.to_bytes(1, "little")
            + telemetry_mode.to_bytes(1, "little")
            + advert_loc_policy.to_bytes(1, "little")
        )
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def set_other_params_from_infos(self, infos) -> Event:
        telemetry_mode = (
            (infos["telemetry_mode_base"] & 0b11)
            | ((infos["telemetry_mode_loc"] & 0b11) << 2)
            | ((infos["telemetry_mode_env"] & 0b11) << 4)
        )
        data = (
            b"\x26"
            + infos["manual_add_contacts"].to_bytes(1, "little")
            + telemetry_mode.to_bytes(1, "little")
            + infos["adv_loc_policy"].to_bytes(1, "little")
            + infos["multi_acks"].to_bytes(1, "little")
        )
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def set_telemetry_mode_base(self, telemetry_mode_base: int) -> Event:
        result = await self.send_appstart()
        if result.is_error():
            return result
        infos = result.payload
        infos["telemetry_mode_base"] = telemetry_mode_base
        return await self.set_other_params_from_infos(infos)

    async def set_telemetry_mode_loc(self, telemetry_mode_loc: int) -> Event:
        result = await self.send_appstart()
        if result.is_error():
            return result
        infos = result.payload
        infos["telemetry_mode_loc"] = telemetry_mode_loc
        return await self.set_other_params_from_infos(infos)

    async def set_telemetry_mode_env(self, telemetry_mode_env: int) -> Event:
        result = await self.send_appstart()
        if result.is_error():
            return result
        infos = result.payload
        infos["telemetry_mode_env"] = telemetry_mode_env
        return await self.set_other_params_from_infos(infos)

    async def set_manual_add_contacts(self, manual_add_contacts: bool) -> Event:
        result = await self.send_appstart()
        if result.is_error():
            return result
        infos = result.payload
        infos["manual_add_contacts"] = manual_add_contacts
        return await self.set_other_params_from_infos(infos)

    async def set_advert_loc_policy(self, advert_loc_policy: int) -> Event:
        result = await self.send_appstart()
        if result.is_error():
            return result
        infos = result.payload
        infos["adv_loc_policy"] = advert_loc_policy
        return await self.set_other_params_from_infos(infos)

    async def set_multi_acks(self, multi_acks: int) -> Event:
        result = await self.send_appstart()
        if result.is_error():
            return result
        infos = result.payload
        infos["multi_acks"] = multi_acks
        return await self.set_other_params_from_infos(infos)

    async def set_devicepin(self, pin: int) -> Event:
        logger.debug(f"Setting device PIN to: {pin}")
        return await self.send(
            b"\x25" + int(pin).to_bytes(4, "little"), [EventType.OK, EventType.ERROR]
        )

    async def get_self_telemetry(self) -> Event:
        logger.debug("Getting self telemetry")
        data = b"\x27\x00\x00\x00"
        return await self.send(data, [EventType.TELEMETRY_RESPONSE, EventType.ERROR])

    async def get_custom_vars(self) -> Event:
        logger.debug("Asking for custom vars")
        data = b"\x28"
        return await self.send(data, [EventType.CUSTOM_VARS, EventType.ERROR])

    async def set_custom_var(self, key, value) -> Event:
        logger.debug(f"Setting custom var {key} to {value}")
        data = b"\x29" + key.encode("utf-8") + b":" + value.encode("utf-8")
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def get_channel(self, channel_idx: int) -> Event:
        logger.debug(f"Getting channel info for channel {channel_idx}")
        data = b"\x1f" + channel_idx.to_bytes(1, "little")
        return await self.send(data, [EventType.CHANNEL_INFO, EventType.ERROR])

    async def set_channel(
        self, channel_idx: int, channel_name: str, channel_secret: bytes = None
    ) -> Event:
        logger.debug(f"Setting channel {channel_idx}: name={channel_name}")

        # Pad channel name to 32 bytes
        name_bytes = channel_name.encode("utf-8")[:32]
        name_bytes = name_bytes.ljust(32, b"\x00")

        if channel_name.startswith("#") or channel_secret is None: # auto name => key calculated from hash
            channel_secret = sha256(channel_name.encode("utf-8")).digest()[0:16]

        # Ensure channel secret is exactly 16 bytes
        if len(channel_secret) != 16:
            raise ValueError("Channel secret must be exactly 16 bytes")

        data = b"\x20" + channel_idx.to_bytes(1, "little") + name_bytes + channel_secret
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def export_private_key(self) -> Event:
        logger.debug("Requesting private key export")
        return await self.send(b"\x17", [EventType.PRIVATE_KEY, EventType.DISABLED, EventType.ERROR])

    async def import_private_key(self, key) -> Event:
        logger.debug("Requesting private key import")
        data = b"\x18" + key
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def sign_start(self) -> Event:
        logger.debug("Starting signing session on device")
        return await self.send(b"\x21", [EventType.SIGN_START, EventType.ERROR])

    async def sign_data(self, chunk: bytes) -> Event:
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError("chunk must be bytes-like")
        logger.debug(f"Sending signing data chunk ({len(chunk)} bytes)")
        data = b"\x22" + bytes(chunk)
        result = await self.send(data, [EventType.OK, EventType.ERROR], timeout=5.0)
        
        # If we got an error (not just timeout), return it immediately
        if result.type == EventType.ERROR:
            # If it's a timeout/no_event, log a warning but continue - the data may have been received
            if result.payload.get("reason") in ("timeout", "no_event_received"):
                logger.warning(
                    f"sign_data OK response not received (timeout), but continuing - "
                    f"data may have been processed by device"
                )
                return Event(EventType.OK, {})
            # For actual errors (bad state, table full, etc.), return the error
            return result
        
        return result

    async def sign_finish(self, timeout: Optional[float] = None, data_size: int = 0) -> Event:
        logger.debug("Finalizing signing session on device")
        if timeout is None:
            base_timeout = max(self.default_timeout * 3, 15.0)
            size_bonus = min(data_size / 2048.0, 5.0)
            timeout = base_timeout + size_bonus
        logger.debug(f"sign_finish using timeout={timeout:.1f} seconds (data_size={data_size} bytes)")
        return await self.send(b"\x23", [EventType.SIGNATURE, EventType.ERROR], timeout=timeout)

    async def sign(self, data: bytes, chunk_size: int = 120, timeout: Optional[float] = None) -> Event:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes-like")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")

        start_evt = await self.sign_start()
        if start_evt.type == EventType.ERROR:
            return start_evt

        max_len = start_evt.payload.get("max_length", 0)
        if max_len and len(data) > max_len:
            return Event(EventType.ERROR, {"reason": "data_too_large", "max_length": max_len, "len": len(data)})

        for idx in range(0, len(data), chunk_size):
            chunk = data[idx : idx + chunk_size]
            chunk_num = (idx // chunk_size) + 1
            total_chunks = (len(data) + chunk_size - 1) // chunk_size
            logger.debug(f"Sending chunk {chunk_num}/{total_chunks} ({len(chunk)} bytes)")
            evt = await self.sign_data(chunk)
            if evt.type == EventType.ERROR:
                logger.error(f"Error sending chunk {chunk_num}/{total_chunks}: {evt.payload}")
                return evt
            logger.debug(f"Chunk {chunk_num}/{total_chunks} sent successfully")

        return await self.sign_finish(timeout=timeout, data_size=len(data))

    async def has_connection(self) -> Event:
        """N09: Check if the device has an active connection (CMD 28).

        Returns:
            Event with a 1-byte response indicating connection status,
            or ERROR.
        """
        logger.debug("Checking device connection status")
        return await self.send(b"\x1c", [EventType.OK, EventType.ERROR])

    async def get_tuning(self) -> Event:
        """N03/N09: Request current tuning parameters (CMD_GET_TUNING_PARAMS = 43).

        Firmware responds with RESP_CODE_TUNING_PARAMS (23): 9 bytes containing
        rx_delay (4 bytes LE) and airtime_factor (4 bytes LE).

        Returns:
            Event of type TUNING_PARAMS with rx_delay and airtime_factor,
            or ERROR.
        """
        logger.debug("Getting tuning parameters")
        return await self.send(b"\x2b", [EventType.TUNING_PARAMS, EventType.ERROR])

    async def request_factory_reset(self) -> str:
        """N09: Request a factory reset token (step 1 of 2).

        This method returns a confirmation token string. Pass it to
        ``confirm_factory_reset(token)`` to actually execute the reset.
        The two-step pattern is a Python-side safety measure; the firmware
        itself has no token verification.

        Returns:
            A confirmation token string to pass to confirm_factory_reset().
        """
        import secrets
        token = secrets.token_hex(8)
        logger.warning(
            "Factory reset requested. Call confirm_factory_reset('%s') to proceed. "
            "This will ERASE ALL DATA on the device.", token
        )
        # Store the token on the instance for validation
        self._factory_reset_token = token
        return token

    async def confirm_factory_reset(self, token: str) -> Event:
        """N09: Execute factory reset after token confirmation (step 2 of 2).

        Args:
            token: The token returned by request_factory_reset().

        Returns:
            Event with OK or ERROR.

        Raises:
            ValueError: If the token does not match.
        """
        expected = getattr(self, "_factory_reset_token", None)
        if expected is None or token != expected:
            raise ValueError(
                "Invalid or expired factory reset token. "
                "Call request_factory_reset() first."
            )
        self._factory_reset_token = None  # Consume the token
        logger.warning("Executing factory reset — all device data will be erased")
        return await self.send(b"\x33", [EventType.OK, EventType.ERROR])

    async def get_stats_core(self) -> Event:
        logger.debug("Getting core statistics")
        # R04: Use CommandType enum instead of literal bytes
        cmd = bytes([CommandType.GET_STATS.value, 0x00])  # GET_STATS + STATS_TYPE_CORE
        return await self.send(cmd, [EventType.STATS_CORE, EventType.ERROR])

    async def get_stats_radio(self) -> Event:
        logger.debug("Getting radio statistics")
        # R04: Use CommandType enum instead of literal bytes
        cmd = bytes([CommandType.GET_STATS.value, 0x01])  # GET_STATS + STATS_TYPE_RADIO
        return await self.send(cmd, [EventType.STATS_RADIO, EventType.ERROR])

    async def get_stats_packets(self) -> Event:
        logger.debug("Getting packet statistics")
        # R04: Use CommandType enum instead of literal bytes
        cmd = bytes([CommandType.GET_STATS.value, 0x02])  # GET_STATS + STATS_TYPE_PACKETS
        return await self.send(cmd, [EventType.STATS_PACKETS, EventType.ERROR])

    async def get_allowed_repeat_freq(self) -> Event:
        logger.debug("Getting allowed repeat freqs")
        return await self.send(b"\x3c", [EventType.ALLOWED_REPEAT_FREQ, EventType.ERROR])

    async def set_path_hash_mode(self, mode: int) -> Event:
        logger.debug(f"Setting path mode to {mode}")
        data = b"\x3d\0" + mode.to_bytes(1, "little")
        return await self.send(data, [EventType.OK, EventType.ERROR])

    async def get_path_hash_mode(self) -> int:
        res = await self.send_device_query()
        if not res is None and res.type != EventType.ERROR:
            if "path_hash_mode" in res.payload:
                return res.payload["path_hash_mode"]
        return 0
