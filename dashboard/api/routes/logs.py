import asyncio
import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from ..services.log_reader import read_log_lines, get_latest_log_path, parse_log_line

router = APIRouter(prefix="/api")


@router.get("/logs")
def get_logs(limit: int = 200):
    """Get recent log lines (parsed)."""
    return {"lines": read_log_lines(limit)}


@router.get("/logs/stream")
async def stream_logs():
    """SSE endpoint - streams new log lines in real time."""
    async def event_generator():
        path = get_latest_log_path()
        if not path:
            yield {"data": json.dumps({"message": "No log file", "type": "error"})}
            return

        with open(path, "r") as f:
            f.seek(0, 2)  # End of file
            while True:
                line = f.readline()
                if line:
                    parsed = parse_log_line(line.strip())
                    yield {"data": json.dumps(parsed)}
                else:
                    await asyncio.sleep(1)

    return EventSourceResponse(event_generator())
