"""Low-level, read-only binding to the Windows XInput 1.4 API."""

import ctypes
import sys
import time

from .models import Sample

ERROR_DEVICE_NOT_CONNECTED = 1167


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_uint16),
        ("bLeftTrigger", ctypes.c_uint8),
        ("bRightTrigger", ctypes.c_uint8),
        ("sThumbLX", ctypes.c_int16),
        ("sThumbLY", ctypes.c_int16),
        ("sThumbRX", ctypes.c_int16),
        ("sThumbRY", ctypes.c_int16),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_uint32),
        ("Gamepad", XINPUT_GAMEPAD),
    ]


def decode_state(state: XINPUT_STATE, timestamp_us: int, connected: bool) -> Sample:
    """Decode an XINPUT_STATE into a pandas-friendly Sample (pure function)."""
    if not connected:
        return Sample(timestamp_us, 0, 0, 0, 0, 0, 0, 0, 0, False, 0)
    g = state.Gamepad
    return Sample(
        timestamp_us=timestamp_us,
        packet=state.dwPacketNumber,
        buttons=g.wButtons,
        lt=g.bLeftTrigger,
        rt=g.bRightTrigger,
        ls_x=g.sThumbLX,
        ls_y=g.sThumbLY,
        rs_x=g.sThumbRX,
        rs_y=g.sThumbRY,
        connected=True,
        held_us=0,
    )


class XInputSource:
    """Read-only poller for a single XInput user slot."""

    def __init__(self, user_index: int, dll=None):
        if not 0 <= user_index <= 3:
            raise ValueError("user_index must be 0..3")
        self.user_index = user_index
        self._dll = dll
        if self._dll is None:
            self._dll = ctypes.WinDLL("xinput1_4.dll")
        fn = self._dll.XInputGetState
        fn.argtypes = [ctypes.c_uint32, ctypes.POINTER(XINPUT_STATE)]
        fn.restype = ctypes.c_uint32
        self._fn = fn

    def poll(self) -> Sample:
        state = XINPUT_STATE()
        ts = time.perf_counter_ns() // 1000
        rc = self._fn(self.user_index, ctypes.byref(state))
        if rc == 0:
            return decode_state(state, ts, True)
        if rc == ERROR_DEVICE_NOT_CONNECTED:
            return decode_state(state, ts, False)
        # Unexpected error: treat as disconnected to keep the recorder alive.
        return decode_state(state, ts, False)


def create_source(user_index: int) -> XInputSource:
    """Create an XInputSource, failing clearly off Windows."""
    if sys.platform != "win32":
        raise RuntimeError("XInput capture requires Windows")
    return XInputSource(user_index)
