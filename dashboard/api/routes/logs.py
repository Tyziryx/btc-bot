import asyncio
import json
import time
from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse
from ..services.log_reader import read_log_lines, get_latest_log_path, parse_log_line

router = APIRouter(prefix="/api")


@router.get("/logs")
def get_logs(limit: int = 200, type: str | None = Query(None)):
    """Get recent log lines (parsed), optionally filtered by type."""
    lines = read_log_lines(limit)
    if type:
        allowed = set(type.split(","))
        lines = [l for l in lines if l["type"] in allowed]
    return {"lines": lines}


@router.get("/logs/stream")
async def stream_logs():
    """SSE endpoint - streams new log lines with 30s heartbeat."""
    async def event_generator():
        path = get_latest_log_path()
        if not path:
            yield {"data": json.dumps({"message": "No log file", "type": "error"})}
            return

        with open(path, "r") as f:
            f.seek(0, 2)
            last_heartbeat = time.time()
            while True:
                line = f.readline()
                if line:
                    parsed = parse_log_line(line.strip())
                    yield {"data": json.dumps(parsed)}
                    last_heartbeat = time.time()
                else:
                    if time.time() - last_heartbeat > 30:
                        yield {"comment": "keepalive"}
                        last_heartbeat = time.time()
                    await asyncio.sleep(1)

    return EventSourceResponse(event_generator())
