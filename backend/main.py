from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import tasks
from backend.db import init_db

app = FastAPI(title="QuantumSwarm API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router, prefix="/api")


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/health")
async def health():
    return {"status": "ok"}
