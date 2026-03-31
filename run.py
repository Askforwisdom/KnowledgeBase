"""
启动脚本
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("知识库服务启动中...")
print("=" * 60)

from src.config import settings
print(f"项目名称: {settings.project_name}")
print(f"版本: {settings.version}")
print(f"启用嵌入模型: {settings.enable_embedding}")
print("=" * 60)

if __name__ == "__main__":
    print("\n启动Web服务器...")
    print("API文档: http://localhost:8000/docs")
    print("=" * 60)
    
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
