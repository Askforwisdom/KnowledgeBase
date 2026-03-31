"""
FAISS 向量库后端实现
支持 IVF 和 PQ 索引优化
线程安全实现
"""
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from src.config import settings
from src.services.vector.backend import BaseVectorBackend, register_backend

logger = logging.getLogger(__name__)

_faiss_checked = False
_faiss_available = False
_numpy_checked = False
_numpy_available = False


def _check_faiss() -> bool:
    global _faiss_available, _faiss_checked
    if _faiss_checked:
        return _faiss_available
    _faiss_checked = True
    try:
        import faiss
        _faiss_available = True
    except ImportError:
        _faiss_available = False
    return _faiss_available


def _check_numpy() -> bool:
    global _numpy_available, _numpy_checked
    if _numpy_checked:
        return _numpy_available
    _numpy_checked = True
    try:
        import numpy
        _numpy_available = True
    except ImportError:
        _numpy_available = False
    return _numpy_available


class FaissIndexBuilder:
    """FAISS 索引构建器"""
    
    def __init__(self, dimension: int):
        self.dimension = dimension
    
    def build_flat_index(self):
        import faiss
        return faiss.IndexFlatIP(self.dimension)
    
    def build_ivf_index(self, nlist: int = 100, use_gpu: bool = False):
        import faiss
        
        quantizer = faiss.IndexFlatIP(self.dimension)
        index = faiss.IndexIVFFlat(quantizer, self.dimension, nlist, faiss.METRIC_INNER_PRODUCT)
        
        return index
    
    def build_pq_index(self, m: int = 8, nbits: int = 8):
        import faiss
        
        index = faiss.IndexPQ(self.dimension, m, nbits, faiss.METRIC_INNER_PRODUCT)
        
        return index
    
    def build_ivf_pq_index(self, nlist: int = 100, m: int = 8, nbits: int = 8):
        import faiss
        
        quantizer = faiss.IndexFlatIP(self.dimension)
        index = faiss.IndexIVFPQ(quantizer, self.dimension, nlist, m, nbits, faiss.METRIC_INNER_PRODUCT)
        
        return index
    
    def build_hnsw_index(self, m: int = 32):
        import faiss
        
        index = faiss.IndexHNSWFlat(self.dimension, m, faiss.METRIC_INNER_PRODUCT)
        
        return index
    
    def build_auto_index(self, expected_size: int = 10000):
        import faiss
        
        if expected_size < 10000:
            return self.build_flat_index()
        elif expected_size < 100000:
            return self.build_ivf_index(nlist=min(100, expected_size // 100))
        elif expected_size < 1000000:
            return self.build_ivf_pq_index(nlist=min(256, expected_size // 1000), m=8)
        else:
            return self.build_ivf_pq_index(nlist=1024, m=16)


@register_backend
class FaissVectorBackend(BaseVectorBackend):
    """FAISS 向量库后端 - 支持多种索引类型，线程安全"""
    
    def __init__(self, dimension: int, index_path: Optional[Path] = None):
        super().__init__(dimension, index_path)
        self.index = None
        self._index_type = "flat"
        self._is_trained = False
        self._training_data: list = []
        self._training_threshold = 100
        self._lock = threading.RLock()
        self._write_lock = threading.RLock()
    
    @classmethod
    def is_available(cls) -> bool:
        return _check_faiss() and _check_numpy()
    
    @classmethod
    def get_name(cls) -> str:
        return "faiss"
    
    def _build_index(self, expected_size: int = 0) -> Any:
        import faiss
        
        index_builder = FaissIndexBuilder(self.dimension)
        
        use_ivf = settings.faiss_use_ivf
        use_pq = settings.faiss_use_pq
        nlist = settings.faiss_ivf_nlist
        m = settings.faiss_pq_m
        nbits = settings.faiss_pq_nbits
        
        if expected_size > 0 and expected_size < 1000:
            self._index_type = "flat"
            return index_builder.build_flat_index()
        
        if use_ivf and use_pq:
            self._index_type = "ivf_pq"
            return index_builder.build_ivf_pq_index(nlist, m, nbits)
        elif use_ivf:
            self._index_type = "ivf"
            return index_builder.build_ivf_index(nlist)
        elif use_pq:
            self._index_type = "pq"
            return index_builder.build_pq_index(m, nbits)
        else:
            self._index_type = "flat"
            return index_builder.build_flat_index()
    
    async def initialize(self) -> bool:
        with self._lock:
            if self._initialized:
                return True
            
            if not self.is_available():
                logger.warning("FAISS 或 NumPy 不可用")
                return False
            
            try:
                import faiss
                
                if self.index_path:
                    self.index_path.mkdir(parents=True, exist_ok=True)
                    index_file = self.index_path / "index.faiss"
                    
                    if index_file.exists():
                        self.index = faiss.read_index(str(index_file))
                        self._is_trained = True
                        self._index_type = "loaded"
                        logger.info(f"从文件加载 FAISS 索引: {index_file}")
                    else:
                        self.index = self._build_index()
                        logger.info(f"创建新的 FAISS 索引, 类型: {self._index_type}")
                else:
                    self.index = self._build_index()
                    logger.info(f"创建新的 FAISS 索引 (无持久化), 类型: {self._index_type}")
                
                self._initialized = True
                return True
            except Exception as e:
                logger.error(f"初始化 FAISS 失败: {e}", exc_info=True)
                return False
    
    def _needs_training(self) -> bool:
        return self._index_type in ("ivf", "pq", "ivf_pq") and not self._is_trained
    
    def _train_index(self, vectors) -> bool:
        if not self._needs_training():
            return True
        
        try:
            import numpy as np
            import faiss
            
            vectors_array = np.array(vectors, dtype=np.float32)
            faiss.normalize_L2(vectors_array)
            
            self.index.train(vectors_array)
            self._is_trained = True
            logger.info(f"FAISS 索引训练完成, 类型: {self._index_type}")
            return True
        except Exception as e:
            logger.error(f"训练 FAISS 索引失败: {e}", exc_info=True)
            return False
    
    async def add_vectors(self, vectors: list[list[float]]) -> bool:
        with self._write_lock:
            if not self._initialized or not self.index:
                return False
            
            try:
                import numpy as np
                import faiss
                
                vectors_array = np.array(vectors, dtype=np.float32)
                faiss.normalize_L2(vectors_array)
                
                if self._needs_training():
                    self._training_data.extend(vectors)
                    
                    if len(self._training_data) >= self._training_threshold:
                        self._train_index(self._training_data)
                        self._training_data = []
                
                if self._needs_training():
                    return True
                
                self.index.add(vectors_array)
                return True
            except Exception as e:
                logger.error(f"添加向量失败: {e}", exc_info=True)
                return False
    
    async def search(self, query_vector: list[float], k: int) -> list[tuple[int, float]]:
        with self._lock:
            if not self._initialized or not self.index or self.index.ntotal == 0:
                return []
            
            if self._needs_training():
                return []
            
            try:
                import numpy as np
                import faiss
                
                query_array = np.array([query_vector], dtype=np.float32)
                faiss.normalize_L2(query_array)
                
                search_k = min(k, self.index.ntotal)
                if search_k <= 0:
                    return []
                
                if self._index_type == "ivf" or self._index_type == "ivf_pq":
                    self.index.nprobe = min(10, self.index.nlist)
                
                scores, indices = self.index.search(query_array, search_k)
                results = []
                for idx, score in zip(indices[0], scores[0]):
                    if idx >= 0:
                        results.append((int(idx), float(score)))
                return results
            except Exception as e:
                logger.error(f"搜索失败: {e}", exc_info=True)
                return []
    
    async def delete_by_indices(self, indices: list[int]) -> bool:
        with self._write_lock:
            if not self._initialized or not self.index:
                return True
            
            try:
                import faiss
                
                try:
                    if hasattr(self.index, 'remove_ids'):
                        import numpy as np
                        id_selector = faiss.IDSelectorArray(len(indices), np.array(indices, dtype=np.int64))
                        self.index.remove_ids(id_selector)
                        return True
                except Exception:
                    pass
                
                self.index = self._build_index(self.index.ntotal - len(indices))
                self._is_trained = False
                self._training_data = []
                return True
            except Exception as e:
                logger.error(f"删除向量失败: {e}", exc_info=True)
                return False
    
    async def save_index(self) -> bool:
        with self._lock:
            if not self._initialized or not self.index or not self.index_path:
                return False
            
            try:
                import faiss
                if self.index.ntotal > 0:
                    faiss.write_index(self.index, str(self.index_path / "index.faiss"))
                    logger.info(f"保存 FAISS 索引: {self.index_path / 'index.faiss'}")
                return True
            except Exception as e:
                logger.error(f"保存索引失败: {e}", exc_info=True)
                return False
    
    async def load_index(self) -> bool:
        with self._lock:
            if not self.index_path:
                return False
            
            try:
                import faiss
                index_file = self.index_path / "index.faiss"
                if index_file.exists():
                    self.index = faiss.read_index(str(index_file))
                    self._is_trained = True
                    self._initialized = True
                    return True
                return False
            except Exception as e:
                logger.error(f"加载索引失败: {e}", exc_info=True)
                return False
    
    async def clear(self) -> bool:
        with self._write_lock:
            try:
                import faiss
                self.index = self._build_index()
                self._is_trained = False
                self._training_data = []
                return True
            except Exception as e:
                logger.error(f"清空索引失败: {e}", exc_info=True)
                return False
    
    def get_vector_count(self) -> int:
        with self._lock:
            if not self.index:
                return 0
            return self.index.ntotal
    
    def normalize_vector(self, vector: list[float]) -> list[float]:
        try:
            import numpy as np
            import faiss
            arr = np.array([vector], dtype=np.float32)
            faiss.normalize_L2(arr)
            return arr[0].tolist()
        except Exception:
            return vector
    
    def get_index_info(self) -> dict[str, Any]:
        with self._lock:
            if not self.index:
                return {"type": "none", "count": 0}
            
            info = {
                "type": self._index_type,
                "count": self.index.ntotal,
                "dimension": self.dimension,
                "is_trained": self._is_trained,
            }
            
            if self._index_type == "ivf":
                info["nlist"] = self.index.nlist if hasattr(self.index, 'nlist') else 0
            elif self._index_type == "pq":
                info["m"] = self.index.pq.M if hasattr(self.index, 'pq') else 0
                info["nbits"] = self.index.pq.nbits if hasattr(self.index, 'pq') else 0
            elif self._index_type == "ivf_pq":
                info["nlist"] = self.index.nlist if hasattr(self.index, 'nlist') else 0
                info["m"] = self.index.pq.M if hasattr(self.index, 'pq') else 0
            
            return info
    
    async def optimize_index(self, target_size: int = 0) -> bool:
        with self._write_lock:
            if not self._initialized or not self.index:
                return False
            
            try:
                current_count = self.index.ntotal
                expected_size = target_size or current_count
                
                if expected_size <= 0:
                    return True
                
                import numpy as np
                import faiss
                
                if self.index.ntotal > 0:
                    all_vectors = np.zeros((self.index.ntotal, self.dimension), dtype=np.float32)
                    self.index.reconstruct_n(0, self.index.ntotal, all_vectors)
                else:
                    all_vectors = None
                
                new_index = FaissIndexBuilder(self.dimension).build_auto_index(expected_size)
                
                if all_vectors is not None and all_vectors.shape[0] > 0:
                    if hasattr(new_index, 'train') and self._index_type in ("ivf", "pq", "ivf_pq"):
                        new_index.train(all_vectors)
                    new_index.add(all_vectors)
                
                self.index = new_index
                self._is_trained = True
                
                logger.info(f"索引优化完成, 新类型: {self._index_type}")
                return True
                
            except Exception as e:
                logger.error(f"优化索引失败: {e}", exc_info=True)
                return False
