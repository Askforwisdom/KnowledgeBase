"""
向量模块
提供统一的向量服务，支持多种知识类型和多种向量库后端

目录结构：
- backend.py: 向量库后端抽象基类和工厂
- backends/: 向量库后端实现（FAISS等）
- compute.py: 向量服务、嵌入向量生成器
- chunker.py: 文本分块器（支持流式读取）
- store.py: 向量存储管理器（支持批量写入优化和异步提交）
- queue.py: 向量计算队列服务（生产者-消费者模式）
- batch_optimizer.py: 批量优化模块（Token预计算、长度分桶、动态批处理）
- multiprocess.py: 多进程处理模块（CPU多进程支持）
"""

from src.services.vector.backend import (
    BaseVectorBackend,
    VectorBackendFactory,
    register_backend,
)
from src.services.vector.backends import FaissVectorBackend
from src.services.vector.compute import (
    VectorComputeService,
    VectorData,
    EmbeddingGenerator,
    embedding_generator,
    vector_compute_service,
)
from src.services.vector.chunker import (
    TextChunker,
    text_chunker,
    StreamingTextReader,
    streaming_reader,
    StreamingChunkProcessor,
    streaming_processor,
    MemoryEfficientChunker,
    memory_efficient_chunker,
)
from src.services.vector.store import (
    VectorStore,
    VectorDocument,
    VectorStoreManager,
    vector_store,
    vector_store_manager,
    AsyncCommitBuffer,
)
from src.services.vector.queue import (
    EmbeddingQueue,
    EmbeddingConsumer,
    EmbeddingPipeline,
    EmbeddingTask,
    TaskStatus,
    embedding_pipeline,
)
from src.services.vector.batch_optimizer import (
    BucketType,
    TokenInfo,
    BatchGroup,
    TokenCounter,
    token_counter,
    LengthBucketing,
    length_bucketing,
    DynamicBatcher,
    dynamic_batcher,
    BatchOptimizer,
    batch_optimizer,
)
from src.services.vector.multiprocess import (
    MultiProcessEncoder,
    MultiProcessTokenizer,
    MultiProcessChunker,
    ParallelProcessor,
    parallel_processor,
    multi_process_encoder,
    multi_process_tokenizer,
    multi_process_chunker,
)

__all__ = [
    "BaseVectorBackend",
    "VectorBackendFactory",
    "register_backend",
    "FaissVectorBackend",
    "VectorComputeService",
    "VectorData",
    "EmbeddingGenerator",
    "embedding_generator",
    "vector_compute_service",
    "TextChunker",
    "text_chunker",
    "StreamingTextReader",
    "streaming_reader",
    "StreamingChunkProcessor",
    "streaming_processor",
    "MemoryEfficientChunker",
    "memory_efficient_chunker",
    "VectorStore",
    "VectorDocument",
    "VectorStoreManager",
    "vector_store",
    "vector_store_manager",
    "AsyncCommitBuffer",
    "EmbeddingQueue",
    "EmbeddingConsumer",
    "EmbeddingPipeline",
    "EmbeddingTask",
    "TaskStatus",
    "embedding_pipeline",
    "BucketType",
    "TokenInfo",
    "BatchGroup",
    "TokenCounter",
    "token_counter",
    "LengthBucketing",
    "length_bucketing",
    "DynamicBatcher",
    "dynamic_batcher",
    "BatchOptimizer",
    "batch_optimizer",
    "MultiProcessEncoder",
    "MultiProcessTokenizer",
    "MultiProcessChunker",
    "ParallelProcessor",
    "parallel_processor",
    "multi_process_encoder",
    "multi_process_tokenizer",
    "multi_process_chunker",
]
