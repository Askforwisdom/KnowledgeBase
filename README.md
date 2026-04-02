# Knowledge Base System

智能知识库系统 - 基于向量检索的知识管理后端服务

## 功能特性

- 向量化知识存储与检索
- 支持多种嵌入模型（Qwen3-Embedding）
- FAISS 向量索引，支持高效相似度搜索
- 多知识类型管理（表单结构、SDK文档等）
- FastAPI RESTful API 接口
- 批量导入与流式处理

## 环境要求

- Python >= 3.10
- CUDA（可选，用于 GPU 加速）

## 快速开始

### 1. 克隆项目

```bash
git clone <repository-url>
cd KnowledgeBaseSystem
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -e .
```

### 4. 下载嵌入模型

运行模型下载脚本：

```bash
python scripts/download_models.py
```

或手动下载：

```bash
# 下载 Qwen3-Embedding-0.6B（推荐，适合 8GB 显存）
huggingface-cli download Qwen/Qwen3-Embedding-0.6B --local-dir ./models/embedding/Qwen3-Embedding-0.6B

# 或下载 Qwen3-Embedding-4B（更强效果，需要更多显存）
huggingface-cli download Qwen/Qwen3-Embedding-4B --local-dir ./models/embedding/Qwen3-Embedding-4B/Qwen/Qwen3-Embedding-4B
```

### 5. 配置环境变量

```bash
cp .env.example .env
# 根据需要修改 .env 配置
```

### 6. 启动服务

```bash
python server.py
```

服务启动后访问：
- API 文档：http://localhost:8000/docs
- 服务状态：http://localhost:8000/

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/knowledge/import` | POST | 导入知识（文件或目录） |
| `/api/knowledge/search` | POST | 搜索知识 |
| `/api/knowledge/rebuild-index` | POST | 重建索引 |
| `/api/knowledge/clear` | DELETE | 清空知识库 |
| `/api/model-info` | GET | 获取模型信息 |

### 搜索示例

```bash
curl -X POST "http://localhost:8000/api/knowledge/search" \
  -F "queries=凭证" \
  -F "knowledge_type=form_structure"
```

## 配置说明

主要配置项（`.env` 文件）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `PROJECT_NAME` | Knowledge Base System | 项目名称 |
| `EMBEDDING_MODEL` | qwen3-0.6b | 嵌入模型 |
| `EMBEDDING_DIMENSION` | 1024 | 向量维度 |
| `API_HOST` | 0.0.0.0 | 服务主机 |
| `API_PORT` | 8000 | 服务端口 |

## 可用嵌入模型

| 模型键 | 模型名称 | 维度 | 说明 |
|--------|----------|------|------|
| `qwen3-0.6b` | Qwen3-Embedding-0.6B | 1024 | 轻量级，适合 8GB 显存 |
| `qwen3` | Qwen3-Embedding-4B | 2560 | 更强效果，需要更多显存 |
| `qwen3-gguf` | Qwen3-Embedding-4B-GGUF Q5 | 2560 | GGUF 格式，适合 CPU |
| `none` | - | - | 禁用嵌入模型 |

## 系统架构

### 文档索引流程 (Document Indexing Workflow)

系统通过以下流程将 Markdown 文档索引到向量数据库：

```
┌─────────────────────────────────────────┐
│  01  Markdown文档                        │
│      Source Documents                     │
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│  02  分类解析                            │
│      Classification Parsing               │
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│  03  Embedding向量化                     │
│      Text Embedding                       │
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│  04  分类存储向量信息                     │
│      Vector Database Storage              │
└─────────────────────────────────────────┘
```

**流程说明：**
1. **Markdown文档** - 原始知识文档输入（表单结构、SDK文档等）
2. **分类解析** - 根据文档类型和元数据进行分类解析
3. **Embedding向量化** - 使用 Qwen3-Embedding 模型将文本转换为向量
4. **分类存储向量信息** - 将向量数据分类存储到 FAISS 向量索引中

### 检索流程 (Retrieval Workflow)

系统通过以下流程处理用户查询并返回相关知识：

```
┌─────────────────────────────────────────┐
│  01  查询文本                            │
│      Query Input                          │
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│  02  需求拆解                            │
│      [Skill]  [Prompt]                    │
│      Decomposition                        │
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│  03  分类检索文本                        │
│      Classification Retrieval             │
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│  04  Embedding向量化                     │
│      Query Embedding                      │
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│  05  Return TOP K                        │
│      Semantic Search                      │
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│  06  筛选                                │
│      [Skill]  [Prompt]                    │
│      Filtering                            │
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│  07  加载文档数据                         │
│      [Skill]                              │
│      Document Loading                     │
└─────────────────────────────────────────┘
```

**流程说明：**
1. **查询文本** - 用户输入的查询内容
2. **需求拆解** - 使用 Skill 和 Prompt 对查询进行意图分析和拆解
3. **分类检索文本** - 根据知识类型进行定向检索
4. **Embedding向量化** - 将查询文本转换为向量表示
5. **Return TOP K** - 在向量数据库中进行语义相似度搜索，返回最相关的 K 个结果
6. **筛选** - 使用 Skill 和 Prompt 对检索结果进行相关性筛选和排序
7. **加载文档数据** - 加载最终筛选后的文档内容返回给用户

## 目录结构

```
KnowledgeBaseKingdee/
├── OriginalKnowledgeData/   # 知识数据
│   ├── formStructure/       # 表单结构文档
│   └── sdk_docs/            # SDK 文档
├── data/                    # 运行时数据（自动生成）
│   ├── form_structure_index/
│   ├── sdk_vector_index/
│   └── knowledge.db
├── models/                  # 模型文件（需下载）
│   └── embedding/
├── src/                     # 源代码
│   ├── api/                 # API 路由
│   ├── config.py            # 配置
│   ├── knowledge/           # 知识管理
│   └── services/            # 服务层
├── scripts/                 # 工具脚本
├── server.py                # 服务入口
└── pyproject.toml           # 项目配置
```

## 开发

### 运行测试

```bash
pytest
```

### 代码格式化

```bash
black .
ruff check .
```

## License

MIT
