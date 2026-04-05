"""Tests for LPP parsing to verify current values are handled correctly."""
import json
import pytest
from cayennelpp import LppFrame, LppData


class TestLppCurrentParsing:
    """Tests to verify LPP current values pass through correctly."""

    def test_large_current_value_wraps_signed(self):
        """
        When raw bytes represent a large unsigned value (like 65525),
        values above 32.767 are reinterpreted as signed (negative).
        65.525 - 65.536 = -0.011
        """
        from meshcore.lpp_json_encoder import lpp_json_encoder

        # Channel 2, Type 117 (current), Value 65525 raw = 0xFF 0xF5 (big-endian)
        raw_bytes = bytes([2, 117, 0xFF, 0xF5])
        lppdata = LppData.from_bytes(raw_bytes)

        lpp = json.loads(json.dumps(LppFrame([lppdata]), default=lpp_json_encoder))

        assert len(lpp) == 1
        assert lpp[0]['channel'] == 2
        assert lpp[0]['type'] == 'current'
        assert lpp[0]['value'] == -0.011

    def test_normal_positive_current(self):
        """Normal positive current should work correctly."""
        from meshcore.lpp_json_encoder import lpp_json_encoder

        # Channel 2, Type 117 (current), Value 500 raw = 0x01 0xF4 (big-endian)
        raw_bytes = bytes([2, 117, 0x01, 0xF4])
        lppdata = LppData.from_bytes(raw_bytes)

        lpp = json.loads(json.dumps(LppFrame([lppdata]), default=lpp_json_encoder))

        assert lpp[0]['value'] == 0.5
