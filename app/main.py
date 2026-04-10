from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers.analysis import router as analysis_router
from app.routers.health import router as health_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger(__name__).info(
        "Docu-Jarvis backend starting. Binary: %s", settings.docu_jarvis_binary
    )
    yield
    logging.getLogger(__name__).info("Docu-Jarvis backend shutting down.")


app = FastAPI(
    title="Docu-Jarvis API",
    description="AI-powered Go code analysis: security, impact, why, debug, explain.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis_router)
app.include_router(health_router)
