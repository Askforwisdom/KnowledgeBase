"""
统一向量检索服务
"""
import logging
from dataclasses import dataclass
from typing import Any, Optional

from src.models.knowledge import KNOWLEDGE_TYPE_CONFIGS, KnowledgeType
from src.services.vector import vector_compute_service, EmbeddingGenerator

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    doc_id: str
    doc_title: str
    doc_path: str
    doc_summary: str
    score: float
    knowledge_type: str


class VectorSearcher:
    """统一向量检索器"""
    
    def __init__(self):
        from src.services.vector import embedding_generator
        self.embedder = embedding_generator
        self._initialized = False
    
    def set_embedding_model(self, model) -> None:
        self._initialized = False
    
    async def _ensure_initialized(self) -> bool:
        if self._initialized:
            return True
        if not self.embedder.is_available():
            logger.error("嵌入模型未设置")
            return False
        await vector_compute_service.initialize()
        self._initialized = True
        return True
    
    async def search(
        self,
        query: str,
        k: int = 10,
        min_score: float = 0.3,
        knowledge_types: Optional[list[KnowledgeType]] = None,
    ) -> list[SearchResult]:
        """
        统一向量检索
        
        Args:
            query: 查询文本
            k: 返回结果数量
            min_score: 最小相似度阈值
            knowledge_types: 指定知识类型列表，为 None 时搜索所有类型
        """
        if not await self._ensure_initialized():
            return []
        
        query_embedding = self.embedder.generate(query)
        if not query_embedding:
            return []
        
        if knowledge_types is None:
            knowledge_types = list(KNOWLEDGE_TYPE_CONFIGS.keys())
        
        all_results = []
        
        for knowledge_type in knowledge_types:
            type_results = await vector_compute_service.search(
                knowledge_type=knowledge_type,
                query_embedding=query_embedding,
                k=k,
                min_score=min_score,
            )
            
            for r in type_results:
                all_results.append(SearchResult(
                    doc_id=r.get("doc_id", ""),
                    doc_title=r.get("doc_title", ""),
                    doc_path=r.get("doc_path", ""),
                    doc_summary=r.get("doc_summary", ""),
                    score=r.get("score", 0.0),
                    knowledge_type=knowledge_type.value,
                ))
        
        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results[:k]
    
    async def get_statistics(self) -> dict[str, Any]:
        return await vector_compute_service.get_statistics()


vector_searcher = VectorSearcher()
