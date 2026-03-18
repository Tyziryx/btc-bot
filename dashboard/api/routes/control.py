from fastapi import APIRouter
from ..services.bot_control import (
    bot_status, bot_start, bot_stop, bot_restart, git_pull, git_log
)

router = APIRouter(prefix="/api/bot")


@router.get("/status")
def get_status():
    return bot_status()


@router.post("/start")
def start():
    return bot_start()


@router.post("/stop")
def stop():
    return bot_stop()


@router.post("/restart")
def restart():
    return bot_restart()


@router.post("/pull")
def pull():
    return git_pull()


@router.get("/commits")
def commits():
    return git_log()
