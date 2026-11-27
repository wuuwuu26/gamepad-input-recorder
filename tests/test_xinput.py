import ctypes

import pytest

from xinput_recorder import xinput


def test_xinput_state_layout():
    assert ctypes.sizeof(xinput.XINPUT_STATE) == 16


def test_decode_state_maps_all_fields():
    s = xinput.XINPUT_STATE()
    s.dwPacketNumber = 7
    s.Gamepad.wButtons = 0x1000          # A
    s.Gamepad.bLeftTrigger = 10
    s.Gamepad.bRightTrigger = 200
    s.Gamepad.sThumbLX, s.Gamepad.sThumbLY = -32768, 32767
    s.Gamepad.sThumbRX, s.Gamepad.sThumbRY = 12, -9
    out = xinput.decode_state(s, 123456, True)
    assert (out.timestamp_us, out.packet, out.buttons) == (123456, 7, 0x1000)
    assert (out.lt, out.rt) == (10, 200)
    assert (out.ls_x, out.ls_y, out.rs_x, out.rs_y) == (-32768, 32767, 12, -9)
    assert out.connected is True and out.held_us == 0


def test_create_source_rejects_non_windows(monkeypatch):
    monkeypatch.setattr(xinput.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows"):
        xinput.create_source(0)


def test_package_import_is_platform_independent():
    import xinput_recorder
    assert xinput_recorder.__version__
