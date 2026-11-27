"""Data model for a single sampled controller state."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    timestamp_us: int
    packet: int
    buttons: int
    lt: int
    rt: int
    ls_x: int
    ls_y: int
    rs_x: int
    rs_y: int
    connected: bool
    held_us: int = 0


CSV_COLUMNS: tuple[str, ...] = (
    "timestamp_us",
    "packet",
    "buttons",
    "lt",
    "rt",
    "ls_x",
    "ls_y",
    "rs_x",
    "rs_y",
    "connected",
    "held_us",
)
