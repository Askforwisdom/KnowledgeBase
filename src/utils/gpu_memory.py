"""
GPU 显存管理模块
提供 GPU 显存监控、优化和清理功能
"""
import gc
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_gpu_available = None
_gpu_memory_manager = None


def check_gpu_available() -> bool:
    global _gpu_available
    if _gpu_available is not None:
        return _gpu_available
    
    try:
        import torch
        _gpu_available = torch.cuda.is_available()
        return _gpu_available
    except ImportError:
        _gpu_available = False
        return False


def get_memory_info() -> dict:
    """获取系统内存信息"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / 1024**3, 2),
            "available_gb": round(mem.available / 1024**3, 2),
            "used_gb": round(mem.used / 1024**3, 2),
            "percent": mem.percent,
        }
    except Exception as e:
        return {"error": str(e)}


def check_memory_available(required_gb: float = 1.0) -> bool:
    """检查是否有足够的可用内存"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        return mem.available >= required_gb * 1024**3
    except Exception:
        return False


def get_safe_batch_size(
    default_batch_size: int = 64,
    min_batch_size: int = 16,
    memory_per_sample_mb: float = 10.0,
) -> int:
    """根据可用内存计算安全的批处理大小"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        
        safe_available = mem.available * 0.5
        
        available_mb = safe_available / 1024**2
        calculated_batch = int(available_mb / memory_per_sample_mb)
        
        return max(min_batch_size, min(calculated_batch, default_batch_size))
    except Exception:
        return min_batch_size


def get_gpu_info() -> dict:
    if not check_gpu_available():
        return {"available": False, "system_memory": get_memory_info()}
    
    try:
        import torch
        
        device_count = torch.cuda.device_count()
        devices = []
        
        for i in range(device_count):
            props = torch.cuda.get_device_properties(i)
            memory_allocated = torch.cuda.memory_allocated(i)
            memory_reserved = torch.cuda.memory_reserved(i)
            memory_free = props.total_memory - memory_reserved
            
            devices.append({
                "index": i,
                "name": props.name,
                "total_memory_gb": round(props.total_memory / 1024**3, 2),
                "allocated_memory_gb": round(memory_allocated / 1024**3, 3),
                "reserved_memory_gb": round(memory_reserved / 1024**3, 3),
                "free_memory_gb": round(memory_free / 1024**3, 3),
                "compute_capability": f"{props.major}.{props.minor}",
                "utilization_percent": round(memory_allocated / props.total_memory * 100, 1),
            })
        
        return {
            "available": True,
            "cuda_version": torch.version.cuda,
            "device_count": device_count,
            "devices": devices,
            "system_memory": get_memory_info(),
        }
    except Exception as e:
        logger.error(f"获取 GPU 信息失败: {e}")
        return {"available": False, "error": str(e), "system_memory": get_memory_info()}


def clear_gpu_cache() -> dict:
    if not check_gpu_available():
        return {"success": False, "message": "GPU 不可用"}
    
    try:
        import torch
        
        before_allocated = torch.cuda.memory_allocated()
        before_reserved = torch.cuda.memory_reserved()
        
        torch.cuda.empty_cache()
        gc.collect()
        
        after_allocated = torch.cuda.memory_allocated()
        after_reserved = torch.cuda.memory_reserved()
        
        freed_reserved = before_reserved - after_reserved
        
        return {
            "success": True,
            "before_allocated_mb": round(before_allocated / 1024**2, 2),
            "after_allocated_mb": round(after_allocated / 1024**2, 2),
            "before_reserved_mb": round(before_reserved / 1024**2, 2),
            "after_reserved_mb": round(after_reserved / 1024**2, 2),
            "freed_mb": round(freed_reserved / 1024**2, 2),
        }
    except Exception as e:
        logger.error(f"清理 GPU 缓存失败: {e}")
        return {"success": False, "error": str(e)}


def get_optimal_batch_size(
    model_memory_mb: float = 600,
    safety_factor: float = 0.5,
    min_batch_size: int = 16,
    max_batch_size: int = 64,
) -> int:
    """计算最优批处理大小，同时考虑 GPU 显存和系统内存"""
    
    system_safe_batch = get_safe_batch_size(
        default_batch_size=max_batch_size,
        min_batch_size=min_batch_size,
        memory_per_sample_mb=10.0,
    )
    
    if not check_gpu_available():
        return system_safe_batch
    
    try:
        import torch
        
        props = torch.cuda.get_device_properties(0)
        memory_allocated = torch.cuda.memory_allocated(0)
        memory_reserved = torch.cuda.memory_reserved(0)
        
        free_memory = props.total_memory - memory_reserved
        usable_memory = free_memory * safety_factor
        
        estimated_samples = int(usable_memory / (model_memory_mb * 1024**2))
        
        gpu_optimal_batch = max(min_batch_size, min(estimated_samples, max_batch_size))
        
        return min(gpu_optimal_batch, system_safe_batch)
    except Exception as e:
        logger.warning(f"计算最优批处理大小失败: {e}")
        return system_safe_batch


def set_memory_fraction(fraction: float = 0.6) -> bool:
    if not check_gpu_available():
        return False
    
    try:
        import torch
        torch.cuda.set_per_process_memory_fraction(fraction)
        logger.info(f"设置 GPU 显存使用比例: {fraction * 100}%")
        return True
    except Exception as e:
        logger.warning(f"设置 GPU 显存比例失败: {e}")
        return False


class GPUMemoryManager:
    def __init__(self, memory_fraction: float = 0.6, max_memory_gb: float = 4.0):
        self.memory_fraction = memory_fraction
        self.max_memory_gb = max_memory_gb
        self._initialized = False
    
    def initialize(self) -> bool:
        if self._initialized:
            return True
        
        if not check_gpu_available():
            logger.info("GPU 不可用，使用 CPU 模式")
            self._initialized = True
            return False
        
        try:
            import torch
            
            set_memory_fraction(self.memory_fraction)
            
            props = torch.cuda.get_device_properties(0)
            logger.info(f"GPU 显存管理器初始化完成")
            logger.info(f"  GPU: {props.name}")
            logger.info(f"  显存: {props.total_memory / 1024**3:.1f} GB")
            logger.info(f"  显存限制: {self.memory_fraction * 100}%")
            logger.info(f"  最大内存使用: {self.max_memory_gb} GB")
            
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"GPU 显存管理器初始化失败: {e}")
            return False
    
    def get_status(self) -> dict:
        return get_gpu_info()
    
    def clear_cache(self) -> dict:
        return clear_gpu_cache()
    
    def get_optimal_batch_size(self, model_memory_mb: float = 600) -> int:
        return get_optimal_batch_size(model_memory_mb)
    
    def check_memory_available(self, required_mb: float) -> bool:
        if not check_gpu_available():
            return check_memory_available(required_mb / 1024)
        
        try:
            import torch
            
            props = torch.cuda.get_device_properties(0)
            memory_reserved = torch.cuda.memory_reserved(0)
            free_memory = props.total_memory - memory_reserved
            
            return free_memory >= required_mb * 1024**2
        except Exception:
            return False
    
    def safe_execute(self, func, *args, **kwargs):
        """安全执行函数，自动处理内存不足"""
        try:
            if not self.check_memory_available(500):
                self.clear_cache()
            
            return func(*args, **kwargs)
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                logger.warning("GPU 显存不足，尝试清理缓存后重试")
                self.clear_cache()
                gc.collect()
                return func(*args, **kwargs)
            raise


gpu_memory_manager = GPUMemoryManager()
