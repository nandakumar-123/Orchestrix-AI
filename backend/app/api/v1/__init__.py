from fastapi import APIRouter

from app.api.v1.auth import auth_router
from app.api.v1.devmemory import devmemory_router
from app.api.v1.devpilot import devpilot_router
from app.api.v1.endpoints import router as health_router
from app.api.v1.flowforge import flowforge_router
from app.api.v1.github import github_router
from app.api.v1.graph import graph_router
from app.api.v1.impact import impact_router
from app.api.v1.indexing import indexing_router
from app.api.v1.secureflow import secureflow_router
from app.api.v1.semantic import semantic_router
from app.api.v1.testpilot import testpilot_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(github_router)
api_router.include_router(indexing_router)
api_router.include_router(semantic_router)
api_router.include_router(graph_router)
api_router.include_router(impact_router)
api_router.include_router(devpilot_router)
api_router.include_router(testpilot_router)
api_router.include_router(secureflow_router)
api_router.include_router(flowforge_router)
api_router.include_router(devmemory_router)
