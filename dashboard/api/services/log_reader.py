import glob
import json
import os
import re

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
LOGS_DIR = os.path.join(DATA_DIR, "logs")


def get_latest_log_path() -> str | None:
    """Find the most recent bot log file (arb or paper trader)."""
    patterns = [
        os.path.join(LOGS_DIR, "arb_*.log"),
        os.path.join(LOGS_DIR, "bot_*.log"),
    ]
    all_files = []
    for p in patterns:
        all_files.extend(glob.glob(p))
    if not all_files:
        return None
    return max(all_files, key=os.path.getmtime)


def _tail_file(path: str, n: int) -> list[str]:
    """Efficiently read last N lines using binary seek (avoids loading entire file)."""
    try:
        with open(path, "rb") as f:
            # Seek from end, reading chunks until we have N newlines
            f.seek(0, 2)
            file_size = f.tell()
            if file_size == 0:
                return []

            chunk_size = min(8192, file_size)
            buf = b""
            pos = file_size
            lines_found = 0

            while pos > 0 and lines_found < n + 1:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                buf = chunk + buf
                lines_found = buf.count(b"\n")

            lines = buf.decode("utf-8", errors="replace").splitlines()
            return lines[-n:] if len(lines) > n else lines
    except Exception:
        return []


def read_window_logs(window_id: int) -> list[dict]:
    """Read all log lines that belong to a specific 15-min window.
    Scans all log files (the window may span a bot restart).
    Matches lines containing 'window=<window_id>' OR within the time range.
    """
    from datetime import datetime, timezone
    window_start = window_id
    window_end = window_id + 900  # 15 minutes

    patterns = [
        os.path.join(LOGS_DIR, "arb_*.log"),
        os.path.join(LOGS_DIR, "bot_*.log"),
    ]
    all_files = []
    for p in patterns:
        all_files.extend(glob.glob(p))
    all_files.sort(key=os.path.getmtime)

    results = []
    window_str = "window=%d" % window_id

    for path in all_files:
        try:
            with open(path, "r", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    # Quick filter: must mention this window OR fall in time range
                    if window_str not in raw:
                        # Try time-based match as fallback
                        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", raw)
                        if m:
                            try:
                                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
                                if not (window_start <= ts <= window_end):
                                    continue
                            except Exception:
                                continue
                        else:
                            continue
                    parsed = parse_log_line(raw)
                    # Skip pure TICK lines to keep it readable — keep key events
                    msg = parsed.get("message", "")
                    if msg.startswith("TICK ") and "state=IDLE" in msg:
                        continue  # Skip IDLE ticks — too noisy
                    results.append(parsed)
        except Exception:
            continue

    return results


def read_log_lines(n: int = 200) -> list[dict]:
    """Read last N lines from the latest log file, parsed."""
    path = get_latest_log_path()
    if not path:
        return []

    lines = _tail_file(path, n)
    parsed = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        parsed.append(parse_log_line(raw))
    return parsed


def parse_log_line(line: str) -> dict:
    """Parse a log line into structured data."""
    m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*(.*)", line)
    if not m:
        m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)", line)
    if m:
        timestamp, message = m.groups()
    else:
        timestamp, message = "", line

    msg_type = "info"

    # OFI directional types (check word-boundary to avoid matching "OPEN" in "POSITION_OPEN")
    if message.startswith("WIN "):
        msg_type = "win"
    elif message.startswith("LOSE "):
        msg_type = "lose"
    elif message.startswith("OPEN "):
        msg_type = "open"
    elif message.startswith("  HOLD") or message.startswith("HOLD "):
        msg_type = "hold"
    # Shared arb types
    elif "INSTANT_ARB" in message:
        msg_type = "instant_arb"
    elif "DECISION" in message:
        msg_type = "decision"
    elif "ABANDONED" in message:
        msg_type = "abandoned"
    # Legacy legging types
    elif "LEG2" in message or "LEG1" in message:
        msg_type = "leg"
    elif "HUNTING" in message:
        msg_type = "hunting"
    elif "COMPLETE" in message:
        msg_type = "complete"
    elif "TICK" in message:
        msg_type = "tick"
    elif "NEW WINDOW" in message or "PRE_SUBSCRIBE" in message:
        msg_type = "window"
    elif "NO_MARKET" in message:
        msg_type = "skip"
    # Error detection — also catch Python tracebacks
    elif ("ERROR" in message or "WARNING" in message
          or "Traceback" in message or "Exception" in message):
        msg_type = "error"
    # Paper trader types (backward compat)
    elif "PREDICT" in message:
        msg_type = "predict"
    elif "RESULT" in message:
        msg_type = "win" if "WIN" in message else "loss"
    elif "SKIP" in message:
        msg_type = "skip"
    elif "MARKET" in message:
        msg_type = "market"
    elif "MODEL" in message:
        msg_type = "model"
    elif "EARLY" in message:
        msg_type = "early"
    elif "FEATURES" in message:
        msg_type = "features"

    return {"timestamp": timestamp, "message": message, "type": msg_type}


def parse_features_from_log(n: int = 500) -> dict:
    """Parse arb stats from tail of log, or ML features for paper trader."""
    path = get_latest_log_path()
    if not path:
        return {"features": {}, "resolution": {}, "signal": {}, "last_updated": None}

    is_arb = os.path.basename(path).startswith("arb_")
    tail = _tail_file(path, n)

    if is_arb:
        return _parse_arb_stats(tail)
    else:
        return _parse_paper_stats(tail)


def _parse_arb_stats(tail: list[str]) -> dict:
    """Extract arb bot stats and signal metrics from log tail."""
    # ── Latest TICK data ─────────────────────────────────────────────────────
    last_tfi = None
    last_obi = None
    last_conf = None
    last_state = None
    last_up_ask = None
    last_down_ask = None
    last_updated = None
    last_ob_shock: int | None = None
    last_mom: float | None = None

    # ── Latest DECISION event ────────────────────────────────────────────────
    last_decision: dict | None = None
    decision_log: list[dict] = []

    # ── Activity counters ────────────────────────────────────────────────────
    wins = 0
    losses = 0
    abandoned = 0
    instant_arbs = 0
    last_position_side = None
    last_position_entry = None

    for line in reversed(tail):
        # Parse TICK line (new format with tfi/obi/conf)
        if last_tfi is None and "TICK" in line:
            # New format: tfi=+Z.Z(N) obi=+O.OOO conf=CC.C
            # New format: tfi=+Z.Z(bN/tM)  — book/trade event counts
            m = re.search(r"tfi=([+\-]?[\d.]+)", line)
            if m:
                last_tfi = float(m.group(1))
            else:
                # Backward compat: old format used ofi=
                m = re.search(r"ofi=([+\-]?[\d.]+)", line)
                if m:
                    last_tfi = float(m.group(1))

            m = re.search(r"obi=([+\-]?[\d.]+)", line)
            if m:
                last_obi = float(m.group(1))

            m = re.search(r"conf=([\d.]+)", line)
            if m:
                last_conf = float(m.group(1))

            m = re.search(r"state=(\w+)", line)
            if m:
                last_state = m.group(1)

            m = re.search(r"ob_shock=(\d+)", line)
            if m:
                last_ob_shock = int(m.group(1))

            m = re.search(r"mom=([+\-]?[\d.]+)", line)
            if m:
                last_mom = float(m.group(1))

            m = re.search(r"up_ask=([\d.]+|none)", line)
            if m and m.group(1) != "none":
                last_up_ask = float(m.group(1))

            m = re.search(r"down_ask=([\d.]+|none)", line)
            if m and m.group(1) != "none":
                last_down_ask = float(m.group(1))

            ts_match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if ts_match:
                last_updated = ts_match.group(1)

        # Current open directional position
        if last_position_side is None and "OPEN " in line:
            m = re.search(r"OPEN (UP|DOWN) @ ([\d.]+)", line)
            if m:
                last_position_side = m.group(1)
                last_position_entry = float(m.group(2))

        # Parse DECISION events for the reason log
        if "DECISION" in line:
            m = re.search(r"DECISION (\{.*\})", line)
            if m:
                try:
                    d = json.loads(m.group(1))
                    ts_match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                    if ts_match:
                        d["_ts"] = ts_match.group(1)
                    if last_decision is None:
                        last_decision = d
                    decision_log.append(d)
                except (json.JSONDecodeError, ValueError):
                    pass

    # Count events forward through tail
    for line in tail:
        stripped = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ", "", line)
        if stripped.startswith("WIN "):
            wins += 1
        elif stripped.startswith("LOSE "):
            losses += 1
        if "ABANDONED" in line:
            abandoned += 1
        if "INSTANT_ARB" in line and "buying both" not in line and "est_net" not in line:
            instant_arbs += 1

    features: dict = {}
    if last_tfi is not None:
        features["tfi"] = round(last_tfi, 1)
        # Keep "ofi" key for backward compat with any existing dashboard logic
        features["ofi"] = round(last_tfi, 1)
    if last_obi is not None:
        features["obi"] = round(last_obi, 3)
    if last_conf is not None:
        features["confidence"] = round(last_conf, 1)
    if last_up_ask is not None:
        features["up_ask"] = last_up_ask
    if last_down_ask is not None:
        features["down_ask"] = last_down_ask
    if last_up_ask and last_down_ask:
        features["combined"] = round(last_up_ask + last_down_ask, 3)
    if last_state:
        features["state"] = last_state
    if last_position_side:
        features["position_side"] = last_position_side
        features["position_entry"] = last_position_entry
    if last_ob_shock is not None:
        features["ob_shock"] = last_ob_shock
    if last_mom is not None:
        features["momentum_score"] = last_mom

    # Last 10 DECISION events (most recent first)
    recent_decisions = list(reversed(decision_log[-10:]))

    signal = {}
    if last_decision:
        signal["last_action"] = last_decision.get("action", "")
        signal["last_reason"] = last_decision.get("reason", "")
        signal["last_score"] = last_decision.get("score")
        signal["last_ts"] = last_decision.get("_ts")
    signal["recent_decisions"] = recent_decisions

    decided = wins + losses
    return {
        "features": features,
        "signal": signal,
        "resolution": {
            "wins": wins,
            "losses": losses,
            "abandoned": abandoned,
            "instant_arbs": instant_arbs,
            "win_rate": round(wins / decided * 100, 1) if decided > 0 else 0,
        },
        "last_updated": last_updated,
    }


def _parse_paper_stats(tail: list[str]) -> dict:
    """Extract paper trader stats from log tail (backward compat)."""
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
        "signal": {},
        "resolution": {
            "predictions": predictions,
            "results": results,
            "skips": skips,
            "resolution_rate": round(results / predictions * 100, 1) if predictions > 0 else 0,
        },
        "last_updated": last_updated,
    }
