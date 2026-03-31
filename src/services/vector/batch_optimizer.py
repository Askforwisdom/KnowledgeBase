"""
批量优化模块
包含 Token 预计算、长度分桶、动态批处理等优化策略
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from src.config import settings

logger = logging.getLogger(__name__)


class BucketType(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


@dataclass
class TokenInfo:
    text: str
    token_count: int
    bucket: BucketType
    index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchGroup:
    bucket: BucketType
    batch_size: int
    items: list[TokenInfo] = field(default_factory=list)


class TokenCounter:
    """Token 计数器 - 支持多种估算方式"""
    
    def __init__(self):
        self._tokenizer = None
        self._use_fast_estimate = True
    
    def set_tokenizer(self, tokenizer) -> None:
        self._tokenizer = tokenizer
        self._use_fast_estimate = False
    
    def count_tokens(self, text: str) -> int:
        if self._use_fast_estimate or self._tokenizer is None:
            return self._fast_estimate(text)
        return self._precise_count(text)
    
    def _fast_estimate(self, text: str) -> int:
        char_count = len(text)
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        english_chars = char_count - chinese_chars
        return max(1, int(chinese_chars * 1.5 + english_chars // 3))
    
    def _precise_count(self, text: str) -> int:
        try:
            tokens = self._tokenizer.encode(text, add_special_tokens=False)
            return len(tokens)
        except Exception:
            return self._fast_estimate(text)
    
    def count_batch(self, texts: list[str]) -> list[int]:
        return [self.count_tokens(text) for text in texts]


token_counter = TokenCounter()


class LengthBucketing:
    """长度分桶策略"""
    
    def __init__(
        self,
        short_threshold: int = None,
        medium_threshold: int = None,
        long_threshold: int = None,
        batch_size_short: int = None,
        batch_size_medium: int = None,
        batch_size_long: int = None,
    ):
        self.short_threshold = short_threshold or settings.token_bucket_short
        self.medium_threshold = medium_threshold or settings.token_bucket_medium
        self.long_threshold = long_threshold or settings.token_bucket_long
        
        self.batch_sizes = {
            BucketType.SHORT: batch_size_short or settings.batch_size_short,
            BucketType.MEDIUM: batch_size_medium or settings.batch_size_medium,
            BucketType.LONG: batch_size_long or settings.batch_size_long,
        }
    
    def get_bucket(self, token_count: int) -> BucketType:
        if token_count <= self.short_threshold:
            return BucketType.SHORT
        elif token_count <= self.medium_threshold:
            return BucketType.MEDIUM
        else:
            return BucketType.LONG
    
    def get_batch_size(self, bucket: BucketType) -> int:
        return self.batch_sizes.get(bucket, settings.batch_size_medium)
    
    def classify_texts(self, texts: list[str], metadata: list[dict] = None) -> list[TokenInfo]:
        results = []
        for i, text in enumerate(texts):
            token_count = token_counter.count_tokens(text)
            bucket = self.get_bucket(token_count)
            meta = metadata[i] if metadata and i < len(metadata) else {}
            results.append(TokenInfo(
                text=text,
                token_count=token_count,
                bucket=bucket,
                index=i,
                metadata=meta,
            ))
        return results
    
    def group_by_bucket(self, token_infos: list[TokenInfo]) -> dict[BucketType, list[TokenInfo]]:
        groups: dict[BucketType, list[TokenInfo]] = {
            BucketType.SHORT: [],
            BucketType.MEDIUM: [],
            BucketType.LONG: [],
        }
        for info in token_infos:
            groups[info.bucket].append(info)
        return groups
    
    def create_batches(self, token_infos: list[TokenInfo]) -> list[BatchGroup]:
        groups = self.group_by_bucket(token_infos)
        batches = []
        
        for bucket, items in groups.items():
            if not items:
                continue
            
            batch_size = self.get_batch_size(bucket)
            
            for i in range(0, len(items), batch_size):
                batch_items = items[i:i + batch_size]
                batches.append(BatchGroup(
                    bucket=bucket,
                    batch_size=len(batch_items),
                    items=batch_items,
                ))
        
        return batches


length_bucketing = LengthBucketing()


class DynamicBatcher:
    """动态批处理器"""
    
    def __init__(
        self,
        min_batch_size: int = None,
        max_batch_size: int = None,
        memory_threshold: float = None,
    ):
        self.min_batch_size = min_batch_size or settings.dynamic_batch_min
        self.max_batch_size = max_batch_size or settings.dynamic_batch_max
        self.memory_threshold = memory_threshold or settings.dynamic_batch_memory_threshold
        self._current_batch_size = self.max_batch_size
        self._consecutive_oom = 0
        self._consecutive_success = 0
    
    def get_current_batch_size(self) -> int:
        return self._current_batch_size
    
    def estimate_memory_usage(self, texts: list[str], token_counts: list[int] = None) -> float:
        if token_counts is None:
            token_counts = [token_counter.count_tokens(t) for t in texts]
        
        total_tokens = sum(token_counts)
        embedding_dim = settings.embedding_dimension
        bytes_per_float = 2 if settings.embedding_quantization == "fp16" else 4
        
        memory_bytes = total_tokens * embedding_dim * bytes_per_float
        memory_mb = memory_bytes / (1024 * 1024)
        
        return memory_mb
    
    def calculate_optimal_batch_size(
        self,
        texts: list[str],
        available_memory_mb: float = None,
    ) -> int:
        if not texts:
            return self.min_batch_size
        
        token_counts = [token_counter.count_tokens(t) for t in texts]
        avg_tokens = sum(token_counts) / len(token_counts)
        
        if available_memory_mb is None:
            try:
                import torch
                if torch.cuda.is_available():
                    free_mem = torch.cuda.mem_get_info()[0] / (1024 * 1024)
                    available_memory_mb = free_mem * self.memory_threshold
                else:
                    available_memory_mb = 4096
            except Exception:
                available_memory_mb = 4096
        
        embedding_dim = settings.embedding_dimension
        bytes_per_float = 2 if settings.embedding_quantization == "fp16" else 4
        
        memory_per_item = avg_tokens * embedding_dim * bytes_per_float / (1024 * 1024)
        
        if memory_per_item > 0:
            optimal = int(available_memory_mb * 0.7 / memory_per_item)
        else:
            optimal = self.max_batch_size
        
        optimal = max(self.min_batch_size, min(optimal, self.max_batch_size))
        
        return optimal
    
    def on_success(self) -> None:
        self._consecutive_oom = 0
        self._consecutive_success += 1
        
        if self._consecutive_success >= 3 and self._current_batch_size < self.max_batch_size:
            self._current_batch_size = min(
                self._current_batch_size * 2,
                self.max_batch_size
            )
            self._consecutive_success = 0
            logger.debug(f"动态批处理: 增加批次大小到 {self._current_batch_size}")
    
    def on_oom(self) -> int:
        self._consecutive_success = 0
        self._consecutive_oom += 1
        
        if self._consecutive_oom >= 1:
            self._current_batch_size = max(
                self._current_batch_size // 2,
                self.min_batch_size
            )
            logger.warning(f"动态批处理: OOM, 减少批次大小到 {self._current_batch_size}")
        
        return self._current_batch_size
    
    def create_adaptive_batches(
        self,
        texts: list[str],
        metadata: list[dict] = None,
    ) -> list[BatchGroup]:
        if not texts:
            return []
        
        token_infos = length_bucketing.classify_texts(texts, metadata)
        bucket_groups = length_bucketing.group_by_bucket(token_infos)
        
        batches = []
        
        for bucket, items in bucket_groups.items():
            if not items:
                continue
            
            base_batch_size = length_bucketing.get_batch_size(bucket)
            dynamic_batch_size = min(base_batch_size, self._current_batch_size)
            
            for i in range(0, len(items), dynamic_batch_size):
                batch_items = items[i:i + dynamic_batch_size]
                batches.append(BatchGroup(
                    bucket=bucket,
                    batch_size=len(batch_items),
                    items=batch_items,
                ))
        
        return batches


dynamic_batcher = DynamicBatcher()


class BatchOptimizer:
    """批量优化器 - 整合所有优化策略"""
    
    def __init__(self):
        self.token_counter = token_counter
        self.length_bucketing = length_bucketing
        self.dynamic_batcher = dynamic_batcher
    
    def optimize_texts(
        self,
        texts: list[str],
        metadata: list[dict] = None,
        use_dynamic: bool = True,
    ) -> list[BatchGroup]:
        if use_dynamic:
            return self.dynamic_batcher.create_adaptive_batches(texts, metadata)
        else:
            token_infos = self.length_bucketing.classify_texts(texts, metadata)
            return self.length_bucketing.create_batches(token_infos)
    
    def get_statistics(self) -> dict[str, Any]:
        return {
            "current_batch_size": self.dynamic_batcher.get_current_batch_size(),
            "bucket_thresholds": {
                "short": self.length_bucketing.short_threshold,
                "medium": self.length_bucketing.medium_threshold,
                "long": self.length_bucketing.long_threshold,
            },
            "batch_sizes": {
                "short": self.length_bucketing.batch_sizes[BucketType.SHORT],
                "medium": self.length_bucketing.batch_sizes[BucketType.MEDIUM],
                "long": self.length_bucketing.batch_sizes[BucketType.LONG],
            },
        }


batch_optimizer = BatchOptimizer()
