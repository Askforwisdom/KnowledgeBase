"""
知识导入服务数据模型
使用 Pydantic BaseModel 统一风格
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ImportStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ManageAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    REBUILD_INDEX = "rebuild_index"
    CLEAR_ALL = "clear_all"


class KnowledgeImportRequest(BaseModel):
    source_path: str = Field(description="源文件或目录路径")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


class ImportResult(BaseModel):
    file_path: str = Field(description="文件路径")
    status: ImportStatus = Field(default=ImportStatus.PENDING, description="导入状态")
    knowledge_id: Optional[str] = Field(default=None, description="知识ID")
    knowledge_name: Optional[str] = Field(default=None, description="知识名称")
    chunks_count: int = Field(default=0, description="分块数量")
    error_message: Optional[str] = Field(default=None, description="错误信息")


class KnowledgeImportResponse(BaseModel):
    success: bool = Field(description="是否成功")
    results: list[ImportResult] = Field(default_factory=list, description="导入结果列表")
    total_knowledge: int = Field(default=0, description="知识总数")
    total_chunks: int = Field(default=0, description="分块总数")
    error_count: int = Field(default=0, description="错误数量")
    errors: list[str] = Field(default_factory=list, description="错误列表")
    processing_time_ms: int = Field(default=0, description="处理耗时(毫秒)")


class KnowledgeManageRequest(BaseModel):
    action: ManageAction = Field(description="管理操作类型")
    knowledge_id: Optional[str] = Field(default=None, description="知识ID")
    knowledge_data: Optional[dict[str, Any]] = Field(default=None, description="知识数据")
    parameters: dict[str, Any] = Field(default_factory=dict, description="参数")


class KnowledgeManageResponse(BaseModel):
    success: bool = Field(description="是否成功")
    action: ManageAction = Field(description="操作类型")
    knowledge_id: Optional[str] = Field(default=None, description="知识ID")
    affected_count: int = Field(default=0, description="影响数量")
    message: str = Field(default="", description="消息")
    data: dict[str, Any] = Field(default_factory=dict, description="返回数据")


class KnowledgeStatistics(BaseModel):
    total_knowledge: int = Field(default=0, description="知识总数")
    total_chunks: int = Field(default=0, description="分块总数")
    by_type: dict[str, int] = Field(default_factory=dict, description="按类型统计")
    by_source: dict[str, int] = Field(default_factory=dict, description="按来源统计")
    vector_store_status: dict[str, Any] = Field(default_factory=dict, description="向量库状态")
