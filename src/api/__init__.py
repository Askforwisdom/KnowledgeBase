"""
API服务模块
整合所有API路由
"""
from fastapi import APIRouter

from src.api.knowledge import router as knowledge_router

router = APIRouter()

router.include_router(knowledge_router)

__all__ = ["router"]
