# XInput 手柄输入采集库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 Windows 下只读、高频（默认 1000 Hz）采集 XInput 手柄输入并落盘的 Python 库，附带离线分析 API、CLI、自检工具和边录边看的 Web 仪表盘。

**Architecture:** 采集线程轮询 `XInputGetState()`（ctypes 直调，只读），状态写入线程安全队列，写入线程落盘到 CSV；另一路订阅者以 30 Hz 降采样通过 SSE 推送给标准库 HTTP 服务。录制与分析分离：分析模块从 CSV 加载 `Session` 后离线计算。依赖注入一个 `poll()` 数据源，使全部测试可在无手柄、非 Windows 环境运行。

**Tech Stack:** Python 3.10+、ctypes、`http.server` + SSE + 原生 Canvas（均标准库）；pytest 仅作开发依赖；pandas 可选。

**Spec:** `docs/superpowers/specs/2026-11-27-xinput-recorder-design.md`

## Global Constraints

- 平台：Windows 7+（`xinput1_4.dll`），Python 3.10+；非 Windows 环境必须能导入包并跑测试，只是不能真正采集。
- 核心库零强制第三方依赖（Web 仪表盘也只用标准库）；pandas 仅为分析模块的可选依赖；pytest 为开发依赖。
- 只读：绝不调用 `XInputSetState`，不做按键注入/宏/作弊；`XInputGetState()` 无副作用，不干扰游戏。
- 采样率默认 1000 Hz，可配置；时间戳为微秒整数（`time.perf_counter_ns() // 1000`）。
- 时间精度不虚标：自检工具实测达成率、平均/最大间隔、抖动并报告。
- 一个 `ControllerRecorder` 实例绑定一个 `user_index` 槽位；多手柄多实例。
- CSV：UTF-8，pandas 可直接读取，列固定为 `timestamp_us,packet,buttons,lt,rt,ls_x,ls_y,rs_x,rs_y,connected,held_us`。
- 热插拔：断开期间继续按 `connected=false` 记录，重连后在同一会话续录。
- 仪表盘默认只监听 `127.0.0.1:8765`；局域网访问需显式 `--host 0.0.0.0`；SSE 推送默认 30 Hz，绝不阻塞采集线程。

## Review Focus

规格暗示但单一任务的测试未覆盖、最可能坑到使用者的输入/失败模式；每条已在对应任务中钉上测试：

1. 完全没有手柄插入时，采集器必须稳定运行、全部标记 `connected=false`、不崩溃 → Task 3 `test_no_controller_does_not_crash`。
2. 会话中途拔掉再插回手柄，必须是同一会话连续记录，且 `connected` 状态转换被记录 → Task 3 `test_hotplug_mid_session_marked`。
3. 按键恰好在会话首/末采样点处于按下状态，`events()` 必须产出无配对的按下/抬起事件而不报错 → Task 4 `test_events_unclosed_press_at_end`、`test_events_empty_session`。
4. 浏览器晚连接或中途断开 SSE，服务端不得崩溃、不得阻塞采集线程 → Task 5 `test_server_serves_page_and_sse`、Task 3 `test_publish_never_blocks`。
5. 慢消费者（浏览器卡住）不得让发布阻塞导致丢采 → Task 3 `test_publish_never_blocks`（队列满时跳过并在 `dropped_publishes` 计数）。

---

### Task 1: 项目骨架 + XInput 低层绑定与数据模型

**Files:**
- Create: `pyproject.toml`
- Create: `src/xinput_recorder/__init__.py`
- Create: `src/xinput_recorder/models.py`（本任务只放 `Sample`）
- Create: `src/xinput_recorder/xinput.py`
- Test: `tests/test_xinput.py`

**Interfaces:**
- Produces: `Sample`（frozen dataclass，字段顺序 `timestamp_us:int, packet:int, buttons:int, lt:int, rt:int, ls_x:int, ls_y:int, rs_x:int, rs_y:int, connected:bool, held_us:int=0`）；`CSV_COLUMNS: tuple[str, ...]`（11 列，顺序见 Global Constraints）。
- Produces: `xinput.XINPUT_STATE`/`XINPUT_GAMEPAD`（ctypes Structure，`sizeof(XINPUT_STATE) == 16`）；`xinput.decode_state(state, timestamp_us, connected) -> Sample`；`xinput.XInputSource(user_index: int)`，其 `poll() -> Sample`；`xinput.create_source(user_index: int) -> XInputSource`（非 Windows 或 DLL 缺失时抛 `RuntimeError`，消息含 "Windows"）。

- [ ] **Step 1: 写失败测试 `tests/test_xinput.py`**

```python
import ctypes, sys
import pytest
from xinput_recorder import xinput

def test_xinput_state_layout():
    assert ctypes.sizeof(xinput.XINPUT_STATE) == 16

def test_decode_state_maps_all_fields():
    s = xinput.XINPUT_STATE()
    s.dwPacketNumber = 7
    s.Gamepad.wButtons = 0x1000          # A
    s.Gamepad.bLeftTrigger = 10
    s.Gamepad.bRightTrigger = 200
    s.Gamepad.sThumbLX, s.Gamepad.sThumbLY = -32768, 32767
    s.Gamepad.sThumbRX, s.Gamepad.sThumbRY = 12, -9
    out = xinput.decode_state(s, 123456, True)
    assert (out.timestamp_us, out.packet, out.buttons) == (123456, 7, 0x1000)
    assert (out.lt, out.rt) == (10, 200)
    assert (out.ls_x, out.ls_y, out.rs_x, out.rs_y) == (-32768, 32767, 12, -9)
    assert out.connected is True and out.held_us == 0

def test_create_source_rejects_non_windows(monkeypatch):
    monkeypatch.setattr(xinput.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows"):
        xinput.create_source(0)

def test_package_import_is_platform_independent():
    import xinput_recorder  # 不应在本机（win32）或非 win32 导入时炸掉
    assert xinput_recorder.__version__
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_xinput.py -v`
Expected: FAIL，ImportError（模块尚未创建）。

- [ ] **Step 3: 实现骨架与低层绑定**

`pyproject.toml`：`[build-system] setuptools>=68`；`[project] name="xinput-recorder"`, `version="0.1.0"`, `requires-python=">=3.10"`；`[project.optional-dependencies] dev=["pytest>=8"]`, `analysis=["pandas>=2"]`；`[tool.setuptools.packages.find] where=["src"]`。此时先不放 scripts，Task 6 再加。
`src/xinput_recorder/__init__.py`：定义 `__version__ = "0.1.0"`（暂不导出其他名字）。
`models.py`：`Sample` frozen dataclass；`CSV_COLUMNS` 常量。
`xinput.py`：按 XInput 1.4 布局定义 `XINPUT_GAMEPAD`（`wButtons:uint16, bLeftTrigger:uint8, bRightTrigger:uint8, sThumbLX:sint16, sThumbLY, sThumbRX, sThumbRY`）与 `XINPUT_STATE`（`dwPacketNumber:uint32, Gamepad`）；`decode_state` 为纯函数；`XInputSource.poll()` 调用 `XInputGetState(user_index, byref(state))`，返回错误码 0 时 `decode_state(..., True)`，返回 `ERROR_DEVICE_NOT_CONNECTED (1167)` 时返回全部字段为零、`connected=False` 的 Sample；`create_source` 检查 `sys.platform == "win32"`，用 `ctypes.WinDLL` 惰性加载 `xinput1_4.dll` 并设好 `argtypes/restype`，失败抛含 "Windows" 的 `RuntimeError`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_xinput.py -v`
Expected: 4 passed。

- [ ] **Step 5: 初始化仓库并提交**

```bash
git init
git add pyproject.toml src tests
git commit -m "feat: scaffold package and XInput ctypes binding"
```

---

### Task 2: Session 与 CSV 持久化

**Files:**
- Modify: `src/xinput_recorder/models.py`（追加 `Session`、`load_csv`）
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `Sample`、`CSV_COLUMNS`（Task 1）。
- Produces: `Session(samples: list[Sample])`，`__len__()`；`session.to_csv(path)`；模块级 `load_csv(path) -> Session`（缺 `held_us` 列时兼容为 0；表头-only 文件返回空 Session）。

- [ ] **Step 1: 写失败测试 `tests/test_models.py`**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL（Session/load_csv 未定义）。

- [ ] **Step 3: 实现 `Session` 与 `load_csv`**

`Session.to_csv` 用 `csv.DictWriter`，`lineterminator="\n"`、UTF-8，每行按 `CSV_COLUMNS` 顺序取 `getattr(sample, col)`。
`load_csv` 用 `csv.DictReader`，逐行按列名构造 `Sample`；`int(row[col])` 转换数值列，`connected` 用 `row["connected"] == "1"`；若 `held_us` 列缺失则传 0。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_models.py -v`
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add src/xinput_recorder/models.py tests/test_models.py
git commit -m "feat: Session CSV persistence"
```

---

### Task 3: 采集器（采样线程 + 写入线程 + 热插拔 + 订阅发布）

**Files:**
- Create: `src/xinput_recorder/recorder.py`
- Test: `tests/test_recorder.py`

**Interfaces:**
- Consumes: `Sample`、`CSV_COLUMNS`（Task 1）；`Session`、`load_csv`（Task 2）；`xinput.create_source`（Task 1，仅在 `source=None` 时调用）。
- Produces: `ControllerRecorder(hz=1000, user_index=0, out=None, change_only=False, source=None)`；属性 `out_path: str`、`dropped_publishes: int`、`session`（`stop()` 前为 `None`，之后为 `Session`）；方法 `start()`、`stop()`、`add_subscriber(sink)`、`publish(sample: Sample) -> None`（非阻塞）；`__enter__`/`__exit__`。`source` 为可注入对象，`poll() -> Sample`。`out=None` 时用 `tempfile.mkstemp` 生成临时 CSV 路径。
- 订阅者契约：任何带 `put_nowait(obj) -> None` 的对象（如 `queue.Queue`、`DashboardServer`）。`publish(sample)` 把消息字典 `put_nowait` 给每个订阅者；`queue.Full` 或其他实现自定义的满队列异常时 `dropped_publishes += 1` 并跳过，绝不阻塞。

- [ ] **Step 1: 写失败测试 `tests/test_recorder.py`**

```python
import queue, time
from xinput_recorder.models import Sample
from xinput_recorder.recorder import ControllerRecorder

class FakeSource:
    def __init__(self, frames=None):
        self.frames, self.i = frames, 0
    def poll(self):
        if self.frames is None:
            s = Sample(time.perf_counter_ns()//1000, self.i, 0x1000, 0,0,0,0,0,0, True, 0)
        else:
            s = self.frames[min(self.i, len(self.frames)-1)]
        self.i += 1
        return s

def test_records_samples_from_fake_source(tmp_path):
    p = tmp_path / "r.csv"
    with ControllerRecorder(hz=200, source=FakeSource(), out=str(p)) as rec:
        time.sleep(0.25)
    samples = rec.session.samples
    assert 30 <= len(samples) <= 60          # 目标 50，CI 上放宽
    assert all(b > a for a, b in zip([s.timestamp_us for s in samples],
                                     [s.timestamp_us for s in samples][1:]))
    assert p.exists()

def test_no_controller_does_not_crash(tmp_path):
    off = Sample(0, 0, 0,0,0,0,0,0,0, False, 0)
    with ControllerRecorder(hz=200, source=FakeSource([off]), out=str(tmp_path/"n.csv")) as rec:
        time.sleep(0.1)
    assert rec.session.samples and all(not s.connected for s in rec.session.samples)

def test_hotplug_mid_session_marked(tmp_path):
    on = Sample(0, 0, 0,0,0,0,0,0,0, True, 0)
    off = Sample(0, 0, 0,0,0,0,0,0,0, False, 0)
    src = FakeSource([on]*5 + [off]*5 + [on]*5)
    with ControllerRecorder(hz=200, source=src, out=str(tmp_path/"h.csv")) as rec:
        time.sleep(0.3)
    flags = [s.connected for s in rec.session.samples]
    assert True in flags and False in flags and flags.index(True) < flags.index(False)

def test_publish_never_blocks(tmp_path):
    q = queue.Queue(maxsize=1)
    q.put("stale")
    rec = ControllerRecorder(hz=200, source=FakeSource(), out=str(tmp_path/"p.csv"))
    rec.add_subscriber(q)
    t0 = time.monotonic()
    rec.publish(Sample(0,0,0,0,0,0,0,0,0,True,0))
    assert time.monotonic() - t0 < 0.05
    assert rec.dropped_publishes == 1

def test_change_only_writes_fewer_rows(tmp_path):
    a = Sample(0,0,0x1000,0,0,0,0,0,0,True,0)
    b = Sample(0,0,0x2000,0,0,0,0,0,0,True,0)
    src = FakeSource([a]*10 + [b]*10)
    p = tmp_path/"c.csv"
    with ControllerRecorder(hz=200, source=src, out=str(p), change_only=True) as rec:
        time.sleep(0.3)
    assert 0 < len(rec.session.samples) < 20
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_recorder.py -v`
Expected: FAIL（recorder 模块不存在）。

- [ ] **Step 3: 实现 `ControllerRecorder`**

采样线程：循环 `source.poll()`，立刻打时间戳（时间戳在 `poll()` 前后各取一次取中点，或直接由 source 提供；此实现中覆盖 Sample 的 `timestamp_us` 为循环读取时刻），放入 `queue.Queue`（容量 10000）；按 `publish_hz=30` 节流调用 `self.publish(sample)`；自适应定时 `time.sleep(interval*0.6)` 后自旋至目标时刻。
写入线程：从队列取 Sample，逐行写 CSV（复用 Task 2 的 `Session.to_csv` 的列顺序思路，增量写）；`change_only=True` 时仅当 `(buttons,lt,rt,ls_x,ls_y,rs_x,rs_y,connected)` 与上次写入不同才写，并把 `held_us` 设为 `当前 timestamp - 上次写入 timestamp`，否则跳过。
`publish` 对每个订阅队列 `put_nowait({"timestamp_us":..., "buttons":..., "lt":..., "rt":..., "ls_x":..., "ls_y":..., "rs_x":..., "rs_y":..., "connected":...})`；`queue.Full` 时 `dropped_publishes += 1` 并跳过，绝不阻塞。
`stop()`：置停止事件 → join 采样线程与写入线程（超时 5s）→ `self.session = load_csv(self.out_path)`。`__enter__` 调 `start()` 并 `return self`；`__exit__` 调 `stop()` 并关闭临时文件（若 `out` 由用户指定则不删）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_recorder.py -v`
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
git add src/xinput_recorder/recorder.py tests/test_recorder.py
git commit -m "feat: recorder threads, hotplug and subscribers"
```

---

### Task 4: 离线分析模块

**Files:**
- Create: `src/xinput_recorder/analysis.py`
- Test: `tests/test_analysis.py`

**Interfaces:**
- Consumes: `Session`、`Sample`（Task 1/2）。
- Produces: `ButtonEvent(button:str, pressed_us:int, released_us:int|None, duration_us:int|None)`；`events(session: Session) -> list[ButtonEvent]`；`TriggerCurve(side:str, points:list[tuple[int,int]], peak:int, peak_time_us:int|None, rise_us:int|None)`；`trigger_curves(session: Session) -> dict[str, TriggerCurve]`（键 `lt`/`rt`）；`StickTrajectory(side:str, points:list[tuple[int,int,int]], path_length:float, max_radius:float, tremor_rms:float)`；`stick_trajectory(session: Session, side:str="left") -> StickTrajectory`；`stats(session: Session) -> dict[str,float]`（键 `achieved_hz, mean_interval_us, max_interval_us, jitter_us`）。
- 按键位名映射：`0x0001..0x0008` = DPAD_UP/DOWN/LEFT/RIGHT，`0x0010` START，`0x0020` BACK，`0x0040` L3，`0x0080` R3，`0x0100` LB，`0x0200` RB，`0x1000` A，`0x2000` B，`0x4000` X，`0x8000` Y。

- [ ] **Step 1: 写失败测试 `tests/test_analysis.py`**

```python
from xinput_recorder.models import Sample, Session
from xinput_recorder.analysis import events, trigger_curves, stick_trajectory, stats

def s(t, buttons=0, lt=0, rt=0):
    return Sample(t, 0, buttons, lt, rt, 0,0,0,0, True, 0)

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
    pts = [Sample(0,0,0,0,0,0,0,0,0,True,0),
           Sample(1000,0,0,0,0,3,4,0,0,True,0),
           Sample(2000,0,0,0,0,0,0,0,0,True,0)]
    tr = stick_trajectory(Session(pts), "left")
    assert (tr.path_length, tr.max_radius, tr.tremor_rms) == (10.0, 5.0, 5.0)

def test_stats_reports_intervals():
    st = stats(Session([s(0), s(1000), s(2000)]))
    assert st["achieved_hz"] == 1000.0
    assert st["mean_interval_us"] == 1000.0 and st["max_interval_us"] == 1000.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_analysis.py -v`
Expected: FAIL（analysis 模块不存在）。

- [ ] **Step 3: 实现 `analysis.py`**

`events`：维护每个按键在上一个采样是否按下的字典；`0→1` 记 pressed_us（若首采样已按下，pressed_us = 首采样时间）；`1→0` 配对并算 duration_us；会话结束时仍未抬起的键产出 `released_us=None, duration_us=None`；空 Session 返回 []。
`trigger_curves`：按 lt/rt 收集 `(timestamp_us, value)`；`peak=max(value)`，`peak_time_us` 为首次达到峰值的采样时间；`rise_us = peak_time_us - 第一个 value>0 的采样时间`（若无正值则 None）。
`stick_trajectory`：`points` 取 `(t, x, y)`；`path_length` 为相邻点欧氏距离之和；`max_radius` 为最大 $\sqrt{x^2+y^2}$；`tremor_rms` 为内部点相对相邻两点中点的偏移向量长度之和除以内部点数（单点时即该点偏移长度），无内部点时 0.0。
`stats`：间隔数组 `diff = [t[i+1]-t[i]]`；`achieved_hz = 1e6 / mean(diff)`；`jitter_us` 为 diff 的总体标准差；空/单点 Session 返回全 0.0。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_analysis.py -v`
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
git add src/xinput_recorder/analysis.py tests/test_analysis.py
git commit -m "feat: offline analysis events/triggers/sticks/stats"
```

---

### Task 5: Web 仪表盘（SSE + 标准库 HTTP 服务）

**Files:**
- Create: `src/xinput_recorder/dashboard.py`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `Sample`（Task 1）；订阅消息字典格式由 Task 3 `publish()` 定义（含 `timestamp_us, buttons, lt, rt, ls_x, ls_y, rs_x, rs_y, connected`）。
- Produces: `format_sse(data: dict) -> str`（返回 `data: <json>\n\n`）；`make_html() -> str`（含 `EventSource` 与 `/events`）；`DashboardServer(host:str="127.0.0.1", port:int=8765, get_latest=None)`，方法 `start()`、`stop()`、`publish(sample: Sample)`、`put_nowait(msg: dict) -> None`（实现 Task 3 订阅者契约：把消息放进内部队列，满则替换最新）、`port` 属性（绑定 0 时读取实际端口）。
- 供 CLI 接入 recorder 的适配方式：`DashboardServer.put_nowait` 接受 Task 3 `publish()` 产生的消息字典；`add_subscriber(dashboard)` 后采集线程每 30 Hz 推一次。

- [ ] **Step 1: 写失败测试 `tests/test_dashboard.py`**

```python
import json, socket, urllib.request
from xinput_recorder.models import Sample
from xinput_recorder.dashboard import DashboardServer, format_sse, make_html

def test_format_sse():
    assert format_sse({"buttons": 4096}) == 'data: {"buttons": 4096}\n\n'

def test_make_html_contains_eventsource():
    html = make_html()
    assert "EventSource" in html and "/events" in html

def test_server_serves_page_and_sse():
    srv = DashboardServer(host="127.0.0.1", port=0, get_latest=lambda: {"buttons": 4096})
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
    srv.publish(Sample(0,0,0,0,0,0,0,0,0,True,0))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: FAIL（dashboard 模块不存在）。

- [ ] **Step 3: 实现 `dashboard.py`**

`format_sse` 用 `json.dumps(data)`（默认分隔符）拼 `data: ...\n\n`。
`make_html` 返回内联 HTML+JS：用 `new EventSource("/events")`，`onmessage` 解析 JSON；Canvas 画手柄轮廓与按键高亮、双摇杆散点、扳机压力条、采样率文本与滚动曲线；自带基础样式（深色背景、等宽字体），不引用外部资源。
`DashboardServer`：`ThreadingHTTPServer((host, port), Handler)`，`serve_forever` 放 daemon 线程；Handler 实现 `do_GET`：`/` 返回 `make_html()`，`/events` 设 `Content-Type: text/event-stream`、`Cache-Control: no-cache`、循环：若构造时传入了 `get_latest` 则每轮优先调用它取得消息字典（测试用，使首行立即为数据），否则从内部订阅队列取（超时 1s 时发 `:keepalive\n\n` 续命）；`BrokenPipe`/`ConnectionReset` 时退出，其他路径 404。`put_nowait(msg)` 把消息放进内部队列（满则 `get_nowait()` 丢弃最旧一条再放）；`publish(sample)` 把 Task 3 格式的字典交给 `put_nowait`。`stop()` 关闭服务器并 join 线程（并置 `shutdown` 事件让 SSE 循环结束）。构造函数不启动服务，须显式 `start()`；`port=0` 时 `self.port` 在 `start()` 后更新为 `server.server_address[1]` 的实际端口。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add src/xinput_recorder/dashboard.py tests/test_dashboard.py
git commit -m "feat: SSE web dashboard"
```

---

### Task 6: CLI、自检工具、包导出与文档

**Files:**
- Modify: `pyproject.toml`（追加 `[project.scripts]`）
- Modify: `src/xinput_recorder/__init__.py`（导出公共 API）
- Create: `src/xinput_recorder/cli.py`
- Create: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 全部前序任务。
- Produces: `cli.record_main(argv: list[str] | None = None) -> int`、`cli.selftest_main(argv=None) -> int`；CLI 参数含 `--hz`（默认 1000）、`--out`、`--user`（默认 0）、`--seconds`（默认无限，测试用有限值）、`--change-only`、`--dashboard`、`--host`（默认 127.0.0.1）、`--port`（默认 8765）、`--source {xinput,fake}`（默认 xinput，fake 供测试/无手柄演示）。
- 公共 API 从 `xinput_recorder` 导出：`ControllerRecorder, Session, load_csv, events, trigger_curves, stick_trajectory, stats, analyze_file(path) -> dict`（后者内部用 `load_csv` 并调用各分析函数，返回 dict）。

- [ ] **Step 1: 写失败测试 `tests/test_cli.py`**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL（cli 模块不存在）。

- [ ] **Step 3: 实现 CLI 与导出**

`cli.py`：`record_main` 解析参数 → 选 source（`fake` 用模块内 `FakeSource` 以固定 60 Hz 状态序列产生 Sample；`xinput` 用 `create_source(user_index)`）→ 若 `--dashboard` 则创建并 `start()` `DashboardServer(host, port)`，调用 `rec.add_subscriber(dashboard)`（用 Task 5 的 `DashboardServer.put_nowait` 契约）→ `with ControllerRecorder(...) as rec:`：`seconds` 为有限值时 `time.sleep(seconds)`，为 `None`（默认）时 `threading.Event().wait()` 直到 Ctrl-C（`KeyboardInterrupt`）→ 打印访问地址与落盘路径 → `stop()` dashboard → 返回 0。`selftest_main`：`record_main` 逻辑跑固定时长，调用 `stats(rec.session)`，打印 `achieved_hz`、`jitter_us`、`mean/max interval` 与"Python 调度存在抖动，数值为实测"提示；返回 0。
`__init__.py`：导出 Task 6 Interfaces 所列名字；`analyze_file(path)` 组合 `load_csv` + 四个分析函数，返回 `{"stats":..., "events":..., "trigger_curves":..., "stick_trajectory":...}`。
`pyproject.toml`：`[project.scripts]` 增加 `xinput-record = "xinput_recorder.cli:record_main"` 与 `xinput-selftest = "xinput_recorder.cli:selftest_main"`。
`README.md`：安装、Python API/CLI 示例、字段表、仪表盘访问方式（含局域网 `--host 0.0.0.0` 提示）、只读声明、自检与精度说明。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_cli.py -v`
Expected: 3 passed。

- [ ] **Step 5: 全量验证并提交**

```bash
python -m pytest -q
python -c "import xinput_recorder as x; print(x.__version__); print(sorted(n for n in dir(x) if not n.startswith('_')))"
git add pyproject.toml src README.md tests
git commit -m "feat: CLI, selftest, public API and README"
```

Expected: 全部测试通过（约 20 项）；导入打印出 `0.1.0` 及公共 API 名称。
