"""
多进程处理模块
支持 CPU 多进程并行处理向量计算任务
"""
import asyncio
import logging
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any, Callable, Optional

from src.config import settings

logger = logging.getLogger(__name__)

_cpu_pool: Optional[ProcessPoolExecutor] = None
_thread_pool: Optional[ThreadPoolExecutor] = None


def get_cpu_pool() -> ProcessPoolExecutor:
    """获取 CPU 进程池"""
    global _cpu_pool
    if _cpu_pool is None:
        max_workers = settings.cpu_max_processes if settings.cpu_multiprocess else 1
        _cpu_pool = ProcessPoolExecutor(max_workers=max_workers)
    return _cpu_pool


def get_thread_pool() -> ThreadPoolExecutor:
    """获取线程池"""
    global _thread_pool
    if _thread_pool is None:
        _thread_pool = ThreadPoolExecutor(max_workers=settings.import_max_workers)
    return _thread_pool


def _cpu_encode_worker(args: tuple) -> list:
    """CPU 编码工作函数（在子进程中执行）"""
    import numpy as np
    
    texts, model_path, device = args
    
    try:
        from sentence_transformers import SentenceTransformer
        
        model = SentenceTransformer(model_path, device=device)
        
        embeddings = model.encode(texts, convert_to_numpy=True)
        
        return embeddings.tolist()
    except Exception as e:
        logger.error(f"CPU 编码失败: {e}")
        return [None] * len(texts)


def _cpu_tokenize_worker(args: tuple) -> list:
    """CPU 分词工作函数"""
    texts, tokenizer_path = args
    
    try:
        from transformers import AutoTokenizer
        
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)
        
        token_counts = []
        for text in texts:
            tokens = tokenizer.encode(text, add_special_tokens=False)
            token_counts.append(len(tokens))
        
        return token_counts
    except Exception as e:
        logger.error(f"CPU 分词失败: {e}")
        return [0] * len(texts)


def _cpu_chunk_worker(args: tuple) -> list:
    """CPU 分块工作函数"""
    texts, max_chunk_size, overlap_size = args
    
    chunks = []
    for text in texts:
        if not text:
            chunks.append([])
            continue
        
        if len(text) <= max_chunk_size:
            chunks.append([text])
            continue
        
        text_chunks = []
        start = 0
        
        while start < len(text):
            end = start + max_chunk_size
            
            if end < len(text):
                break_point = end
                for i in range(end, max(end - 100, 0), -1):
                    if text[i] in '。！？\n':
                        break_point = i + 1
                        break
                end = break_point
            
            chunk = text[start:end].strip()
            if chunk:
                text_chunks.append(chunk)
            
            start = end - overlap_size if end < len(text) else end
            if text_chunks and start <= len(text_chunks[-1]):
                start = end
        
        chunks.append(text_chunks)
    
    return chunks


class MultiProcessEncoder:
    """多进程编码器"""
    
    def __init__(
        self,
        use_multiprocess: bool = None,
        max_processes: int = None,
    ):
        self.use_multiprocess = use_multiprocess if use_multiprocess is not None else settings.cpu_multiprocess
        self.max_processes = max_processes or settings.cpu_max_processes
        self._model_path = None
        self._device = "cpu"
    
    def set_model(self, model_path: str, device: str = "cpu") -> None:
        """设置模型路径"""
        self._model_path = model_path
        self._device = device
    
    async def encode_batch(
        self,
        texts: list[str],
        batch_size: int = 32,
    ) -> list[Optional[list[float]]]:
        """批量编码文本"""
        if not texts:
            return []
        
        if not self._model_path:
            logger.warning("模型路径未设置")
            return [None] * len(texts)
        
        if not self.use_multiprocess or len(texts) < batch_size * 2:
            return await self._encode_single_process(texts, batch_size)
        
        return await self._encode_multi_process(texts, batch_size)
    
    async def _encode_single_process(
        self,
        texts: list[str],
        batch_size: int,
    ) -> list[Optional[list[float]]]:
        """单进程编码"""
        try:
            from sentence_transformers import SentenceTransformer
            
            model = SentenceTransformer(self._model_path, device=self._device)
            
            all_embeddings = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                embeddings = model.encode(batch, convert_to_numpy=True)
                all_embeddings.extend(embeddings.tolist())
            
            return all_embeddings
        except Exception as e:
            logger.error(f"单进程编码失败: {e}")
            return [None] * len(texts)
    
    async def _encode_multi_process(
        self,
        texts: list[str],
        batch_size: int,
    ) -> list[Optional[list[float]]]:
        """多进程编码"""
        num_processes = min(self.max_processes, (len(texts) + batch_size - 1) // batch_size)
        
        chunks = []
        chunk_size = (len(texts) + num_processes - 1) // num_processes
        
        for i in range(0, len(texts), chunk_size):
            chunks.append(texts[i:i + chunk_size])
        
        loop = asyncio.get_event_loop()
        pool = get_cpu_pool()
        
        tasks = []
        for chunk in chunks:
            task = loop.run_in_executor(
                pool,
                _cpu_encode_worker,
                (chunk, self._model_path, self._device)
            )
            tasks.append(task)
        
        try:
            results = await asyncio.gather(*tasks)
            
            all_embeddings = []
            for result in results:
                all_embeddings.extend(result)
            
            return all_embeddings
        except Exception as e:
            logger.error(f"多进程编码失败: {e}")
            return [None] * len(texts)


class MultiProcessTokenizer:
    """多进程分词器"""
    
    def __init__(
        self,
        use_multiprocess: bool = None,
        max_processes: int = None,
    ):
        self.use_multiprocess = use_multiprocess if use_multiprocess is not None else settings.cpu_multiprocess
        self.max_processes = max_processes or settings.cpu_max_processes
        self._tokenizer_path = None
    
    def set_tokenizer(self, tokenizer_path: str) -> None:
        """设置分词器路径"""
        self._tokenizer_path = tokenizer_path
    
    async def count_tokens_batch(self, texts: list[str]) -> list[int]:
        """批量计算 token 数量"""
        if not texts:
            return []
        
        if not self._tokenizer_path:
            return self._fast_estimate_batch(texts)
        
        if not self.use_multiprocess or len(texts) < 1000:
            return await self._count_single_process(texts)
        
        return await self._count_multi_process(texts)
    
    def _fast_estimate_batch(self, texts: list[str]) -> list[int]:
        """快速估算 token 数量"""
        results = []
        for text in texts:
            char_count = len(text)
            chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            english_chars = char_count - chinese_chars
            results.append(max(1, chinese_chars + english_chars // 4))
        return results
    
    async def _count_single_process(self, texts: list[str]) -> list[int]:
        """单进程计算"""
        try:
            from transformers import AutoTokenizer
            
            tokenizer = AutoTokenizer.from_pretrained(self._tokenizer_path, trust_remote_code=True)
            
            return [len(tokenizer.encode(text, add_special_tokens=False)) for text in texts]
        except Exception as e:
            logger.error(f"单进程分词失败: {e}")
            return self._fast_estimate_batch(texts)
    
    async def _count_multi_process(self, texts: list[str]) -> list[int]:
        """多进程计算"""
        num_processes = min(self.max_processes, max(1, len(texts) // 1000))
        
        chunks = []
        chunk_size = (len(texts) + num_processes - 1) // num_processes
        
        for i in range(0, len(texts), chunk_size):
            chunks.append(texts[i:i + chunk_size])
        
        loop = asyncio.get_event_loop()
        pool = get_cpu_pool()
        
        tasks = []
        for chunk in chunks:
            task = loop.run_in_executor(
                pool,
                _cpu_tokenize_worker,
                (chunk, self._tokenizer_path)
            )
            tasks.append(task)
        
        try:
            results = await asyncio.gather(*tasks)
            
            all_counts = []
            for result in results:
                all_counts.extend(result)
            
            return all_counts
        except Exception as e:
            logger.error(f"多进程分词失败: {e}")
            return self._fast_estimate_batch(texts)


class MultiProcessChunker:
    """多进程分块器"""
    
    def __init__(
        self,
        use_multiprocess: bool = None,
        max_processes: int = None,
        max_chunk_size: int = None,
        overlap_size: int = None,
    ):
        self.use_multiprocess = use_multiprocess if use_multiprocess is not None else settings.cpu_multiprocess
        self.max_processes = max_processes or settings.cpu_max_processes
        self.max_chunk_size = max_chunk_size or settings.chunk_max_size
        self.overlap_size = overlap_size or settings.chunk_overlap_size
    
    async def chunk_batch(self, texts: list[str]) -> list[list[str]]:
        """批量分块"""
        if not texts:
            return []
        
        if not self.use_multiprocess or len(texts) < 100:
            return self._chunk_single_process(texts)
        
        return await self._chunk_multi_process(texts)
    
    def _chunk_single_process(self, texts: list[str]) -> list[list[str]]:
        """单进程分块"""
        results = []
        for text in texts:
            if not text:
                results.append([])
                continue
            
            if len(text) <= self.max_chunk_size:
                results.append([text])
                continue
            
            chunks = []
            start = 0
            
            while start < len(text):
                end = start + self.max_chunk_size
                
                if end < len(text):
                    break_point = end
                    for i in range(end, max(end - 100, 0), -1):
                        if text[i] in '。！？\n':
                            break_point = i + 1
                            break
                    end = break_point
                
                chunk = text[start:end].strip()
                if chunk:
                    chunks.append(chunk)
                
                start = end - self.overlap_size if end < len(text) else end
                if chunks and start <= len(chunks[-1]):
                    start = end
            
            results.append(chunks)
        
        return results
    
    async def _chunk_multi_process(self, texts: list[str]) -> list[list[str]]:
        """多进程分块"""
        num_processes = min(self.max_processes, max(1, len(texts) // 100))
        
        chunks = []
        chunk_size = (len(texts) + num_processes - 1) // num_processes
        
        for i in range(0, len(texts), chunk_size):
            chunks.append(texts[i:i + chunk_size])
        
        loop = asyncio.get_event_loop()
        pool = get_cpu_pool()
        
        tasks = []
        for chunk in chunks:
            task = loop.run_in_executor(
                pool,
                _cpu_chunk_worker,
                (chunk, self.max_chunk_size, self.overlap_size)
            )
            tasks.append(task)
        
        try:
            results = await asyncio.gather(*tasks)
            
            all_chunks = []
            for result in results:
                all_chunks.extend(result)
            
            return all_chunks
        except Exception as e:
            logger.error(f"多进程分块失败: {e}")
            return self._chunk_single_process(texts)


class ParallelProcessor:
    """并行处理器 - 统一管理多进程/多线程任务"""
    
    def __init__(self):
        self.encoder = MultiProcessEncoder()
        self.tokenizer = MultiProcessTokenizer()
        self.chunker = MultiProcessChunker()
    
    async def process_files_parallel(
        self,
        file_paths: list,
        process_func: Callable,
        max_workers: int = None,
    ) -> list[Any]:
        """并行处理文件"""
        if not file_paths:
            return []
        
        max_workers = max_workers or settings.import_max_workers
        
        loop = asyncio.get_event_loop()
        pool = get_thread_pool()
        
        tasks = [
            loop.run_in_executor(pool, process_func, fp)
            for fp in file_paths
        ]
        
        return await asyncio.gather(*tasks)
    
    async def map_parallel(
        self,
        items: list,
        func: Callable,
        max_workers: int = None,
        use_process: bool = False,
    ) -> list[Any]:
        """并行映射"""
        if not items:
            return []
        
        max_workers = max_workers or settings.import_max_workers
        
        loop = asyncio.get_event_loop()
        pool = get_cpu_pool() if use_process else get_thread_pool()
        
        tasks = [
            loop.run_in_executor(pool, func, item)
            for item in items
        ]
        
        return await asyncio.gather(*tasks)
    
    def shutdown(self) -> None:
        """关闭所有线程池/进程池"""
        global _cpu_pool, _thread_pool
        
        if _cpu_pool:
            _cpu_pool.shutdown(wait=False)
            _cpu_pool = None
        
        if _thread_pool:
            _thread_pool.shutdown(wait=False)
            _thread_pool = None


parallel_processor = ParallelProcessor()
multi_process_encoder = MultiProcessEncoder()
multi_process_tokenizer = MultiProcessTokenizer()
multi_process_chunker = MultiProcessChunker()
