from xinput_recorder.models import Sample, Session, load_csv


def test_csv_roundtrip(tmp_path):
    samples = [Sample(1000, 1, 0x1000, 0, 0, 0, 0, 0, 0, True, 0),
               Sample(2000, 2, 0x1000, 5, 9, 1, -1, 2, -2, True, 1000)]
    p = tmp_path / "s.csv"
    Session(samples).to_csv(p)
    assert load_csv(p).samples == samples


def test_load_empty_csv(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("timestamp_us,packet,buttons,lt,rt,ls_x,ls_y,rs_x,rs_y,connected,held_us\n", encoding="utf-8")
    assert len(load_csv(p)) == 0


def test_load_csv_without_held_us_defaults_zero(tmp_path):
    p = tmp_path / "old.csv"
    p.write_text("timestamp_us,packet,buttons,lt,rt,ls_x,ls_y,rs_x,rs_y,connected\n"
                 "1000,1,0,0,0,0,0,0,0,1\n", encoding="utf-8")
    assert load_csv(p).samples[0].held_us == 0
