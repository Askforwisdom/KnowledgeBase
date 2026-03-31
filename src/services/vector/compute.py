"""
向量模块
包含向量服务和嵌入向量生成器
支持LRU缓存和按需加载
"""
import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from src.config import settings
from src.models.knowledge import (
    KnowledgeType,
    KnowledgeTypeConfig,
    VectorFieldType,
    KNOWLEDGE_TYPE_CONFIGS,
    get_knowledge_type_by_path,
    get_knowledge_type_config,
)
from src.services.vector.store import VectorStore
from src.services.vector.chunker import text_chunker
from src.services.embedding import embedding_service

logger = logging.getLogger(__name__)


class VectorData:
    """向量数据"""
    def __init__(
        self,
        doc_id: str,
        doc_title: str,
        doc_path: str,
        doc_summary: str,
        content_for_embedding: str,
        source_file: Optional[str] = None,
    ):
        self.doc_id = doc_id
        self.doc_title = doc_title
        self.doc_path = doc_path
        self.doc_summary = doc_summary
        self.content_for_embedding = content_for_embedding
        self.source_file = source_file


class LRUCache:
    """LRU缓存实现"""
    
    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self._cache: OrderedDict = OrderedDict()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[list[float]]:
        if key in self._cache:
            self._cache.move_to_end(key)
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None
    
    def set(self, key: str, value: list[float]) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        while len(self._cache) > self.max_size:
            self._cache.popitem(last=False)
    
    def __contains__(self, key: str) -> bool:
        return key in self._cache
    
    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0
    
    def get_stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
        }


class EmbeddingGenerator:
    """嵌入向量生成器 - 从 EmbeddingService 获取模型，支持LRU缓存"""
    
    def __init__(self, cache_size: int = None):
        cache_size = cache_size or getattr(settings, 'embedding_cache_size', 10000)
        self._cache = LRUCache(max_size=cache_size)
    
    @property
    def model(self):
        return embedding_service.model
    
    def generate(self, text: str) -> Optional[list[float]]:
        if not self.model:
            return None
        
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        
        try:
            embedding = self.model.encode(text, convert_to_numpy=True)
            embedding_list = embedding.tolist()
            self._cache.set(text, embedding_list)
            return embedding_list
        except Exception as e:
            logger.error(f"生成嵌入向量失败: {e}", exc_info=True)
            return None
    
    def generate_batch(self, texts: list[str], batch_size: int = None) -> list[Optional[list[float]]]:
        if batch_size is None:
            batch_size = settings.embedding_batch_size
        if not self.model:
            return [None] * len(texts)
        
        results = [None] * len(texts)
        uncached_texts = []
        uncached_indices = []
        
        for i, text in enumerate(texts):
            cached = self._cache.get(text)
            if cached is not None:
                results[i] = cached
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)
        
        if uncached_texts:
            try:
                embeddings = self.model.encode(uncached_texts, batch_size=batch_size, convert_to_numpy=True)
                for j, (text, embedding) in enumerate(zip(uncached_texts, embeddings)):
                    embedding_list = embedding.tolist()
                    self._cache.set(text, embedding_list)
                    results[uncached_indices[j]] = embedding_list
            except Exception as e:
                logger.error(f"批量生成嵌入向量失败: {e}", exc_info=True)
        
        return results
    
    def clear_cache(self) -> None:
        self._cache.clear()
    
    def get_cache_stats(self) -> dict[str, Any]:
        return self._cache.get_stats()
    
    def is_available(self) -> bool:
        return self.model is not None


class LazySummaryLoader:
    """摘要延迟加载器 - 按需加载摘要数据"""
    
    def __init__(self, max_cache_types: int = 10):
        self._summaries_cache: dict[KnowledgeType, list[dict[str, Any]]] = {}
        self._loaded_types: set[KnowledgeType] = set()
        self._configs: dict[KnowledgeType, KnowledgeTypeConfig] = {}
        self._max_cache_types = max_cache_types
    
    def register_config(self, knowledge_type: KnowledgeType, config: KnowledgeTypeConfig) -> None:
        self._configs[knowledge_type] = config
    
    def _ensure_loaded(self, knowledge_type: KnowledgeType) -> bool:
        if knowledge_type in self._loaded_types:
            return True
        
        config = self._configs.get(knowledge_type)
        if not config or not config.summary_file:
            return False
        
        if len(self._loaded_types) >= self._max_cache_types:
            oldest_type = next(iter(self._loaded_types))
            if oldest_type in self._summaries_cache:
                del self._summaries_cache[oldest_type]
            self._loaded_types.discard(oldest_type)
        
        summary_path = config.get_summary_path(settings.data_dir)
        if summary_path and summary_path.exists():
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    self._summaries_cache[knowledge_type] = json.load(f)
                self._loaded_types.add(knowledge_type)
                logger.info(f"延迟加载 {knowledge_type.value} 摘要: {len(self._summaries_cache[knowledge_type])} 条")
                return True
            except Exception as e:
                logger.error(f"加载摘要文件失败: {summary_path}", exc_info=True)
                self._summaries_cache[knowledge_type] = []
                return False
        
        self._summaries_cache[knowledge_type] = []
        return False
    
    def get_summaries(self, knowledge_type: KnowledgeType) -> list[dict[str, Any]]:
        self._ensure_loaded(knowledge_type)
        return self._summaries_cache.get(knowledge_type, [])
    
    def find_summary(self, knowledge_type: KnowledgeType, doc_id: str = None, doc_title: str = None) -> Optional[dict]:
        summaries = self.get_summaries(knowledge_type)
        for summary in summaries:
            if doc_id and summary.get("doc_id") == doc_id:
                return summary
            if doc_title and summary.get("doc_title") == doc_title:
                return summary
        return None
    
    def clear(self) -> None:
        self._summaries_cache.clear()
        self._loaded_types.clear()


class VectorComputeService:
    """统一向量计算服务"""
    
    def __init__(self):
        self._vector_stores: dict[KnowledgeType, VectorStore] = {}
        self._summary_loader = LazySummaryLoader()
        self._initialized = False
    
    async def initialize(self) -> bool:
        if self._initialized:
            return True
        for knowledge_type, config in KNOWLEDGE_TYPE_CONFIGS.items():
            index_path = config.get_index_path(settings.data_dir)
            store = VectorStore(dimension=settings.embedding_dimension, index_path=index_path)
            await store.initialize()
            self._vector_stores[knowledge_type] = store
            
            if config.vector_field == VectorFieldType.SUMMARY and config.summary_file:
                self._summary_loader.register_config(knowledge_type, config)
        
        self._initialized = True
        logger.info("向量计算服务初始化完成")
        return True
    
    def get_knowledge_type(self, file_path: str) -> Optional[KnowledgeType]:
        return get_knowledge_type_by_path(file_path)
    
    def get_vector_data_for_file(self, file_path: str) -> Optional[VectorData]:
        knowledge_type = self.get_knowledge_type(file_path)
        if not knowledge_type:
            return None
        config = get_knowledge_type_config(knowledge_type)
        if not config:
            return None
        path = Path(file_path)
        file_name = config.get_file_name(file_path)
        if config.vector_field == VectorFieldType.FILE_NAME:
            return VectorData(
                doc_id=file_name,
                doc_title=file_name,
                doc_path=str(path),
                doc_summary=file_name,
                content_for_embedding=file_name,
                source_file=str(path),
            )
        elif config.vector_field == VectorFieldType.SUMMARY:
            summary = self._summary_loader.find_summary(knowledge_type, doc_id=file_name, doc_title=file_name)
            if summary:
                return VectorData(
                    doc_id=summary.get("doc_id", file_name),
                    doc_title=summary.get("doc_title", file_name),
                    doc_path=summary.get("doc_path", str(path)),
                    doc_summary=summary.get("summary", ""),
                    content_for_embedding=summary.get("summary", ""),
                    source_file=str(path),
                )
            return None
        return None
    
    def get_all_vector_data_for_type(self, knowledge_type: KnowledgeType) -> list[VectorData]:
        config = get_knowledge_type_config(knowledge_type)
        if not config:
            return []
        result = []
        if config.vector_field == VectorFieldType.SUMMARY:
            summaries = self._summary_loader.get_summaries(knowledge_type)
            for summary in summaries:
                result.append(VectorData(
                    doc_id=summary.get("doc_id", ""),
                    doc_title=summary.get("doc_title", ""),
                    doc_path=summary.get("doc_path", ""),
                    doc_summary=summary.get("summary", ""),
                    content_for_embedding=summary.get("summary", ""),
                ))
        return result
    
    def get_vector_store(self, knowledge_type: KnowledgeType) -> Optional[VectorStore]:
        return self._vector_stores.get(knowledge_type)
    
    def get_chunked_data(self, vector_data: VectorData) -> list[dict]:
        return text_chunker.chunk_with_metadata(
            doc_id=vector_data.doc_id,
            doc_title=vector_data.doc_title,
            doc_path=vector_data.doc_path,
            doc_summary=vector_data.doc_summary,
            content_for_embedding=vector_data.content_for_embedding,
        )
    
    async def add_vector(self, knowledge_type: KnowledgeType, vector_data: VectorData, embedding: list[float], chunk_id: str = None) -> bool:
        store = self.get_vector_store(knowledge_type)
        if not store:
            return False
        doc_id = chunk_id or vector_data.doc_id
        metadata = {
            "doc_id": vector_data.doc_id,
            "doc_title": vector_data.doc_title,
            "doc_path": vector_data.doc_path,
            "doc_summary": vector_data.doc_summary,
        }
        return await store.add_document(
            doc_id=doc_id,
            content=vector_data.content_for_embedding,
            embedding=embedding,
            metadata=metadata,
        )
    
    async def add_vector_with_chunking(
        self,
        knowledge_type: KnowledgeType,
        vector_data: VectorData,
        embedder: EmbeddingGenerator,
    ) -> tuple[int, int]:
        store = self.get_vector_store(knowledge_type)
        if not store:
            return 0, 1
        
        chunks = self.get_chunked_data(vector_data)
        if not chunks:
            return 0, 1
        
        if len(chunks) == 1:
            embedding = embedder.generate(chunks[0]["content_for_embedding"])
            if embedding and await self.add_vector(knowledge_type, vector_data, embedding):
                return 1, 0
            return 0, 1
        
        success_count = 0
        error_count = 0
        
        contents = [c["content_for_embedding"] for c in chunks]
        embeddings = embedder.generate_batch(contents)
        
        for chunk, embedding in zip(chunks, embeddings):
            if embedding:
                chunk_data = VectorData(
                    doc_id=vector_data.doc_id,
                    doc_title=vector_data.doc_title,
                    doc_path=vector_data.doc_path,
                    doc_summary=vector_data.doc_summary,
                    content_for_embedding=chunk["content_for_embedding"],
                )
                if await self.add_vector(knowledge_type, chunk_data, embedding, chunk["chunk_id"]):
                    success_count += 1
                else:
                    error_count += 1
            else:
                error_count += 1
        
        return success_count, error_count
    
    async def search(self, knowledge_type: KnowledgeType, query_embedding: list[float], k: int = 10, min_score: float = 0.0) -> list[dict[str, Any]]:
        store = self.get_vector_store(knowledge_type)
        if not store:
            return []
        results = await store.search_with_content(query_embedding=query_embedding, k=k, min_score=min_score)
        formatted_results = []
        for result in results:
            metadata = result.get("metadata", {})
            formatted_results.append({
                "doc_id": metadata.get("doc_id"),
                "doc_title": metadata.get("doc_title"),
                "doc_path": metadata.get("doc_path"),
                "doc_summary": metadata.get("doc_summary"),
                "score": result.get("score", 0.0),
            })
        return formatted_results
    
    async def build_index_for_type(self, knowledge_type: KnowledgeType, embedder: EmbeddingGenerator, batch_size: int = None) -> dict[str, Any]:
        if batch_size is None:
            batch_size = settings.import_batch_size
        config = get_knowledge_type_config(knowledge_type)
        if not config:
            return {"success": False, "error": "未知知识类型"}
        store = self.get_vector_store(knowledge_type)
        if not store:
            return {"success": False, "error": "向量库未初始化"}
        if not embedder or not embedder.is_available():
            return {"success": False, "error": "嵌入模型不可用"}
        vector_data_list = self.get_all_vector_data_for_type(knowledge_type)
        if not vector_data_list:
            return {"success": False, "error": "无向量数据"}
        
        stats = {"total": len(vector_data_list), "success": 0, "failed": 0}
        await store.clear()
        store.begin_batch()
        
        for vector_data in vector_data_list:
            success, failed = await self.add_vector_with_chunking(knowledge_type, vector_data, embedder)
            stats["success"] += success
            stats["failed"] += failed
        
        await store.end_batch()
        logger.info(f"{knowledge_type.value} 向量索引构建完成: {stats}")
        return {"success": True, "stats": stats}
    
    async def get_statistics(self) -> dict[str, Any]:
        total_count = 0
        by_type = {}
        
        for knowledge_type, store in self._vector_stores.items():
            store_stats = await store.get_statistics()
            count = store_stats.get("total_chunks", 0)
            by_type[knowledge_type.value] = count
            total_count += count
        
        return {
            "total_count": total_count,
            "faiss_chunks": total_count,
            "by_type": by_type,
            "by_source": {},
        }
    
    async def clear_all(self) -> None:
        for knowledge_type, store in self._vector_stores.items():
            await store.clear()
        logger.info("所有向量库已清空")


embedding_generator = EmbeddingGenerator()
vector_compute_service = VectorComputeService()
