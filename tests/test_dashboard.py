import json
import urllib.request

from xinput_recorder.models import Sample
from xinput_recorder.dashboard import DashboardServer, format_sse, make_html


def test_format_sse():
    assert format_sse({"buttons": 4096}) == 'data: {"buttons": 4096}\n\n'


def test_make_html_contains_eventsource():
    html = make_html()
    assert "EventSource" in html and "/events" in html


def test_server_serves_page_and_sse():
    srv = DashboardServer(host="127.0.0.1", port=0,
                          get_latest=lambda: {"buttons": 4096})
    srv.start()
    try:
        base = f"http://127.0.0.1:{srv.port}"
        with urllib.request.urlopen(base + "/", timeout=2) as r:
            assert "EventSource" in r.read().decode()
        with urllib.request.urlopen(base + "/events", timeout=2) as r:
            line = r.readline().decode().strip()
        assert line.startswith("data: ") and json.loads(line[6:])["buttons"] == 4096
    finally:
        srv.stop()


def test_publish_without_subscribers_is_noop():
    srv = DashboardServer(port=0)
    srv.publish(Sample(0, 0, 0, 0, 0, 0, 0, 0, 0, True, 0))
