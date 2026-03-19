import glob
import os
import re

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
LOGS_DIR = os.path.join(DATA_DIR, "logs")


def get_latest_log_path() -> str | None:
    """Find the most recent bot log file."""
    pattern = os.path.join(LOGS_DIR, "bot_*.log")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def read_log_lines(n: int = 200) -> list[dict]:
    """Read last N lines from the latest log file, parsed."""
    path = get_latest_log_path()
    if not path:
        return []

    with open(path, "r") as f:
        lines = f.readlines()

    parsed = []
    for raw in lines[-n:]:
        raw = raw.strip()
        if not raw:
            continue
        parsed.append(parse_log_line(raw))
    return parsed


def parse_log_line(line: str) -> dict:
    """Parse a log line into structured data."""
    m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)", line)
    if m:
        timestamp, message = m.groups()
    else:
        timestamp, message = "", line

    msg_type = "info"
    if "PREDICT" in message:
        msg_type = "predict"
    elif "RESULT" in message:
        msg_type = "win" if "WIN" in message else "loss"
    elif "SKIP" in message:
        msg_type = "skip"
    elif "MARKET" in message:
        msg_type = "market"
    elif "MODEL" in message:
        msg_type = "model"
    elif "ERROR" in message or "WARNING" in message:
        msg_type = "error"
    elif "EARLY" in message:
        msg_type = "early"
    elif "FEATURES" in message:
        msg_type = "features"

    return {"timestamp": timestamp, "message": message, "type": msg_type}


def parse_features_from_log(n: int = 500) -> dict:
    """Parse latest FEATURES line and count PREDICT/RESULT/SKIP from tail of log."""
    path = get_latest_log_path()
    if not path:
        return {"features": {}, "resolution": {}, "last_updated": None}

    with open(path, "r") as f:
        lines = f.readlines()

    tail = lines[-n:]

    features = {}
    last_updated = None
    for line in reversed(tail):
        if "FEATURES" in line:
            pairs = re.findall(r"(\w+)=([\d.\-]+)", line)
            features = {k: round(float(v), 4) for k, v in pairs}
            ts_match = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
            if ts_match:
                last_updated = ts_match.group(1)
            break

    predictions = sum(1 for l in tail if re.search(r"\] PREDICT ", l))
    results = sum(1 for l in tail if "RESULT" in l)
    skips = sum(1 for l in tail if "SKIP" in l)

    return {
        "features": features,
        "resolution": {
            "predictions": predictions,
            "results": results,
            "skips": skips,
            "resolution_rate": round(results / predictions * 100, 1) if predictions > 0 else 0,
        },
        "last_updated": last_updated,
    }
