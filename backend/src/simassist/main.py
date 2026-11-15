from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from simassist.api.routes.artifacts import router as artifacts_router
from simassist.api.routes.chat import router as chat_router
from simassist.api.routes.engines import router as engines_router
from simassist.api.routes.health import router as health_router
from simassist.api.routes.jobs import router as jobs_router
from simassist.api.routes.jobs_events import (
    router as jobs_events_router,
)
from simassist.api.routes.mesh_previews import router as mesh_previews_router
from simassist.api.routes.projects import router as projects_router

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
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(health_router)
app.include_router(engines_router)
app.include_router(artifacts_router)
app.include_router(jobs_router)
app.include_router(mesh_previews_router)
app.include_router(chat_router)
app.include_router(jobs_events_router)
app.include_router(projects_router)
