from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from simassist.api.routes.artifacts import router as artifacts_router
from simassist.api.routes.engines import router as engines_router
from simassist.api.routes.health import router as health_router

app = FastAPI(
    title="SimAssist API",
    version="0.1.0",
    description="Local AI-powered simulation platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(health_router)
app.include_router(engines_router)
app.include_router(artifacts_router)
