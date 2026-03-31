"""
智能知识库系统
独立后端服务入口
"""
import logging
import argparse
import os
from pathlib import Path
from contextlib import asynccontextmanager

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from src.api import router as ai_router
from src.config import settings
from src.knowledge import knowledge_manager
from src.services.embedding import embedding_service

logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("启动知识库服务...")
    
    logger.info(f"初始化嵌入模型: {settings.embedding_model}")
    await embedding_service.initialize()
    
    if embedding_service.is_available:
        logger.info(f"嵌入模型已加载，设备: {embedding_service.device}")
    else:
        logger.warning("嵌入模型未加载，向量功能将受限")
    
    await knowledge_manager.initialize()
    logger.info("知识库服务启动完成")
    
    yield
    
    logger.info("关闭知识库服务...")
    await knowledge_manager.builder.store.close()
    logger.info("知识库服务已关闭")


app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    description="智能知识库系统后端服务",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_router)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), media_type="text/html")
    return {
        "name": settings.project_name,
        "version": settings.version,
        "status": "running",
        "description": "知识库后端服务",
    }


@app.get("/api/model-info")
async def get_model_info():
    """获取当前嵌入模型信息"""
    return embedding_service.get_model_info()


def main():
    parser = argparse.ArgumentParser(description="知识库后端服务")
    parser.add_argument("--host", default=settings.api_host, help="服务主机地址")
    parser.add_argument("--port", type=int, default=settings.api_port, help="服务端口")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"  知识库后端服务")
    print(f"  版本: {settings.version}")
    print(f"{'='*60}")
    print(f"  服务地址: http://{args.host}:{args.port}")
    print(f"  API文档: http://{args.host}:{args.port}/docs")
    print(f"  调试模式: {'开启' if args.debug else '关闭'}")
    print(f"{'='*60}\n")
    
    config = uvicorn.Config(
        app=app,
        host=args.host,
        port=args.port,
        log_level="debug" if args.debug else "info",
        access_log=False,
    )
    server = uvicorn.Server(config=config)
    server.run()


if __name__ == "__main__":
    main()
