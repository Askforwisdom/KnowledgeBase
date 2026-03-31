"""
智能知识库系统配置模块
"""
from pathlib import Path
from typing import Any, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "Knowledge Base System"
    version: str = "1.0.0"
    debug: bool = False

    base_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent)
    data_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "data")
    knowledge_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "knowledge")
    logs_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "logs")

    enable_embedding: bool = True
    embedding_model: str = "qwen3-0.6b"
    embedding_dimension: int = 1024
    similarity_threshold: float = 0.7
    embedding_quantization: str = "fp16"
    
    vector_backend: str = "faiss"
    
    embedding_batch_size: int = 256
    embedding_max_memory_gb: float = 4.0
    
    import_max_workers: int = 4
    import_batch_size: int = 256
    import_chunk_batch_size: int = 512
    
    chunk_max_size: int = 1000
    chunk_min_size: int = 100
    chunk_overlap_size: int = 100
    chunk_max_per_knowledge: int = 50
    
    streaming_chunk_size: int = 65536
    streaming_read_ahead: int = 3
    
    token_bucket_short: int = 64
    token_bucket_medium: int = 256
    token_bucket_long: int = 1024
    batch_size_short: int = 256
    batch_size_medium: int = 64
    batch_size_long: int = 16
    
    dynamic_batch_min: int = 16
    dynamic_batch_max: int = 512
    dynamic_batch_memory_threshold: float = 0.85
    
    async_commit_batch_size: int = 1000
    async_commit_delay_ms: int = 100
    
    faiss_use_ivf: bool = False
    faiss_ivf_nlist: int = 100
    faiss_use_pq: bool = False
    faiss_pq_m: int = 8
    faiss_pq_nbits: int = 8
    
    cpu_multiprocess: bool = True
    cpu_max_processes: int = 4

    available_embedding_models: dict[str, dict[str, Any]] = {
        "qwen3-gguf": {
            "name": "./models/embedding/Qwen3-Embedding-4B-GGUF/Qwen3-Embedding-4B-Q5_K_M.gguf",
            "dimension": 2560,
            "type": "gguf",
            "description": "Qwen3-Embedding-4B Q5_K_M 量化版，GGUF格式，适合CPU推理",
        },
        "qwen3-gguf-q4": {
            "name": "./models/embedding/Qwen3-Embedding-4B-GGUF/Qwen3-Embedding-4B-Q4_K_M.gguf",
            "dimension": 2560,
            "type": "gguf",
            "description": "Qwen3-Embedding-4B Q4_K_M 量化版，GGUF格式，更小体积",
        },
        "qwen3": {
            "name": "./models/embedding/Qwen3-Embedding-4B/Qwen/Qwen3-Embedding-4B",
            "dimension": 2560,
            "type": "sentence_transformers",
            "description": "Qwen3-Embedding-4B，更强的语义理解能力，支持中文和代码",
        },
        "qwen3-0.6b": {
            "name": "./models/embedding/Qwen3-Embedding-0.6B",
            "dimension": 1024,
            "type": "sentence_transformers",
            "description": "Qwen3-Embedding-0.6B，轻量级模型，适合 8GB 显存",
        },
        "none": {
            "name": None,
            "dimension": 0,
            "type": "none",
            "description": "禁用嵌入模型，仅使用数据库查询",
        },
    }

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"

    max_file_size: int = 50 * 1024 * 1024
    allowed_extensions_str: str = ".md"

    @property
    def allowed_extensions(self) -> set[str]:
        return set(ext.strip() for ext in self.allowed_extensions_str.split(",") if ext.strip())

    platform_version: str = "1.0"
    docs_url: str = ""

    def ensure_directories(self) -> None:
        for directory in [self.data_dir, self.knowledge_dir, self.logs_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    def get_embedding_model_config(self, model_key: str = "qwen3") -> dict[str, Any]:
        return self.available_embedding_models.get(model_key, self.available_embedding_models["qwen3"])


settings = Settings()
