import queue
import time

from xinput_recorder.models import Sample
from xinput_recorder.recorder import ControllerRecorder


class FakeSource:
    def __init__(self, frames=None):
        self.frames, self.i = frames, 0

    def poll(self):
        if self.frames is None:
            s = Sample(time.perf_counter_ns() // 1000, self.i, 0x1000,
                       0, 0, 0, 0, 0, 0, True, 0)
        else:
            s = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return s


def test_records_samples_from_fake_source(tmp_path):
    p = tmp_path / "r.csv"
    with ControllerRecorder(hz=200, source=FakeSource(), out=str(p)) as rec:
        time.sleep(0.25)
    samples = rec.session.samples
    assert 30 <= len(samples) <= 60          # 目标 50，CI 上放宽
    ts = [s.timestamp_us for s in samples]
    assert all(b > a for a, b in zip(ts, ts[1:]))
    assert p.exists()


def test_no_controller_does_not_crash(tmp_path):
    off = Sample(0, 0, 0, 0, 0, 0, 0, 0, 0, False, 0)
    with ControllerRecorder(hz=200, source=FakeSource([off]),
                            out=str(tmp_path / "n.csv")) as rec:
        time.sleep(0.1)
    assert rec.session.samples and all(not s.connected for s in rec.session.samples)


def test_hotplug_mid_session_marked(tmp_path):
    on = Sample(0, 0, 0, 0, 0, 0, 0, 0, 0, True, 0)
    off = Sample(0, 0, 0, 0, 0, 0, 0, 0, 0, False, 0)
    src = FakeSource([on] * 5 + [off] * 5 + [on] * 5)
    with ControllerRecorder(hz=200, source=src, out=str(tmp_path / "h.csv")) as rec:
        time.sleep(0.3)
    flags = [s.connected for s in rec.session.samples]
    assert True in flags and False in flags and flags.index(True) < flags.index(False)


def test_publish_never_blocks(tmp_path):
    q = queue.Queue(maxsize=1)
    q.put("stale")
    rec = ControllerRecorder(hz=200, source=FakeSource(), out=str(tmp_path / "p.csv"))
    rec.add_subscriber(q)
    t0 = time.monotonic()
    rec.publish(Sample(0, 0, 0, 0, 0, 0, 0, 0, 0, True, 0))
    assert time.monotonic() - t0 < 0.05
    assert rec.dropped_publishes == 1


def test_change_only_writes_fewer_rows(tmp_path):
    a = Sample(0, 0, 0x1000, 0, 0, 0, 0, 0, 0, True, 0)
    b = Sample(0, 0, 0x2000, 0, 0, 0, 0, 0, 0, True, 0)
    src = FakeSource([a] * 10 + [b] * 10)
    p = tmp_path / "c.csv"
    with ControllerRecorder(hz=200, source=src, out=str(p), change_only=True) as rec:
        time.sleep(0.3)
    assert 0 < len(rec.session.samples) < 20
