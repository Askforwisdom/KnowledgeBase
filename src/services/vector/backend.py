"""
向量库后端抽象模块
提供向量库后端的抽象接口，支持多种向量库实现
"""
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BaseVectorBackend(ABC):
    """向量库后端抽象基类"""
    
    def __init__(self, dimension: int, index_path: Optional[Path] = None):
        self.dimension = dimension
        self.index_path = index_path
        self._initialized = False
    
    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """检查后端是否可用"""
        pass
    
    @classmethod
    @abstractmethod
    def get_name(cls) -> str:
        """获取后端名称"""
        pass
    
    @abstractmethod
    async def initialize(self) -> bool:
        """初始化向量库"""
        pass
    
    @abstractmethod
    async def add_vectors(self, vectors: list[list[float]]) -> bool:
        """添加向量到索引"""
        pass
    
    @abstractmethod
    async def search(self, query_vector: list[float], k: int) -> list[tuple[int, float]]:
        """
        搜索相似向量
        返回: [(索引, 分数), ...]
        """
        pass
    
    @abstractmethod
    async def delete_by_indices(self, indices: list[int]) -> bool:
        """根据索引删除向量"""
        pass
    
    @abstractmethod
    async def save_index(self) -> bool:
        """保存索引到磁盘"""
        pass
    
    @abstractmethod
    async def load_index(self) -> bool:
        """从磁盘加载索引"""
        pass
    
    @abstractmethod
    async def clear(self) -> bool:
        """清空索引"""
        pass
    
    @abstractmethod
    def get_vector_count(self) -> int:
        """获取向量数量"""
        pass
    
    @abstractmethod
    def normalize_vector(self, vector: list[float]) -> list[float]:
        """归一化向量"""
        pass
    
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized


class VectorBackendFactory:
    """向量库后端工厂"""
    
    _backends: dict[str, type[BaseVectorBackend]] = {}
    
    @classmethod
    def register(cls, backend_class: type[BaseVectorBackend]) -> None:
        """注册后端"""
        cls._backends[backend_class.get_name()] = backend_class
    
    @classmethod
    def get_available_backends(cls) -> list[str]:
        """获取所有可用的后端"""
        return [name for name, backend in cls._backends.items() if backend.is_available()]
    
    @classmethod
    def create(cls, backend_name: str, dimension: int, index_path: Optional[Path] = None) -> Optional[BaseVectorBackend]:
        """创建后端实例"""
        backend_class = cls._backends.get(backend_name)
        if not backend_class:
            logger.error(f"未知的向量库后端: {backend_name}")
            return None
        if not backend_class.is_available():
            logger.error(f"向量库后端不可用: {backend_name}")
            return None
        return backend_class(dimension=dimension, index_path=index_path)
    
    @classmethod
    def get_default_backend(cls) -> Optional[str]:
        """获取默认后端"""
        available = cls.get_available_backends()
        if "faiss" in available:
            return "faiss"
        return available[0] if available else None


def register_backend(backend_class: type[BaseVectorBackend]) -> type[BaseVectorBackend]:
    """后端注册装饰器"""
    VectorBackendFactory.register(backend_class)
    return backend_class
