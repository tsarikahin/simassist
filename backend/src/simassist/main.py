import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from simassist.api.dependencies import get_data_root
from simassist.api.routes.artifacts import router as artifacts_router
from simassist.api.routes.cad_geometry import router as cad_geometry_router
from simassist.api.routes.chat import router as chat_router
from simassist.api.routes.engines import router as engines_router
from simassist.api.routes.files import UploadLimitMiddleware
from simassist.api.routes.files import router as files_router
from simassist.api.routes.health import router as health_router
from simassist.api.routes.jobs import router as jobs_router
from simassist.api.routes.jobs_events import (
    router as jobs_events_router,
)
from simassist.api.routes.mesh_previews import router as mesh_previews_router
from simassist.api.routes.mesh_quality import router as mesh_quality_router
from simassist.api.routes.mesh_versions import router as mesh_versions_router
from simassist.api.routes.projects import router as projects_router
from simassist.api.routes.workspace import router as workspace_router

logger = logging.getLogger("simassist")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API runtime data root: %s", get_data_root())
    yield


app = FastAPI(
    title="SimAssist API",
    version="0.1.0",
    description="Local AI-powered simulation platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type"],
    expose_headers=["Server-Timing", "Content-Length", "X-Preview-Cache"],
)
app.add_middleware(UploadLimitMiddleware)

app.include_router(health_router)
app.include_router(engines_router)
app.include_router(artifacts_router)
app.include_router(jobs_router)
app.include_router(mesh_previews_router)
app.include_router(mesh_versions_router)
app.include_router(mesh_quality_router)
app.include_router(chat_router)
app.include_router(cad_geometry_router)
app.include_router(jobs_events_router)
app.include_router(projects_router)
app.include_router(workspace_router)
app.include_router(files_router)
