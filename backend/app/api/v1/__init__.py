from fastapi import APIRouter

from app.api.v1.auth import auth_router
from app.api.v1.endpoints import router as health_router
from app.api.v1.github import github_router
from app.api.v1.graph import graph_router
from app.api.v1.indexing import indexing_router
from app.api.v1.semantic import semantic_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(github_router)
api_router.include_router(indexing_router)
api_router.include_router(semantic_router)
api_router.include_router(graph_router)
