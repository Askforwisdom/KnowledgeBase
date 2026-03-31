"""
文本分块模块
将长文本分割成适合向量计算的小块
支持流式读取和内存优化
"""
import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Optional
from uuid import uuid4

from src.config import settings

logger = logging.getLogger(__name__)


class TextChunker:
    """文本分块器"""
    
    def __init__(self, max_chunk_size: int = None, overlap_size: int = None):
        self.max_chunk_size = max_chunk_size or settings.chunk_max_size
        self.overlap_size = overlap_size or settings.chunk_overlap_size

    def chunk_text(self, text: str) -> list[str]:
        if not text:
            return []
        
        if len(text) <= self.max_chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + self.max_chunk_size
            
            if end < len(text):
                break_point = self._find_break_point(text, end)
                if break_point > start:
                    end = break_point
            
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            start = end - self.overlap_size if end < len(text) else end
            if start <= chunks[-1] if chunks else 0:
                start = end
        
        return chunks

    def _find_break_point(self, text: str, position: int) -> int:
        for i in range(position, max(position - 100, 0), -1):
            if text[i] in '。！？\n':
                return i + 1
        for i in range(position, max(position - 50, 0), -1):
            if text[i] in '，、；：':
                return i + 1
        for i in range(position, max(position - 20, 0), -1):
            if text[i] == ' ':
                return i + 1
        return position

    def chunk_with_metadata(
        self,
        doc_id: str,
        doc_title: str,
        doc_path: str,
        doc_summary: str,
        content_for_embedding: str,
    ) -> list[dict]:
        chunks = self.chunk_text(content_for_embedding)
        
        result = []
        for chunk in chunks:
            result.append({
                "chunk_id": str(uuid4()),
                "doc_id": doc_id,
                "doc_title": doc_title,
                "doc_path": doc_path,
                "doc_summary": doc_summary,
                "content_for_embedding": chunk,
            })
        
        return result


class StreamingTextReader:
    """流式文本读取器"""
    
    def __init__(
        self,
        chunk_size: int = None,
        read_ahead: int = None,
        max_chunk_size: int = None,
        overlap_size: int = None,
    ):
        self.chunk_size = chunk_size or settings.streaming_chunk_size
        self.read_ahead = read_ahead or settings.streaming_read_ahead
        self.max_chunk_size = max_chunk_size or settings.chunk_max_size
        self.overlap_size = overlap_size or settings.chunk_overlap_size
        self._buffer = ""
        self._position = 0
    
    def read_file_streaming(self, file_path: Path) -> Iterator[str]:
        """流式读取文件，按块返回"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                while True:
                    chunk = f.read(self.chunk_size)
                    if not chunk:
                        if self._buffer:
                            yield self._buffer.strip()
                            self._buffer = ""
                        break
                    
                    self._buffer += chunk
                    
                    while len(self._buffer) >= self.max_chunk_size:
                        text_chunk, self._buffer = self._extract_chunk()
                        if text_chunk:
                            yield text_chunk
                
                if self._buffer:
                    yield self._buffer.strip()
                    self._buffer = ""
                    
        except Exception as e:
            logger.error(f"流式读取文件失败: {file_path}, 错误: {e}")
            raise
    
    async def read_file_streaming_async(self, file_path: Path) -> AsyncIterator[str]:
        """异步流式读取文件"""
        loop = asyncio.get_event_loop()
        
        def read_chunk(f):
            return f.read(self.chunk_size)
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                while True:
                    chunk = await loop.run_in_executor(None, read_chunk, f)
                    if not chunk:
                        if self._buffer:
                            yield self._buffer.strip()
                            self._buffer = ""
                        break
                    
                    self._buffer += chunk
                    
                    while len(self._buffer) >= self.max_chunk_size:
                        text_chunk, self._buffer = self._extract_chunk()
                        if text_chunk:
                            yield text_chunk
                
                if self._buffer:
                    yield self._buffer.strip()
                    self._buffer = ""
                    
        except Exception as e:
            logger.error(f"异步流式读取文件失败: {file_path}, 错误: {e}")
            raise
    
    def _extract_chunk(self) -> tuple[str, str]:
        """从缓冲区提取一个完整块"""
        if len(self._buffer) <= self.max_chunk_size:
            return self._buffer, ""
        
        break_point = self._find_break_point_streaming()
        
        if break_point <= 0:
            break_point = self.max_chunk_size
        
        chunk = self._buffer[:break_point].strip()
        remaining = self._buffer[break_point - self.overlap_size:] if break_point < len(self._buffer) else ""
        
        return chunk, remaining
    
    def _find_break_point_streaming(self) -> int:
        """在缓冲区中寻找断点"""
        search_start = max(0, self.max_chunk_size - 100)
        search_end = min(len(self._buffer), self.max_chunk_size + 100)
        
        for i in range(search_end, search_start, -1):
            if i < len(self._buffer) and self._buffer[i] in '。！？\n':
                return i + 1
        
        for i in range(search_end, search_start, -1):
            if i < len(self._buffer) and self._buffer[i] in '，、；：':
                return i + 1
        
        for i in range(search_end, search_start, -1):
            if i < len(self._buffer) and self._buffer[i] == ' ':
                return i + 1
        
        return self.max_chunk_size


class StreamingChunkProcessor:
    """流式分块处理器"""
    
    def __init__(
        self,
        chunk_size: int = None,
        max_chunk_size: int = None,
        overlap_size: int = None,
    ):
        self.reader = StreamingTextReader(
            chunk_size=chunk_size,
            max_chunk_size=max_chunk_size,
            overlap_size=overlap_size,
        )
        self.chunker = TextChunker(max_chunk_size, overlap_size)
    
    def process_file_streaming(
        self,
        file_path: Path,
        doc_id: str,
        doc_title: str,
        doc_summary: str = "",
    ) -> Iterator[dict]:
        """流式处理文件，逐块返回带元数据的结果"""
        chunk_index = 0
        
        for text_chunk in self.reader.read_file_streaming(file_path):
            if not text_chunk.strip():
                continue
            
            sub_chunks = self.chunker.chunk_text(text_chunk)
            
            for sub_chunk in sub_chunks:
                chunk_index += 1
                yield {
                    "chunk_id": f"{doc_id}_chunk_{chunk_index}",
                    "doc_id": doc_id,
                    "doc_title": doc_title,
                    "doc_path": str(file_path),
                    "doc_summary": doc_summary,
                    "content_for_embedding": sub_chunk,
                    "chunk_index": chunk_index,
                }
    
    async def process_file_streaming_async(
        self,
        file_path: Path,
        doc_id: str,
        doc_title: str,
        doc_summary: str = "",
    ) -> AsyncIterator[dict]:
        """异步流式处理文件"""
        chunk_index = 0
        
        async for text_chunk in self.reader.read_file_streaming_async(file_path):
            if not text_chunk.strip():
                continue
            
            sub_chunks = self.chunker.chunk_text(text_chunk)
            
            for sub_chunk in sub_chunks:
                chunk_index += 1
                yield {
                    "chunk_id": f"{doc_id}_chunk_{chunk_index}",
                    "doc_id": doc_id,
                    "doc_title": doc_title,
                    "doc_path": str(file_path),
                    "doc_summary": doc_summary,
                    "content_for_embedding": sub_chunk,
                    "chunk_index": chunk_index,
                }
    
    def process_large_file(
        self,
        file_path: Path,
        doc_id: str,
        doc_title: str,
        doc_summary: str = "",
        callback: callable = None,
    ) -> list[dict]:
        """处理大文件，支持回调"""
        results = []
        
        for chunk_data in self.process_file_streaming(file_path, doc_id, doc_title, doc_summary):
            results.append(chunk_data)
            if callback:
                callback(chunk_data)
        
        return results


class MemoryEfficientChunker:
    """内存高效分块器 - 用于处理超大文件"""
    
    def __init__(
        self,
        max_memory_mb: int = 100,
        max_chunk_size: int = None,
        overlap_size: int = None,
    ):
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.max_chunk_size = max_chunk_size or settings.chunk_max_size
        self.overlap_size = overlap_size or settings.chunk_overlap_size
    
    def process_file_with_memory_limit(
        self,
        file_path: Path,
        doc_id: str,
        doc_title: str,
        doc_summary: str = "",
    ) -> Iterator[dict]:
        """在内存限制下处理文件"""
        file_size = file_path.stat().st_size if file_path.exists() else 0
        
        if file_size <= self.max_memory_bytes:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            chunker = TextChunker(self.max_chunk_size, self.overlap_size)
            chunks = chunker.chunk_text(content)
            
            for i, chunk in enumerate(chunks, 1):
                yield {
                    "chunk_id": f"{doc_id}_chunk_{i}",
                    "doc_id": doc_id,
                    "doc_title": doc_title,
                    "doc_path": str(file_path),
                    "doc_summary": doc_summary,
                    "content_for_embedding": chunk,
                    "chunk_index": i,
                }
        else:
            processor = StreamingChunkProcessor(
                max_chunk_size=self.max_chunk_size,
                overlap_size=self.overlap_size,
            )
            yield from processor.process_file_streaming(file_path, doc_id, doc_title, doc_summary)


text_chunker = TextChunker()
streaming_reader = StreamingTextReader()
streaming_processor = StreamingChunkProcessor()
memory_efficient_chunker = MemoryEfficientChunker()
