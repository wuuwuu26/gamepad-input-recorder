"""SSE web dashboard backed only by the Python standard library."""

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .models import Sample


def format_sse(data: dict) -> str:
    return "data: " + json.dumps(data) + "\n\n"


def make_html() -> str:
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>XInput Recorder — Live</title>
<style>
  body { background:#111; color:#eee; font-family:ui-monospace,Menlo,Consolas,monospace;
         margin:0; padding:12px; }
  h1 { font-size:1rem; margin:0 0 8px; color:#8cf; }
  canvas { background:#1a1a1a; border:1px solid #333; border-radius:6px; }
  .row { display:flex; flex-wrap:wrap; gap:12px; }
  .stat { color:#8f8; }
  .muted { color:#999; }
</style></head><body>
<h1>XInput Recorder — Live</h1>
<div class="row">
  <canvas id="pad" width="420" height="260"></canvas>
  <div><canvas id="curve" width="420" height="260"></canvas></div>
</div>
<p class="stat" id="stat">waiting for data…</p>
<p class="muted">Events via /events · recorder samples at full rate, view @30 Hz</p>
<script>
const BTN = {0x1:'↑',0x2:'↓',0x4:'←',0x8:'→',0x10:'START',0x20:'BACK',
 0x40:'L3',0x80:'R3',0x100:'LB',0x200:'RB',0x1000:'A',0x2000:'B',
 0x4000:'X',0x8000:'Y'};
const pad = document.getElementById('pad').getContext('2d');
const cv = document.getElementById('curve').getContext('2d');
const stat = document.getElementById('stat');
let hist = [];
function drawPad(d){
  pad.clearRect(0,0,420,260);
  if(!d.connected){ pad.fillStyle='#f66'; pad.fillText('CONTROLLER DISCONNECTED',20,30); return; }
  // sticks
  const sticks=[['L',210-d.ls_x/32768*60,110-d.ls_y/32768*60,'#8cf'],
                ['R',290-d.rs_x/32768*60,150-d.rs_y/32768*60,'#fc8']];
  for(const [n,x,y,c] of sticks){
    pad.strokeStyle='#444'; pad.beginPath(); pad.arc(x<210?150:290,x<210?110:150,60,0,7); pad.stroke();
    pad.fillStyle=c; pad.beginPath(); pad.arc(x,y,9,0,7); pad.fill();
    pad.fillText(n,x+10,y-10);
  }
  // triggers
  pad.fillStyle='#888'; pad.fillText('LT',20,200); pad.fillText('RT',20,230);
  pad.fillStyle='#444'; pad.fillRect(50,190,120,12); pad.fillRect(50,220,120,12);
  pad.fillStyle='#6c6'; pad.fillRect(50,190,120*d.lt/255,12); pad.fillRect(50,220,120*d.rt/255,12);
  // buttons
  const labels = Object.keys(BTN).map(Number).filter(k=>d.buttons & k).map(k=>BTN[k]);
  pad.fillStyle='#ffd54f'; pad.font='18px monospace'; pad.fillText(labels.join(' ')||'—',20,40);
}
function drawCurve(){
  cv.clearRect(0,0,420,260); cv.strokeStyle='#8cf'; cv.beginPath();
  hist.forEach((h,i)=>{ const x=i/Math.max(1,hist.length-1)*420, y=200-h*160/255;
    i?cv.lineTo(x,y):cv.moveTo(x,y); }); cv.stroke();
  cv.fillStyle='#999'; cv.fillText('A hold (last ~120 frames)',10,20);
}
const es = new EventSource('/events');
es.onmessage = e => {
  const d = JSON.parse(e.data);
  drawPad(d); hist.push(d.buttons & 0x1000 ? 255 : 0); if(hist.length>120) hist.shift();
  drawCurve(); stat.textContent = 'buttons=0x'+(d.buttons>>>0).toString(16)+
    ' LT='+d.lt+' RT='+d.rt+' LS='+d.ls_x+','+d.ls_y+' RS='+d.rs_x+','+d.rs_y;
};
es.onerror = () => { stat.textContent = 'stream disconnected (reconnecting…)'; };
</script></body></html>"""


class DashboardServer:
    """Tiny HTTP server streaming live controller state over SSE."""

    def __init__(self, host="127.0.0.1", port=8765, get_latest=None):
        self.host = host
        self.port = port
        self._get_latest = get_latest
        self._messages: queue.Queue = queue.Queue(maxsize=8)
        self._shutdown = threading.Event()
        self._httpd = None
        self._thread = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/":
                    body = make_html().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/events":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    try:
                        while not outer._shutdown.is_set():
                            if outer._get_latest is not None:
                                msg = outer._get_latest()
                            else:
                                try:
                                    msg = outer._messages.get(timeout=1.0)
                                except queue.Empty:
                                    self.wfile.write(b": keepalive\n\n")
                                    self.wfile.flush()
                                    continue
                            self.wfile.write(format_sse(msg).encode("utf-8"))
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                else:
                    self.send_error(404)

            def log_message(self, *args):
                pass

        self._Handler = Handler

    def start(self):
        self._httpd = ThreadingHTTPServer((self.host, self.port), self._Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True, name="xinput-dashboard")
        self._thread.start()
        return self

    def put_nowait(self, msg: dict) -> None:
        try:
            self._messages.put_nowait(msg)
        except queue.Full:
            try:
                self._messages.get_nowait()
            except queue.Empty:
                pass
            try:
                self._messages.put_nowait(msg)
            except queue.Full:
                pass

    def publish(self, sample: Sample) -> None:
        self.put_nowait({
            "timestamp_us": sample.timestamp_us,
            "buttons": sample.buttons,
            "lt": sample.lt,
            "rt": sample.rt,
            "ls_x": sample.ls_x,
            "ls_y": sample.ls_y,
            "rs_x": sample.rs_x,
            "rs_y": sample.rs_y,
            "connected": sample.connected,
        })

    def stop(self):
        self._shutdown.set()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
