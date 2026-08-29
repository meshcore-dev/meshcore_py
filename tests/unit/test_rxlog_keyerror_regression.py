import pytest
from Crypto.Cipher import AES
from Crypto.Hash import HMAC, SHA256

from meshcore.meshcore_parser import MeshcorePacketParser


@pytest.mark.asyncio
async def test_duplicate_of_undecryptable_channel_frame_does_not_keyerror():
    """A channel frame first heard without the key is logged with no "message".

    When a duplicate of it arrives after the key becomes known (a channel-table refresh
    landing between two copies of a flooded transmission), parsePacketPayload matches the
    prior, keyless channels_log entry by pkt_hash and copies its fields. That entry has no
    "message"/"msg_hash"/etc., so `logged["message"]` raised KeyError and aborted handle_rx
    for the whole packet — dropping its RX_LOG_DATA. It must not raise.
    """
    parser = MeshcorePacketParser()
    parser.decrypt_channels = True

    channel_secret = b"\x01" * 16
    parser.channels[0] = {
        "channel_idx": 0,
        "channel_name": "test",
        "channel_hash": "ab",
        "channel_secret": channel_secret,
    }

    # A valid GRP_TXT (channel) frame: header (route_type=1, payload_type=5), path_byte=0,
    # then pkt_payload = chan_hash(1) + cipher_mac(2) + AES-ECB ciphertext(16).
    plaintext = b"\x00\x00\x00\x00\x15hello\x00\x00\x00\x00\x00\x00"
    assert len(plaintext) == 16
    encrypted = AES.new(channel_secret, AES.MODE_ECB).encrypt(plaintext)
    h = HMAC.new(channel_secret, digestmod=SHA256)
    h.update(encrypted)
    cipher_mac = h.digest()[:2]
    pkt_payload = bytes([0xAB]) + cipher_mac + encrypted
    payload = bytes([0x15, 0x00]) + pkt_payload

    # Simulate the earlier reception, logged while the channel could not be decrypted:
    # a channels_log entry for this pkt_hash with NO "message"/"msg_hash"/etc.
    pkt_hash = int.from_bytes(SHA256.new(pkt_payload).digest()[0:4], "little", signed=False)
    parser.channels_log.append({"pkt_hash": pkt_hash, "chan_hash": "ab"})

    # The duplicate now decrypts and reaches the "found: copy" branch.
    log_data = await parser.parsePacketPayload(payload, log_data={})

    assert log_data["payload_type"] == 0x05
    # Copied (absent) from the keyless entry instead of raising KeyError.
    assert log_data["message"] is None
