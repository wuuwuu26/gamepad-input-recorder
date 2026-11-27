# xinput-recorder

只读、高频的 Windows XInput 手柄输入采集库，用于学术与行为研究。

它后台轮询 `XInputGetState()`（不修改游戏、不注入输入、不抢焦点），以默认 1000 Hz 记录玩家在**任意游戏**中的手柄操作，附带微秒级时间戳。核心零强制第三方依赖，可边录边看实时 Web 仪表盘。

## 原理

XInput 是共享轮询 API：游戏每帧读手柄，独立进程也能同时读到同一份状态。本库的 `XInputGetState()` 是只读快照、无副作用，既不会消耗游戏的按键事件，也不会改变游戏读到的状态。已查证 MSDN 文档确认此行为。

> 仅支持 **Windows**（`xinput1_4.dll`）与 XInput 兼容手柄；不记录键鼠，不做按键注入/宏。

## 安装

```bash
pip install .
# 开发 / 分析可选依赖
pip install -e ".[dev,analysis]"
```

## 用法一：Python API

```python
from xinput_recorder import ControllerRecorder, analyze_file

with ControllerRecorder(hz=1000, user_index=0, out="session.csv",
                        dashboard=True) as rec:   # 游戏此时正常游玩
    ...

session = rec.session
result = analyze_file("session.csv")
print(result["stats"])
print(result["events"][:3])
```

## 用法二：命令行

```bash
# 边录边看（默认 1000 Hz，录到 session.csv）
xinput-record --hz 1000 --out session.csv --user 0 --dashboard

# 局域网访问仪表盘（手机/平板/副屏）
xinput-record --out session.csv --dashboard --host 0.0.0.0

# 无手柄演示
xinput-record --source fake --seconds 3 --dashboard

# 实测采样精度
xinput-selftest --seconds 2
```

`--dashboard` 后浏览器打开 `http://127.0.0.1:8765/`（局域网用本机 IP）。画面展示手柄按键高亮、双摇杆位置、扳机压力、采样统计与滚动曲线；推送降采样到 30 Hz，不影响录制精度。

## CSV 字段

| 列 | 含义 |
|---|---|
| `timestamp_us` | 微秒级单调时钟时间戳 |
| `packet` | XInput 包号（状态变化时递增） |
| `buttons` | 16 位按键位掩码 |
| `lt` / `rt` | 左右扳机压力 0–255 |
| `ls_x,ls_y,rs_x,rs_y` | 双摇杆坐标 -32768…32767 |
| `connected` | 手柄连接状态（1/0） |
| `held_us` | 状态持续时长（`change_only` 模式下有效） |

`--change-only` 仅在状态变化时记一行，可显著减小文件（1 kHz 全量约 60–100 MB/小时）。

## 分析模块

- `events(session)`：按键按下/抬起事件、按压时长
- `trigger_curves(session)`：扳机力度曲线、峰值、上升时间
- `stick_trajectory(session, side)`：摇杆轨迹、路径长度、抖动 RMS
- `stats(session)`：实际采样率、平均/最大间隔、抖动
- `analyze_file(path)`：一次返回以上全部结果（dict）

## 精度说明

Python 的 `time.sleep()` 在 Windows 上精度约 1 ms。采集线程采用「sleep 大部分间隔 + 末段自旋」的自适应策略追求 1 kHz；`xinput-selftest` 会**实测**达成率、平均/最大间隔与抖动并如实报告，不虚标精度。开启仪表盘不会降低采集频率（推送独立降采样）。

## 测试

```bash
python -m pytest -q
```

全部测试注入假数据源，无需真实手柄、可在任意平台运行。
