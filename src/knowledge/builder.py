"""
知识库构建与管理模块
提供知识库查询和管理功能
导入功能由 src.services.import 模块提供
"""
import logging
from pathlib import Path
from typing import Any, Optional

from src.config import settings
from src.models.knowledge import (
    KnowledgeQuery,
    KnowledgeSearchResult,
    KnowledgeType,
)
from src.services.import_ import knowledge_importer
from src.services.embedding import embedding_service
from src.services.vector import vector_compute_service

logger = logging.getLogger(__name__)


class KnowledgeBuilder:
    """知识库构建器"""
    
    def __init__(self) -> None:
        self._initialized = False
    
    async def initialize(self) -> None:
        logger.info("开始初始化知识库构建器...")
        await knowledge_importer.initialize()
        self._initialized = knowledge_importer._initialized
        logger.info("知识库构建器初始化完成")
    
    def switch_embedding_model(self, model_key: str) -> dict[str, Any]:
        return embedding_service.switch_model(model_key)
    
    def get_current_model_info(self) -> dict[str, Any]:
        return embedding_service.get_model_info()
    
    async def import_from_file(self, file_path: Path) -> dict[str, Any]:
        result = await knowledge_importer.import_file(file_path)
        return {
            "success": result.success,
            "knowledge_count": result.knowledge_count,
            "error_count": result.error_count,
            "errors": result.errors,
        }
    
    async def import_from_directory(
        self, directory_path: Path
    ) -> dict[str, Any]:
        results = await knowledge_importer.import_directory(directory_path)
        total_count = sum(r.knowledge_count for r in results)
        total_errors = sum(r.error_count for r in results)
        all_errors = []
        for r in results:
            all_errors.extend(r.errors)
        
        return {
            "success": all(r.success for r in results),
            "knowledge_count": total_count,
            "error_count": total_errors,
            "errors": all_errors,
        }
    
    async def search(self, query: KnowledgeQuery) -> list[KnowledgeSearchResult]:
        if not query.query or not self._initialized:
            return []
        
        query_embedding = embedding_service.generate_embedding(query.query)
        if not query_embedding:
            return []
        
        all_results = []
        
        for knowledge_type in [KnowledgeType.FORM_STRUCTURE, KnowledgeType.SDK_DOC]:
            results = await vector_compute_service.search(
                knowledge_type,
                query_embedding,
                k=query.limit,
                min_score=query.min_relevance,
            )
            
            for r in results:
                all_results.append(KnowledgeSearchResult(
                    knowledge_id=r.get("doc_id", ""),
                    knowledge_type=knowledge_type,
                    name=r.get("doc_title", ""),
                    description=r.get("doc_summary", ""),
                    relevance_score=r.get("score", 0),
                    source_file=r.get("doc_path"),
                ))
        
        all_results.sort(key=lambda x: x.relevance_score, reverse=True)
        return all_results[:query.limit]
    
    async def get_statistics(self) -> dict[str, Any]:
        return await knowledge_importer.get_statistics()
    
    async def rebuild_index(self) -> dict[str, Any]:
        return await knowledge_importer.rebuild_index()


class KnowledgeManager:
    """知识库管理器"""
    
    def __init__(self) -> None:
        self.builder = KnowledgeBuilder()
    
    async def initialize(self) -> None:
        await self.builder.initialize()
    
    async def import_knowledge(self, source: str) -> dict[str, Any]:
        source_path = Path(source)

        if not source_path.exists():
            return {"success": False, "message": f"源路径不存在: {source}"}

        if source_path.is_file():
            return await self.builder.import_from_file(source_path)
        elif source_path.is_dir():
            return await self.builder.import_from_directory(source_path)
        else:
            return {"success": False, "message": "无效的源路径"}

    async def query_knowledge(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        knowledge_query = KnowledgeQuery(query=query, limit=limit)
        results = await self.builder.search(knowledge_query)

        return [
            {
                "id": r.knowledge_id,
                "type": r.knowledge_type.value,
                "name": r.name,
                "description": r.description,
                "relevance": r.relevance_score,
            }
            for r in results
        ]

    async def get_statistics(self) -> dict[str, Any]:
        return await self.builder.get_statistics()


knowledge_manager = KnowledgeManager()
