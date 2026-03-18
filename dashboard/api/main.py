from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import trades, logs, control

app = FastAPI(title="BTC Bot Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trades.router)
app.include_router(logs.router)
app.include_router(control.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
