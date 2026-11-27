"""Offline analysis helpers for recorded controller sessions."""

import math
from dataclasses import dataclass

from .models import Sample, Session

BUTTON_NAMES = {
    0x0001: "DPAD_UP", 0x0002: "DPAD_DOWN", 0x0004: "DPAD_LEFT",
    0x0008: "DPAD_RIGHT", 0x0010: "START", 0x0020: "BACK",
    0x0040: "L3", 0x0080: "R3", 0x0100: "LB", 0x0200: "RB",
    0x1000: "A", 0x2000: "B", 0x4000: "X", 0x8000: "Y",
}


@dataclass
class ButtonEvent:
    button: str
    pressed_us: int
    released_us: int | None
    duration_us: int | None


@dataclass
class TriggerCurve:
    side: str
    points: list[tuple[int, int]]
    peak: int
    peak_time_us: int | None
    rise_us: int | None


@dataclass
class StickTrajectory:
    side: str
    points: list[tuple[int, int, int]]
    path_length: float
    max_radius: float
    tremor_rms: float


def events(session: Session) -> list[ButtonEvent]:
    """Pair button press/release transitions across samples."""
    result: list[ButtonEvent] = []
    if not session.samples:
        return result
    pressed: dict[int, int] = {}
    first = session.samples[0]
    prev = first.buttons
    for mask, name in BUTTON_NAMES.items():
        if first.buttons & mask:
            pressed[mask] = first.timestamp_us
    for sample in session.samples[1:]:
        for mask, name in BUTTON_NAMES.items():
            is_down = bool(sample.buttons & mask)
            was_down = bool(prev & mask)
            if is_down and not was_down:
                pressed[mask] = sample.timestamp_us
            elif was_down and not is_down and mask in pressed:
                start = pressed.pop(mask)
                result.append(ButtonEvent(name, start, sample.timestamp_us,
                                          sample.timestamp_us - start))
        prev = sample.buttons
    for mask, start in pressed.items():
        result.append(ButtonEvent(BUTTON_NAMES[mask], start, None, None))
    return result


def trigger_curves(session: Session) -> dict[str, TriggerCurve]:
    curves = {}
    for side, attr in (("lt", "lt"), ("rt", "rt")):
        pts = [(s.timestamp_us, getattr(s, attr)) for s in session.samples]
        if not pts:
            curves[side] = TriggerCurve(side, [], 0, None, None)
            continue
        peak = max(v for _, v in pts)
        peak_time = next(t for t, v in pts if v == peak)
        first_pos = next((t for t, v in pts if v > 0), None)
        rise = peak_time - first_pos if first_pos is not None else None
        curves[side] = TriggerCurve(side, pts, peak, peak_time, rise)
    return curves


def stick_trajectory(session: Session, side: str = "left") -> StickTrajectory:
    xattr, yattr = ("ls_x", "ls_y") if side == "left" else ("rs_x", "rs_y")
    pts = [(s.timestamp_us, getattr(s, xattr), getattr(s, yattr))
           for s in session.samples]
    path = 0.0
    for a, b in zip(pts, pts[1:]):
        path += math.hypot(b[1] - a[1], b[2] - a[2])
    max_radius = max((math.hypot(x, y) for _, x, y in pts), default=0.0)
    tremor = 0.0
    for i in range(1, len(pts) - 1):
        mx = (pts[i - 1][1] + pts[i + 1][1]) / 2.0
        my = (pts[i - 1][2] + pts[i + 1][2]) / 2.0
        tremor += math.hypot(pts[i][1] - mx, pts[i][2] - my)
    tremor_rms = tremor / (len(pts) - 2) if len(pts) > 2 else 0.0
    return StickTrajectory(side, pts, path, max_radius, tremor_rms)


def stats(session: Session) -> dict[str, float]:
    ts = [s.timestamp_us for s in session.samples]
    if len(ts) < 2:
        return {"achieved_hz": 0.0, "mean_interval_us": 0.0,
                "max_interval_us": 0.0, "jitter_us": 0.0}
    diffs = [b - a for a, b in zip(ts, ts[1:])]
    mean = sum(diffs) / len(diffs)
    variance = sum((d - mean) ** 2 for d in diffs) / len(diffs)
    return {
        "achieved_hz": 1_000_000.0 / mean if mean else 0.0,
        "mean_interval_us": float(mean),
        "max_interval_us": float(max(diffs)),
        "jitter_us": math.sqrt(variance),
    }
