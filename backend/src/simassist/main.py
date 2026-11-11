
from fastapi import FastAPI

from simassist.api.routes.health import router as health_router

app = FastAPI(
    title="SimAssist API",
    version="0.1.0",
)

app.include_router(health_router)
