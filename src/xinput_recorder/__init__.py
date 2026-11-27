"""xinput-recorder: read-only XInput controller input capture for research."""

from .analysis import events, stick_trajectory, stats, trigger_curves
from .models import Session, load_csv
from .recorder import ControllerRecorder

__version__ = "0.1.0"


def analyze_file(path) -> dict:
    """Load a CSV and return all offline analyses in one dict."""
    session = load_csv(path)
    return {
        "stats": stats(session),
        "events": events(session),
        "trigger_curves": trigger_curves(session),
        "stick_trajectory": stick_trajectory(session),
    }


__all__ = [
    "ControllerRecorder", "Session", "load_csv", "events",
    "trigger_curves", "stick_trajectory", "stats", "analyze_file",
    "__version__",
]
