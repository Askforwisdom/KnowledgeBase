"""
向量存储模块
支持多种向量库后端的向量存储管理器
包含批量写入优化和异步提交功能
线程安全实现 - 默认使用批量模式减少锁竞争
"""
import asyncio
import json
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import threading

from pydantic import BaseModel, Field

from src.config import settings
from src.services.vector.backend import VectorBackendFactory
from src.services.vector import backends

logger = logging.getLogger(__name__)

_file_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vector_io")


class VectorDocument(BaseModel):
    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[list[float]] = None
    created_at: datetime = Field(default_factory=datetime.now)
    deleted: bool = Field(default=False, description="软删除标记")
    deleted_at: Optional[datetime] = None


class AsyncCommitBuffer:
    """异步提交缓冲区 - 线程安全"""
    
    def __init__(
        self,
        batch_size: int = None,
        delay_ms: int = None,
        commit_callback: callable = None,
    ):
        self.batch_size = batch_size or settings.async_commit_batch_size
        self.delay_ms = delay_ms or settings.async_commit_delay_ms
        self.commit_callback = commit_callback
        self._buffer: deque = deque()
        self._lock = asyncio.Lock()
        self._commit_task: Optional[asyncio.Task] = None
        self._pending_commit = False
        self._last_commit_time = 0.0
    
    async def add(self, doc: dict) -> bool:
        async with self._lock:
            self._buffer.append(doc)
            
            if len(self._buffer) >= self.batch_size:
                return await self._flush()
            
            self._schedule_delayed_commit()
            return True
    
    async def add_batch(self, docs: list[dict]) -> int:
        async with self._lock:
            self._buffer.extend(docs)
            
            if len(self._buffer) >= self.batch_size:
                await self._flush()
            else:
                self._schedule_delayed_commit()
            
            return len(docs)
    
    def _schedule_delayed_commit(self) -> None:
        if self._pending_commit:
            return
        
        self._pending_commit = True
        
        async def delayed_commit():
            await asyncio.sleep(self.delay_ms / 1000.0)
            async with self._lock:
                if self._buffer:
                    await self._flush()
                self._pending_commit = False
        
        if asyncio.get_event_loop().is_running():
            asyncio.create_task(delayed_commit())
    
    async def _flush(self) -> bool:
        if not self._buffer or not self.commit_callback:
            return True
        
        docs_to_commit = list(self._buffer)
        self._buffer.clear()
        
        try:
            result = await self.commit_callback(docs_to_commit)
            self._last_commit_time = asyncio.get_event_loop().time()
            return result
        except Exception as e:
            logger.error(f"异步提交失败: {e}")
            self._buffer.extendleft(reversed(docs_to_commit))
            return False
    
    async def flush(self) -> bool:
        async with self._lock:
            return await self._flush()
    
    async def wait_pending(self) -> None:
        while self._buffer or self._pending_commit:
            await asyncio.sleep(0.01)
    
    def get_pending_count(self) -> int:
        return len(self._buffer)


class VectorStore:
    """向量库 - 支持多种后端，优化批量写入，线程安全
    默认使用批量模式减少锁竞争，提升高并发写入性能
    """
    
    def __init__(
        self,
        dimension: int = 1024,
        index_path: Optional[Path] = None,
        backend_name: Optional[str] = None,
        auto_batch: bool = True,
        auto_flush_size: int = None,
        auto_flush_delay_ms: int = None,
    ):
        self.dimension = dimension
        self.index_path = index_path or settings.data_dir / "vector_index"
        self.backend_name = backend_name or settings.vector_backend
        self.backend = None
        self.documents: dict[str, VectorDocument] = {}
        self.id_to_idx: dict[str, int] = {}
        self.idx_to_id: dict[int, str] = {}
        self._initialized = False
        self._batch_mode = False
        self._pending_save = False
        
        self._auto_batch = auto_batch
        self._auto_flush_size = auto_flush_size or settings.import_batch_size
        self._auto_flush_delay_ms = auto_flush_delay_ms or settings.async_commit_delay_ms
        
        self._write_buffer: list[dict] = []
        self._buffer_size = settings.import_batch_size
        self._async_buffer: Optional[AsyncCommitBuffer] = None
        
        self._write_lock = asyncio.Lock()
        self._read_lock = asyncio.Lock()
        self._thread_lock = threading.RLock()
        self._save_semaphore = asyncio.Semaphore(1)
        
        self._auto_flush_task: Optional[asyncio.Task] = None
        self._last_write_time: float = 0.0
    
    async def initialize(self) -> bool:
        async with self._write_lock:
            if self._initialized:
                return True
            
            self.backend = VectorBackendFactory.create(
                backend_name=self.backend_name,
                dimension=self.dimension,
                index_path=self.index_path,
            )
            
            if not self.backend:
                available = VectorBackendFactory.get_available_backends()
                logger.warning(f"向量库后端 {self.backend_name} 不可用，可用后端: {available}")
                return False
            
            if not await self.backend.initialize():
                logger.warning(f"初始化向量库后端 {self.backend_name} 失败")
                return False
            
            self._load_documents()
            self._initialized = True
            
            self._async_buffer = AsyncCommitBuffer(
                batch_size=settings.async_commit_batch_size,
                delay_ms=settings.async_commit_delay_ms,
                commit_callback=self._async_commit_callback,
            )
            
            if self._auto_batch:
                self._batch_mode = True
                self._start_auto_flush()
            
            return True
    
    def _start_auto_flush(self) -> None:
        """启动自动刷新任务"""
        async def auto_flush_loop():
            while self._auto_batch and self._initialized:
                await asyncio.sleep(self._auto_flush_delay_ms / 1000.0)
                
                if self._write_buffer and self._last_write_time > 0:
                    import time
                    if (time.time() - self._last_write_time) * 1000 >= self._auto_flush_delay_ms:
                        async with self._write_lock:
                            if self._write_buffer:
                                await self._flush_write_buffer()
                                await self._do_save()
        
        try:
            if asyncio.get_event_loop().is_running():
                self._auto_flush_task = asyncio.create_task(auto_flush_loop())
        except Exception:
            pass
    
    async def _async_commit_callback(self, docs: list[dict]) -> bool:
        async with self._save_semaphore:
            try:
                await self._save_index_async()
                await self._save_documents_async()
                return True
            except Exception as e:
                logger.error(f"异步提交回调失败: {e}")
                return False
    
    def begin_batch(self) -> None:
        self._batch_mode = True
        self._pending_save = False
        self._write_buffer = []
    
    async def end_batch(self) -> None:
        async with self._write_lock:
            if self._write_buffer:
                await self._flush_write_buffer()
            
            if self._pending_save:
                await self._do_save()
            
            if self._auto_batch:
                self._batch_mode = True
            else:
                self._batch_mode = False
    
    async def _do_save(self) -> None:
        """执行保存操作"""
        async with self._save_semaphore:
            await self._save_index()
            await self._save_documents(skip_semaphore=True)
        self._pending_save = False
    
    def _load_documents(self) -> None:
        with self._thread_lock:
            try:
                doc_file = self.index_path / "documents.json"
                if doc_file.exists():
                    with open(doc_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self.documents = {k: VectorDocument(**v) for k, v in data.get("documents", {}).items()}
                        self.id_to_idx = data.get("id_to_idx", {})
                        self.idx_to_id = {int(k): v for k, v in data.get("idx_to_id", {}).items()}
            except Exception as e:
                logger.error(f"加载文档数据失败: {e}", exc_info=True)
    
    async def _save_index(self) -> None:
        if self._batch_mode:
            self._pending_save = True
            return
        if self.backend:
            await self.backend.save_index()
    
    async def _save_index_async(self) -> None:
        if self.backend:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_file_executor, self._save_index_sync)
    
    def _save_index_sync(self) -> None:
        with self._thread_lock:
            if self.backend and hasattr(self.backend, 'save_index'):
                import asyncio
                asyncio.run(self.backend.save_index())
    
    async def _save_documents(self, skip_semaphore: bool = False) -> None:
        if self._batch_mode:
            self._pending_save = True
            return
        
        async def _do_save_documents_inner() -> None:
            """内部保存方法，已持有信号量"""
            try:
                self.index_path.mkdir(parents=True, exist_ok=True)
                doc_file = self.index_path / "documents.json"
                
                with self._thread_lock:
                    data = {
                        "documents": {k: v.model_dump(mode="json") for k, v in self.documents.items()},
                        "id_to_idx": self.id_to_idx.copy(),
                        "idx_to_id": {str(k): v for k, v in self.idx_to_id.items()},
                    }
                
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    _file_executor,
                    self._write_json_file,
                    doc_file,
                    data
                )
            except Exception as e:
                logger.error(f"保存文档数据失败: {e}", exc_info=True)
        
        if skip_semaphore:
            await _do_save_documents_inner()
        else:
            async with self._save_semaphore:
                await _do_save_documents_inner()
    
    async def _save_documents_async(self) -> None:
        await self._save_documents()
    
    def _write_json_file(self, file_path: Path, data: dict) -> None:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    async def _flush_write_buffer(self) -> None:
        if not self._write_buffer:
            return
        
        docs_to_write = self._write_buffer.copy()
        self._write_buffer = []
        
        if not self.backend or not docs_to_write:
            return
        
        try:
            embeddings_to_add = []
            
            for doc_data in docs_to_write:
                doc_id = doc_data["doc_id"]
                
                if doc_id in self.documents:
                    del self.documents[doc_id]
                
                doc = VectorDocument(
                    id=doc_id,
                    content=doc_data["content"],
                    metadata=doc_data.get("metadata", {}),
                    embedding=doc_data["embedding"],
                )
                idx = len(self.documents)
                self.id_to_idx[doc_id] = idx
                self.idx_to_id[idx] = doc_id
                self.documents[doc_id] = doc
                embeddings_to_add.append(doc_data["embedding"])
            
            if embeddings_to_add:
                await self.backend.add_vectors(embeddings_to_add)
            
            self._pending_save = True
            
        except Exception as e:
            logger.error(f"刷新写入缓冲区失败: {e}", exc_info=True)
    
    async def add_document(
        self,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        async with self._write_lock:
            if not self._initialized:
                await self.initialize()
            
            if not self.backend:
                return False
            
            try:
                self._write_buffer.append({
                    "doc_id": doc_id,
                    "content": content,
                    "embedding": embedding,
                    "metadata": metadata or {},
                })
                
                import time
                self._last_write_time = time.time()
                
                if len(self._write_buffer) >= self._buffer_size:
                    await self._flush_write_buffer()
                    if not self._batch_mode:
                        await self._do_save()
                
                return True
            except Exception as e:
                logger.error(f"添加文档失败: {e}", exc_info=True)
                return False
    
    async def add_documents_batch(self, docs: list[dict[str, Any]], force: bool = False) -> int:
        async with self._write_lock:
            if not self._initialized:
                await self.initialize()
            
            if not self.backend or not docs:
                return 0
            
            try:
                for doc_data in docs:
                    doc_id = doc_data["doc_id"]
                    if not force and doc_id in self.documents:
                        continue
                    
                    if force and doc_id in self.documents:
                        del self.documents[doc_id]
                    
                    self._write_buffer.append(doc_data)
                
                import time
                self._last_write_time = time.time()
                
                if len(self._write_buffer) >= self._buffer_size:
                    await self._flush_write_buffer()
                    if not self._batch_mode:
                        await self._do_save()
                
                return len(docs)
            except Exception as e:
                logger.error(f"批量添加文档失败: {e}", exc_info=True)
                return 0
    
    async def flush(self) -> bool:
        """手动刷新缓冲区并保存"""
        async with self._write_lock:
            if self._write_buffer:
                await self._flush_write_buffer()
            
            was_batch_mode = self._batch_mode
            self._batch_mode = False
            
            if self._pending_save:
                await self._do_save()
            
            self._batch_mode = was_batch_mode
            return True
    
    async def add_documents_streaming(
        self,
        docs_iterator,
        batch_size: int = None,
        progress_callback: callable = None,
    ) -> int:
        if not self._initialized:
            await self.initialize()
        
        batch_size = batch_size or self._buffer_size
        total_added = 0
        batch = []
        
        was_batch_mode = self._batch_mode
        self._batch_mode = True
        
        try:
            for doc in docs_iterator:
                batch.append(doc)
                
                if len(batch) >= batch_size:
                    added = await self.add_documents_batch(batch)
                    total_added += added
                    batch = []
                    
                    if progress_callback:
                        progress_callback(total_added)
            
            if batch:
                added = await self.add_documents_batch(batch)
                total_added += added
                
                if progress_callback:
                    progress_callback(total_added)
            
            await self.flush()
            
        except Exception as e:
            logger.error(f"流式批量添加失败: {e}", exc_info=True)
            await self.flush()
            raise
        finally:
            self._batch_mode = was_batch_mode if not self._auto_batch else True
        
        return total_added
    
    async def _delete_document_unsafe(self, doc_id: str, hard: bool = False) -> bool:
        """内部删除方法 - 必须在持有锁时调用
        软删除：只标记删除，不重建索引，性能更高
        硬删除：真正删除并重建索引
        """
        if doc_id not in self.documents:
            return True
        
        try:
            doc = self.documents[doc_id]
            
            if hard:
                idx = self.id_to_idx.get(doc_id)
                if idx is not None:
                    await self.backend.clear()
                    
                    for existing_id, d in self.documents.items():
                        if existing_id != doc_id and d.embedding and not d.deleted:
                            await self.backend.add_vectors([d.embedding])
                    
                    del self.documents[doc_id]
                    del self.id_to_idx[doc_id]
                    del self.idx_to_id[idx]
                    
                    self.id_to_idx = {}
                    self.idx_to_id = {}
                    for i, existing_id in enumerate(self.documents.keys()):
                        self.id_to_idx[existing_id] = i
                        self.idx_to_id[i] = existing_id
            else:
                doc.deleted = True
                doc.deleted_at = datetime.now()
                self.documents[doc_id] = doc
            
            self._pending_save = True
            return True
        except Exception as e:
            logger.error(f"删除文档失败: {e}", exc_info=True)
            return False
    
    async def delete_document(self, doc_id: str, hard: bool = False) -> bool:
        """删除文档
        Args:
            doc_id: 文档ID
            hard: 是否硬删除，默认软删除
        """
        async with self._write_lock:
            if not self._initialized or doc_id not in self.documents:
                return True
            return await self._delete_document_unsafe(doc_id, hard=hard)
    
    async def delete_knowledge_chunks(self, knowledge_id: str, hard: bool = False) -> int:
        """删除知识的所有分块
        Args:
            knowledge_id: 知识ID
            hard: 是否硬删除，默认软删除
        """
        async with self._write_lock:
            if not self._initialized:
                return 0
            chunk_ids = [
                doc_id for doc_id, doc in self.documents.items()
                if doc.metadata.get("doc_id") == knowledge_id and not doc.deleted
            ]
            deleted_count = 0
            for chunk_id in chunk_ids:
                if await self._delete_document_unsafe(chunk_id, hard=hard):
                    deleted_count += 1
            return deleted_count
    
    async def restore_document(self, doc_id: str) -> bool:
        """恢复软删除的文档"""
        async with self._write_lock:
            if doc_id not in self.documents:
                return False
            doc = self.documents[doc_id]
            if not doc.deleted:
                return True
            doc.deleted = False
            doc.deleted_at = None
            self.documents[doc_id] = doc
            self._pending_save = True
            return True
    
    async def purge_deleted(self) -> int:
        """清理所有软删除的文档，执行硬删除"""
        async with self._write_lock:
            deleted_ids = [
                doc_id for doc_id, doc in self.documents.items()
                if doc.deleted
            ]
            count = 0
            for doc_id in deleted_ids:
                if await self._delete_document_unsafe(doc_id, hard=True):
                    count += 1
            return count
    
    async def search_with_content(
        self,
        query_embedding: list[float],
        k: int = 10,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        async with self._read_lock:
            if not self._initialized or not self.backend:
                return []
            
            try:
                results = await self.backend.search(query_embedding, k * 2)
                
                formatted_results = []
                for idx, score in results:
                    if score < min_score:
                        continue
                    
                    doc_id = self.idx_to_id.get(idx)
                    if not doc_id or doc_id not in self.documents:
                        continue
                    
                    doc = self.documents[doc_id]
                    
                    if doc.deleted:
                        continue
                    
                    formatted_results.append({
                        "chunk_id": doc_id,
                        "content": doc.content,
                        "score": float(score),
                        "metadata": doc.metadata.copy(),
                    })
                    
                    if len(formatted_results) >= k:
                        break
                
                return formatted_results
            except Exception as e:
                logger.error(f"向量搜索失败: {e}", exc_info=True)
                return []
    
    async def get_statistics(self) -> dict[str, Any]:
        async with self._read_lock:
            if not self._initialized:
                return {"total_chunks": 0}
            active_count = sum(1 for d in self.documents.values() if not d.deleted)
            deleted_count = sum(1 for d in self.documents.values() if d.deleted)
            return {
                "total_chunks": active_count,
                "deleted_chunks": deleted_count,
                "pending_writes": len(self._write_buffer),
                "batch_mode": self._batch_mode,
            }
    
    async def clear(self) -> bool:
        async with self._write_lock:
            if not self.backend:
                return True
            
            try:
                await self.backend.clear()
                self.documents.clear()
                self.id_to_idx.clear()
                self.idx_to_id.clear()
                self._write_buffer.clear()
                self._pending_save = True
                return True
            except Exception as e:
                logger.error(f"清空向量库失败: {e}", exc_info=True)
                return False
    
    def get_backend_name(self) -> str:
        return self.backend_name
    
    async def close(self) -> None:
        """关闭向量库，刷新所有待写入数据"""
        if self._auto_flush_task:
            self._auto_flush_task.cancel()
        
        await self.flush()
        
        if self._async_buffer:
            await self._async_buffer.wait_pending()


class VectorStoreManager:
    """向量存储管理器"""
    
    def __init__(self):
        self.vector_store = vector_store
        self._initialized = False
    
    async def initialize(self) -> bool:
        if self._initialized:
            return True
        result = await self.vector_store.initialize()
        self._initialized = result
        return result
    
    async def get_statistics(self) -> dict[str, Any]:
        return await self.vector_store.get_statistics() if self._initialized else {"total_chunks": 0}
    
    async def clear(self) -> bool:
        return await self.vector_store.clear() if self._initialized else True
    
    def is_initialized(self) -> bool:
        return self._initialized


vector_store = VectorStore(dimension=settings.embedding_dimension)
vector_store_manager = VectorStoreManager()
