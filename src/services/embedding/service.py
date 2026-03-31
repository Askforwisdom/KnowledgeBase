"""
嵌入模型服务
专门管理嵌入模型的加载和切换
支持 SentenceTransformer 和 GGUF 格式模型
"""
import logging
from typing import Any, Optional

from src.config import settings

logger = logging.getLogger(__name__)

_torch_checked = False
_torch_available = False
_st_checked = False
_st_available = False
_bnb_checked = False
_bnb_available = False
_llama_checked = False
_llama_available = False


def _is_torch_available() -> bool:
    global _torch_available, _torch_checked
    if _torch_checked:
        return _torch_available
    _torch_checked = True
    try:
        import torch
        _torch_available = True
    except ImportError:
        _torch_available = False
    return _torch_available


def _is_sentence_transformers_available() -> bool:
    global _st_available, _st_checked
    if _st_checked:
        return _st_available
    _st_checked = True
    try:
        import sentence_transformers
        _st_available = True
    except ImportError:
        _st_available = False
    return _st_available


def _is_bitsandbytes_available() -> bool:
    global _bnb_available, _bnb_checked
    if _bnb_checked:
        return _bnb_available
    _bnb_checked = True
    try:
        import bitsandbytes
        _bnb_available = True
    except ImportError:
        _bnb_available = False
    return _bnb_available


def _is_llama_cpp_available() -> bool:
    global _llama_available, _llama_checked
    if _llama_checked:
        return _llama_available
    _llama_checked = True
    try:
        import llama_cpp
        _llama_available = True
    except ImportError:
        _llama_available = False
    return _llama_available


class EmbeddingService:
    """嵌入模型服务 - 管理嵌入模型的加载和切换，支持多种模型格式"""
    
    def __init__(self) -> None:
        self.model = None
        self.current_model_key: str = settings.embedding_model
        self._initialized = False
        self._device: Optional[str] = None
        self._quantization: Optional[str] = None
        self._model_type: Optional[str] = None
    
    @property
    def is_available(self) -> bool:
        return self._initialized and self.model is not None
    
    @property
    def device(self) -> str:
        return self._device or "cpu"
    
    @property
    def quantization(self) -> str:
        return self._quantization or "none"
    
    @property
    def model_type(self) -> str:
        return self._model_type or "unknown"
    
    async def initialize(self, model_key: Optional[str] = None) -> bool:
        if self._initialized:
            logger.info("嵌入模型已初始化")
            return True
        
        if not settings.enable_embedding:
            logger.info("嵌入模型已禁用")
            return True
        
        if model_key:
            self.current_model_key = model_key
        
        model_config = settings.get_embedding_model_config(self.current_model_key)
        model_name = model_config.get("name")
        model_type = model_config.get("type", "sentence_transformers")
        
        if not model_name:
            logger.info("模型名称为空，跳过加载")
            self.model = None
            self._initialized = True
            return True
        
        self._model_type = model_type
        
        if model_type == "gguf":
            return await self._load_model_gguf(model_name, model_config)
        elif model_type == "sentence_transformers":
            return await self._load_model_sentence_transformers_wrapper(model_name)
        elif model_type == "none":
            logger.info("嵌入模型类型为 none，跳过加载")
            self.model = None
            self._initialized = True
            return True
        else:
            logger.warning(f"未知的模型类型: {model_type}")
            return False
    
    async def _load_model_gguf(self, model_path: str, model_config: dict) -> bool:
        """加载 GGUF 格式模型"""
        if not _is_llama_cpp_available():
            logger.warning("llama-cpp-python 不可用，无法加载 GGUF 模型")
            return False
        
        try:
            from llama_cpp import Llama
            
            logger.info(f"正在加载 GGUF 模型: {model_path}")
            
            n_gpu_layers = 0
            if _is_torch_available():
                import torch
                if torch.cuda.is_available():
                    n_gpu_layers = -1
            
            self.model = Llama(
                model_path=model_path,
                embedding=True,
                n_gpu_layers=n_gpu_layers,
                n_ctx=8192,
                verbose=False,
            )
            
            self._device = "cuda" if n_gpu_layers != 0 else "cpu"
            self._quantization = "gguf"
            self._initialized = True
            
            logger.info(f"加载 GGUF 模型成功: {model_path}, 设备: {self._device}")
            return True
            
        except Exception as e:
            logger.error(f"加载 GGUF 模型失败: {e}", exc_info=True)
            self.model = None
            return False
    
    async def _load_model_sentence_transformers_wrapper(self, model_name: str) -> bool:
        """SentenceTransformer 模型加载包装"""
        if not _is_sentence_transformers_available():
            logger.warning("sentence_transformers 不可用，嵌入功能将受限")
            return False
        
        if not _is_torch_available():
            logger.warning("torch 不可用，嵌入功能将受限")
            return False
        
        quantization = settings.embedding_quantization.lower()
        
        if _is_torch_available():
            import torch
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            
            if self._device == "cuda" and quantization in ("4bit", "8bit"):
                if not _is_bitsandbytes_available():
                    logger.warning(f"bitsandbytes 不可用，无法使用 {quantization} 量化，回退到 FP16")
                    return self._load_model_sentence_transformers(model_name)
                
                return self._load_model_quantized(model_name, quantization)
            else:
                return self._load_model_sentence_transformers(model_name)
        else:
            return self._load_model_sentence_transformers(model_name)
    
    def _load_model_sentence_transformers(self, model_name: str) -> bool:
        """使用 SentenceTransformer 加载模型"""
        try:
            from sentence_transformers import SentenceTransformer
            import torch
            
            if self._device == "cuda":
                self.model = SentenceTransformer(model_name, device=self._device, trust_remote_code=True)
                self.model.half()
                self._quantization = "fp16"
            else:
                self.model = SentenceTransformer(model_name, device=self._device)
                self._quantization = "fp32"
            
            logger.info(f"加载嵌入模型成功: {model_name}, 设备: {self._device}, 精度: {self._quantization.upper()}")
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"加载嵌入模型失败: {e}", exc_info=True)
            self.model = None
            return False
    
    def _load_model_quantized(self, model_name: str, quantization: str) -> bool:
        """使用量化加载模型"""
        try:
            from transformers import AutoModel, AutoTokenizer, BitsAndBytesConfig
            import torch
            
            if quantization == "4bit":
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4"
                )
            elif quantization == "8bit":
                quantization_config = BitsAndBytesConfig(
                    load_in_8bit=True,
                )
            else:
                return self._load_model_sentence_transformers(model_name)
            
            logger.info(f"正在加载量化模型: {model_name}, 量化模式: {quantization}")
            
            tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            model = AutoModel.from_pretrained(
                model_name,
                trust_remote_code=True,
                quantization_config=quantization_config,
                device_map="auto"
            )
            
            self.model = {
                "model": model,
                "tokenizer": tokenizer,
                "type": "transformers"
            }
            self._quantization = quantization
            self._initialized = True
            
            logger.info(f"加载量化嵌入模型成功: {model_name}, 设备: {self._device}, 量化: {quantization}")
            return True
            
        except Exception as e:
            logger.error(f"量化加载失败: {e}, 回退到 SentenceTransformer", exc_info=True)
            return self._load_model_sentence_transformers(model_name)
    
    def generate_embedding(self, text: str) -> Optional[list[float]]:
        """生成文本嵌入向量"""
        if self.model is None:
            return None
        
        try:
            if self._model_type == "gguf":
                return self._generate_embedding_gguf(text)
            elif isinstance(self.model, dict) and self.model.get("type") == "transformers":
                return self._generate_embedding_transformers(text)
            else:
                return self._generate_embedding_sentence_transformers(text)
        except Exception as e:
            logger.error(f"生成嵌入向量失败: {e}", exc_info=True)
            return None
    
    def _generate_embedding_gguf(self, text: str) -> Optional[list[float]]:
        """使用 GGUF 模型生成嵌入"""
        try:
            embedding = self.model.embed(text)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"GGUF 嵌入生成失败: {e}", exc_info=True)
            return None
    
    def _generate_embedding_sentence_transformers(self, text: str) -> Optional[list[float]]:
        """使用 SentenceTransformer 生成嵌入"""
        import torch
        
        with torch.no_grad():
            embedding = self.model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
    
    def _generate_embedding_transformers(self, text: str) -> Optional[list[float]]:
        """使用 Transformers 模型生成嵌入"""
        import torch
        
        model = self.model["model"]
        tokenizer = self.model["tokenizer"]
        
        with torch.no_grad():
            inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=8192)
            inputs = {k: v.to(model.device) for k, v in inputs.items()}
            
            outputs = model(**inputs)
            
            last_hidden_state = outputs.last_hidden_state
            attention_mask = inputs["attention_mask"]
            
            mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
            sum_embeddings = torch.sum(last_hidden_state * mask_expanded, dim=1)
            sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
            embedding = (sum_embeddings / sum_mask).squeeze(0)
            
            return embedding.cpu().numpy().tolist()
    
    def generate_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """批量生成嵌入向量"""
        if self.model is None:
            return [None] * len(texts)
        
        try:
            if self._model_type == "gguf":
                return [self._generate_embedding_gguf(text) for text in texts]
            elif isinstance(self.model, dict) and self.model.get("type") == "transformers":
                return [self._generate_embedding_transformers(text) for text in texts]
            else:
                import torch
                with torch.no_grad():
                    embeddings = self.model.encode(texts, convert_to_tensor=True)
                    return [emb.cpu().numpy().tolist() for emb in embeddings]
        except Exception as e:
            logger.error(f"批量生成嵌入向量失败: {e}", exc_info=True)
            return [None] * len(texts)
    
    def switch_model(self, model_key: str) -> dict[str, Any]:
        if model_key not in settings.available_embedding_models:
            return {"success": False, "message": f"未知的模型: {model_key}"}
        
        old_key = self.current_model_key
        old_model = self.model
        
        self.current_model_key = model_key
        self._initialized = False
        
        import asyncio
        if asyncio.run(self.initialize()):
            model_config = settings.get_embedding_model_config(model_key)
            return {
                "success": True,
                "message": f"已切换到模型: {model_config.get('name')}",
                "model_key": model_key,
                "device": self._device,
                "quantization": self._quantization,
                "model_type": self._model_type,
            }
        else:
            self.current_model_key = old_key
            self.model = old_model
            self._initialized = True
            return {"success": False, "message": "模型加载失败"}
    
    def get_model_info(self) -> dict[str, Any]:
        model_config = settings.get_embedding_model_config(self.current_model_key)
        return {
            "model_key": self.current_model_key,
            "model_name": model_config.get("name"),
            "model_dimension": model_config.get("dimension"),
            "model_type": self._model_type,
            "is_loaded": self.model is not None,
            "device": self._device,
            "quantization": self._quantization,
            "is_initialized": self._initialized,
        }
    
    def get_dimension(self) -> int:
        model_config = settings.get_embedding_model_config(self.current_model_key)
        return model_config.get("dimension", settings.embedding_dimension)


embedding_service = EmbeddingService()
