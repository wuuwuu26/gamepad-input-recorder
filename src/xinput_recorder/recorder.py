"""Background recorder: sampling thread, writer thread, hotplug, subscribers."""

import csv
import os
import queue
import tempfile
import threading
import time
from dataclasses import replace

from . import xinput
from .models import CSV_COLUMNS, Sample, Session, load_csv

_SENTINEL = object()
_QUEUE_CAPACITY = 10000
_PUBLISH_HZ = 30


class ControllerRecorder:
    """Record one XInput slot's input stream to CSV, read-only."""

    def __init__(self, hz=1000, user_index=0, out=None, change_only=False,
                 source=None):
        if hz <= 0:
            raise ValueError("hz must be positive")
        self.hz = hz
        self.user_index = user_index
        self.change_only = change_only
        self.source = source if source is not None else xinput.create_source(user_index)
        self._temp_file = out is None
        if out is None:
            fd, path = tempfile.mkstemp(prefix="xinput-", suffix=".csv")
            os.close(fd)
            self.out_path = path
        else:
            self.out_path = str(out)

        self._queue: queue.Queue = queue.Queue(maxsize=_QUEUE_CAPACITY)
        self._subscribers: list = []
        self.dropped_publishes = 0
        self._dropped_lock = threading.Lock()
        self.session: Session | None = None

        self._stop_event = threading.Event()
        self._sampler: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._publish_every = max(1, int(round(hz / _PUBLISH_HZ)))
        self._started = False

    # ---- public control -------------------------------------------------
    def start(self):
        if self._started:
            raise RuntimeError("recorder already started")
        self._started = True
        self._sampler = threading.Thread(target=self._sample_loop, daemon=True,
                                         name="xinput-sampler")
        self._writer = threading.Thread(target=self._write_loop, daemon=True,
                                        name="xinput-writer")
        self._writer.start()
        self._sampler.start()
        return self

    def stop(self):
        if not self._started:
            return
        self._stop_event.set()
        if self._sampler is not None:
            self._sampler.join(timeout=5)
        self._queue.put(_SENTINEL)
        if self._writer is not None:
            self._writer.join(timeout=5)
        self.session = load_csv(self.out_path)

    def add_subscriber(self, sink):
        """Register any object with put_nowait(obj)."""
        self._subscribers.append(sink)

    def publish(self, sample: Sample) -> None:
        """Best-effort, non-blocking push to subscribers."""
        msg = {
            "timestamp_us": sample.timestamp_us,
            "buttons": sample.buttons,
            "lt": sample.lt,
            "rt": sample.rt,
            "ls_x": sample.ls_x,
            "ls_y": sample.ls_y,
            "rs_x": sample.rs_x,
            "rs_y": sample.rs_y,
            "connected": sample.connected,
        }
        for sink in self._subscribers:
            try:
                sink.put_nowait(msg)
            except Exception:
                with self._dropped_lock:
                    self.dropped_publishes += 1

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        if self._temp_file and os.path.exists(self.out_path):
            os.remove(self.out_path)
        return False

    # ---- internal loops -------------------------------------------------
    def _sample_loop(self):
        interval = 1.0 / self.hz
        n = 0
        while not self._stop_event.is_set():
            t0 = time.perf_counter()
            raw = self.source.poll()
            ts = time.perf_counter_ns() // 1000
            sample = replace(raw, timestamp_us=ts)
            try:
                self._queue.put_nowait(sample)
            except queue.Full:
                pass
            if n % self._publish_every == 0:
                self.publish(sample)
            n += 1
            target = t0 + interval
            remaining = target - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining * 0.6)
            while time.perf_counter() < target and not self._stop_event.is_set():
                pass  # fine-grained spin for sub-millisecond precision

    def _write_loop(self):
        with open(self.out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
            writer.writeheader()
            last_key = None
            last_ts = None
            while True:
                item = self._queue.get()
                if item is _SENTINEL:
                    break
                if self.change_only:
                    key = (item.buttons, item.lt, item.rt,
                           item.ls_x, item.ls_y, item.rs_x, item.rs_y,
                           item.connected)
                    if key == last_key:
                        continue
                    held = item.timestamp_us - last_ts if last_ts is not None else 0
                    last_key, last_ts = key, item.timestamp_us
                else:
                    held = item.held_us
                row = {
                    "timestamp_us": item.timestamp_us,
                    "packet": item.packet,
                    "buttons": item.buttons,
                    "lt": item.lt,
                    "rt": item.rt,
                    "ls_x": item.ls_x,
                    "ls_y": item.ls_y,
                    "rs_x": item.rs_x,
                    "rs_y": item.rs_y,
                    "connected": 1 if item.connected else 0,
                    "held_us": held,
                }
                writer.writerow(row)
