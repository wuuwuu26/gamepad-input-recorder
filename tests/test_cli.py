def test_record_cli_creates_csv(tmp_path):
    from xinput_recorder.cli import record_main
    p = tmp_path / "cli.csv"
    rc = record_main(["--hz", "200", "--seconds", "0.2",
                      "--source", "fake", "--out", str(p)])
    assert rc == 0 and p.exists()
    assert p.read_text(encoding="utf-8").splitlines()[0].startswith("timestamp_us,")


def test_record_cli_with_dashboard(tmp_path):
    from xinput_recorder.cli import record_main
    p = tmp_path / "dash.csv"
    rc = record_main(["--hz", "200", "--seconds", "0.2", "--source", "fake",
                      "--dashboard", "--port", "0", "--out", str(p)])
    assert rc == 0 and p.exists()


def test_selftest_prints_stats(capsys):
    from xinput_recorder.cli import selftest_main
    rc = selftest_main(["--seconds", "0.15", "--source", "fake"])
    out = capsys.readouterr().out
    assert rc == 0 and "Hz" in out and "jitter" in out
