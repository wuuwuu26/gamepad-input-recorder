"""Command-line entry points: record and selftest."""

import argparse
import threading
import time

from . import xinput
from .analysis import stats
from .dashboard import DashboardServer
from .models import Sample
from .recorder import ControllerRecorder


class FakeSource:
    """Deterministic fake source for tests and controller-less demos."""

    def __init__(self):
        self.n = 0

    def poll(self) -> Sample:
        self.n += 1
        b = 0x1000 if (self.n // 6) % 2 == 0 else 0
        return Sample(time.perf_counter_ns() // 1000, self.n, b,
                      self.n % 256, (self.n * 2) % 256,
                      0, 0, 0, 0, True, 0)


def _parse(argv=None):
    p = argparse.ArgumentParser(prog="xinput-record",
                                description="Read-only XInput input recorder")
    p.add_argument("--hz", type=int, default=1000)
    p.add_argument("--out", default=None)
    p.add_argument("--user", type=int, default=0)
    p.add_argument("--seconds", type=float, default=None)
    p.add_argument("--change-only", action="store_true")
    p.add_argument("--dashboard", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--source", choices=["xinput", "fake"], default="xinput")
    return p.parse_args(argv)


def _make_source(args):
    return FakeSource() if args.source == "fake" else xinput.create_source(args.user)


def _run_record(args, dashboard=None):
    src = _make_source(args)
    rec = ControllerRecorder(hz=args.hz, user_index=args.user, out=args.out,
                             change_only=args.change_only, source=src)
    if dashboard is not None:
        rec.add_subscriber(dashboard)
    return rec


def record_main(argv=None) -> int:
    args = _parse(argv)
    dashboard = None
    if args.dashboard:
        dashboard = DashboardServer(host=args.host, port=args.port)
        dashboard.start()
    try:
        rec = _run_record(args, dashboard)
        with rec:
            if args.seconds is None:
                print("Recording… press Ctrl-C to stop.")
                try:
                    threading.Event().wait()
                except KeyboardInterrupt:
                    pass
            else:
                time.sleep(args.seconds)
        print(f"Saved {len(rec.session)} samples to {rec.out_path}")
        if dashboard is not None:
            print(f"Dashboard: http://{args.host}:{dashboard.port}/")
        return 0
    finally:
        if dashboard is not None:
            dashboard.stop()
    return 0


def selftest_main(argv=None) -> int:
    args = _parse(argv)
    if args.seconds is None:
        args.seconds = 0.15
    rec = _run_record(args)
    with rec:
        time.sleep(args.seconds)
    st = stats(rec.session)
    print(f"XInput Recorder self-test ({rec.hz} Hz target)")
    print(f"  achieved:     {st['achieved_hz']:.1f} Hz")
    print(f"  mean interval:{st['mean_interval_us']:.3f} us")
    print(f"  max interval: {st['max_interval_us']:.3f} us")
    print(f"  jitter:       {st['jitter_us']:.3f} us")
    print("Note: Python scheduling introduces jitter; values above are measured, not guaranteed.")
    return 0
