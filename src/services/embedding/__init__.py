"""
嵌入模型服务模块
提供统一的嵌入模型管理
"""
from src.services.embedding.service import EmbeddingService, embedding_service

__all__ = [
    "EmbeddingService",
    "embedding_service",
]
