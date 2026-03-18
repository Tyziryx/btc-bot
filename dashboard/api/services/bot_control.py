import subprocess

BOT_DIR = "/root/bot"
SERVICE_NAME = "btc-bot"


def run_cmd(cmd: list[str], cwd: str = BOT_DIR, timeout: int = 30) -> dict:
    """Run a shell command and return result."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Command timed out"}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e)}


def bot_status() -> dict:
    """Get bot service status."""
    r = run_cmd(["systemctl", "is-active", SERVICE_NAME])
    active = r["stdout"] == "active"

    uptime = ""
    if active:
        r2 = run_cmd(["systemctl", "show", SERVICE_NAME, "--property=ActiveEnterTimestamp"])
        uptime = r2["stdout"].replace("ActiveEnterTimestamp=", "")

    return {"running": active, "uptime": uptime}


def bot_start() -> dict:
    return run_cmd(["sudo", "systemctl", "start", SERVICE_NAME])


def bot_stop() -> dict:
    return run_cmd(["sudo", "systemctl", "stop", SERVICE_NAME])


def bot_restart() -> dict:
    return run_cmd(["sudo", "systemctl", "restart", SERVICE_NAME])


def git_pull() -> dict:
    """Pull latest code, make scripts executable, show result."""
    pull = run_cmd(["git", "pull", "origin", "main"])
    if pull["success"]:
        run_cmd(["chmod", "+x", "start.sh", "stop.sh", "logs.sh", "status.sh"])
    return pull


def git_log() -> dict:
    """Get last 5 commits."""
    return run_cmd(["git", "log", "--oneline", "-5"])
