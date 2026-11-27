"""Data model for a single sampled controller state."""

import csv
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


class Session:
    """An immutable-in-practice collection of samples from one recording."""

    def __init__(self, samples: list[Sample]):
        self.samples = list(samples)

    def __len__(self) -> int:
        return len(self.samples)

    def to_csv(self, path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for sample in self.samples:
                row = {col: getattr(sample, col) for col in CSV_COLUMNS}
                row["connected"] = 1 if sample.connected else 0
                writer.writerow(row)


def load_csv(path) -> Session:
    samples: list[Sample] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ints = {
                col: int(row[col])
                for col in CSV_COLUMNS
                if col not in ("connected", "held_us") and row.get(col) not in (None, "")
            }
            ints["connected"] = row["connected"] == "1"
            ints["held_us"] = int(row["held_us"]) if row.get("held_us") else 0
            samples.append(Sample(**ints))
    return Session(samples)
