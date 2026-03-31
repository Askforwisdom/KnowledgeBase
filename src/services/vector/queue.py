"""
向量计算队列服务
实现生产者-消费者模式，支持并行处理和批量计算
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class EmbeddingTask:
    task_id: str
    knowledge_type: Any
    vector_data: Any
    status: TaskStatus = TaskStatus.PENDING
    embedding: Optional[list[float]] = None
    error: Optional[str] = None
    result_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        if self.result_event is None:
            self.result_event = asyncio.Event()


class EmbeddingQueue:
    """向量计算队列 - 管理待处理的嵌入任务"""
    
    def __init__(self, max_size: int = 10000):
        self._queue: asyncio.Queue[EmbeddingTask] = asyncio.Queue(maxsize=max_size)
        self._pending_tasks: dict[str, EmbeddingTask] = {}
        self._task_counter = 0
        self._lock = asyncio.Lock()
    
    async def submit(self, knowledge_type: Any, vector_data: Any) -> str:
        async with self._lock:
            self._task_counter += 1
            task_id = f"emb_{self._task_counter}"
        
        task = EmbeddingTask(
            task_id=task_id,
            knowledge_type=knowledge_type,
            vector_data=vector_data,
        )
        
        self._pending_tasks[task_id] = task
        await self._queue.put(task)
        logger.debug(f"任务已提交: {task_id}, 队列大小: {self._queue.qsize()}")
        return task_id
    
    async def get_batch(self, batch_size: int, timeout: float = 0.1) -> list[EmbeddingTask]:
        tasks = []
        try:
            task = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            tasks.append(task)
            
            while len(tasks) < batch_size and not self._queue.empty():
                try:
                    task = self._queue.get_nowait()
                    tasks.append(task)
                except asyncio.QueueEmpty:
                    break
        except asyncio.TimeoutError:
            pass
        
        return tasks
    
    def get_task(self, task_id: str) -> Optional[EmbeddingTask]:
        return self._pending_tasks.get(task_id)
    
    def complete_task(self, task_id: str, embedding: Optional[list[float]], error: Optional[str] = None):
        task = self._pending_tasks.get(task_id)
        if task:
            task.embedding = embedding
            task.error = error
            task.status = TaskStatus.COMPLETED if embedding else TaskStatus.FAILED
            task.result_event.set()
    
    async def wait_for_task(self, task_id: str, timeout: float = 300.0) -> Optional[list[float]]:
        task = self._pending_tasks.get(task_id)
        if not task:
            return None
        
        try:
            await asyncio.wait_for(task.result_event.wait(), timeout=timeout)
            return task.embedding
        except asyncio.TimeoutError:
            logger.warning(f"任务超时: {task_id}")
            return None
    
    def clear_completed(self):
        completed_ids = [
            tid for tid, task in self._pending_tasks.items()
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
        ]
        for tid in completed_ids:
            del self._pending_tasks[tid]
    
    @property
    def size(self) -> int:
        return self._queue.qsize()
    
    @property
    def pending_count(self) -> int:
        return len(self._pending_tasks)


class EmbeddingConsumer:
    """向量计算消费者 - 批量处理嵌入任务"""
    
    def __init__(
        self,
        queue: EmbeddingQueue,
        batch_size: int = 32,
        batch_timeout: float = 0.1,
    ):
        self._queue = queue
        self._batch_size = batch_size
        self._batch_timeout = batch_timeout
        self._running = False
        self._consumer_task: Optional[asyncio.Task] = None
        self._stats = {
            "total_processed": 0,
            "total_failed": 0,
            "batches_processed": 0,
        }
    
    @property
    def stats(self) -> dict[str, Any]:
        return self._stats.copy()
    
    async def start(self):
        if self._running:
            return
        
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_loop())
        logger.info(f"向量计算消费者已启动, 批次大小: {self._batch_size}")
    
    async def stop(self):
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        logger.info("向量计算消费者已停止")
    
    async def _consume_loop(self):
        while self._running:
            try:
                tasks = await self._queue.get_batch(
                    self._batch_size,
                    timeout=self._batch_timeout
                )
                
                if not tasks:
                    await asyncio.sleep(0.01)
                    continue
                
                await self._process_batch(tasks)
                self._stats["batches_processed"] += 1
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"消费者处理错误: {e}", exc_info=True)
                await asyncio.sleep(0.1)
    
    async def _process_batch(self, tasks: list[EmbeddingTask]):
        if not tasks:
            return
        
        for task in tasks:
            task.status = TaskStatus.PROCESSING
        
        texts = [task.vector_data.content_for_embedding for task in tasks]
        
        try:
            from src.services.vector.compute import embedding_generator
            embeddings = embedding_generator.generate_batch(texts, batch_size=self._batch_size)
            
            for task, embedding in zip(tasks, embeddings):
                if embedding:
                    self._queue.complete_task(task.task_id, embedding)
                    self._stats["total_processed"] += 1
                else:
                    self._queue.complete_task(task.task_id, None, "嵌入生成失败")
                    self._stats["total_failed"] += 1
                    
        except Exception as e:
            logger.error(f"批量处理失败: {e}", exc_info=True)
            for task in tasks:
                self._queue.complete_task(task.task_id, None, str(e))
                self._stats["total_failed"] += 1


class EmbeddingPipeline:
    """向量计算流水线 - 管理队列和消费者"""
    
    def __init__(
        self,
        queue_size: int = 10000,
        batch_size: int = 32,
        num_consumers: int = 1,
    ):
        self._queue = EmbeddingQueue(max_size=queue_size)
        self._batch_size = batch_size
        self._num_consumers = num_consumers
        self._consumers: list[EmbeddingConsumer] = []
        self._running = False
    
    @property
    def queue(self) -> EmbeddingQueue:
        return self._queue
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def stats(self) -> dict[str, Any]:
        consumer_stats = [c.stats for c in self._consumers]
        total_processed = sum(s["total_processed"] for s in consumer_stats)
        total_failed = sum(s["total_failed"] for s in consumer_stats)
        
        return {
            "running": self._running,
            "queue_size": self._queue.size,
            "pending_tasks": self._queue.pending_count,
            "total_processed": total_processed,
            "total_failed": total_failed,
            "num_consumers": len(self._consumers),
        }
    
    async def start(self):
        if self._running:
            return
        
        self._running = True
        self._consumers = []
        
        for i in range(self._num_consumers):
            consumer = EmbeddingConsumer(
                queue=self._queue,
                batch_size=self._batch_size,
            )
            await consumer.start()
            self._consumers.append(consumer)
        
        logger.info(f"向量计算流水线已启动, 消费者数: {self._num_consumers}")
    
    async def stop(self):
        self._running = False
        for consumer in self._consumers:
            await consumer.stop()
        self._consumers = []
        logger.info("向量计算流水线已停止")
    
    async def submit(self, knowledge_type: Any, vector_data: Any) -> str:
        return await self._queue.submit(knowledge_type, vector_data)
    
    async def submit_batch(
        self,
        items: list[tuple[Any, Any]]
    ) -> list[str]:
        task_ids = []
        for knowledge_type, vector_data in items:
            task_id = await self.submit(knowledge_type, vector_data)
            task_ids.append(task_id)
        return task_ids
    
    async def wait_for_all(self, timeout: float = 300.0) -> dict[str, Optional[list[float]]]:
        results = {}
        pending_ids = list(self._queue._pending_tasks.keys())
        
        for task_id in pending_ids:
            embedding = await self._queue.wait_for_task(task_id, timeout=timeout)
            results[task_id] = embedding
        
        return results


embedding_pipeline = EmbeddingPipeline()
