from xinput_recorder.models import Sample, Session
from xinput_recorder.analysis import events, trigger_curves, stick_trajectory, stats


def s(t, buttons=0, lt=0, rt=0):
    return Sample(t, 0, buttons, lt, rt, 0, 0, 0, 0, True, 0)


def test_events_pairs_press_release():
    ses = Session([s(1000, 0x1000), s(2000, 0x1000), s(3000)])
    ev = events(ses)
    assert len(ev) == 1 and ev[0].button == "A"
    assert (ev[0].pressed_us, ev[0].released_us, ev[0].duration_us) == (1000, 3000, 2000)


def test_events_unclosed_press_at_end():
    ev = events(Session([s(1000, 0x1000), s(2000, 0x1000)]))
    assert ev[0].released_us is None and ev[0].duration_us is None
    assert events(Session([])) == []


def test_trigger_curves_peak_and_rise():
    ses = Session([s(0, lt=0), s(1000, lt=10), s(2000, lt=50),
                   s(3000, lt=255), s(4000, lt=20)])
    c = trigger_curves(ses)["lt"]
    assert c.peak == 255 and c.peak_time_us == 3000 and c.rise_us == 2000


def test_stick_trajectory_metrics():
    pts = [Sample(0, 0, 0, 0, 0, 0, 0, 0, 0, True, 0),
           Sample(1000, 0, 0, 0, 0, 3, 4, 0, 0, True, 0),
           Sample(2000, 0, 0, 0, 0, 0, 0, 0, 0, True, 0)]
    tr = stick_trajectory(Session(pts), "left")
    assert (tr.path_length, tr.max_radius, tr.tremor_rms) == (10.0, 5.0, 5.0)


def test_stats_reports_intervals():
    st = stats(Session([s(0), s(1000), s(2000)]))
    assert st["achieved_hz"] == 1000.0
    assert st["mean_interval_us"] == 1000.0 and st["max_interval_us"] == 1000.0
