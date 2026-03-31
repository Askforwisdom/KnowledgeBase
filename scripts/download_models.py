"""
嵌入模型下载脚本
自动下载项目所需的嵌入模型
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


MODELS = {
    "qwen3-0.6b": {
        "repo": "Qwen/Qwen3-Embedding-0.6B",
        "local_dir": "./models/embedding/Qwen3-Embedding-0.6B",
        "description": "Qwen3-Embedding-0.6B 轻量级模型 (1024维, 适合8GB显存)",
        "size": "~1.2GB",
    },
    "qwen3-4b": {
        "repo": "Qwen/Qwen3-Embedding-4B",
        "local_dir": "./models/embedding/Qwen3-Embedding-4B/Qwen/Qwen3-Embedding-4B",
        "description": "Qwen3-Embedding-4B 标准模型 (2560维, 需要更多显存)",
        "size": "~8GB",
    },
    "qwen3-4b-gguf": {
        "repo": "Qwen/Qwen3-Embedding-4B-GGUF",
        "local_dir": "./models/embedding/Qwen3-Embedding-4B-GGUF",
        "description": "Qwen3-Embedding-4B GGUF格式 (适合CPU推理)",
        "size": "~3GB",
        "include": "Q5_K_M",  # 只下载 Q5_K_M 量化版本
    },
}


def check_huggingface_cli() -> bool:
    """检查 huggingface-cli 是否可用"""
    try:
        result = subprocess.run(
            ["huggingface-cli", "--help"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def install_huggingface_hub() -> bool:
    """安装 huggingface_hub"""
    print("正在安装 huggingface_hub...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "huggingface_hub[cli]"],
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def download_model(model_key: str, force: bool = False) -> bool:
    """下载指定模型"""
    if model_key not in MODELS:
        print(f"错误: 未知的模型 '{model_key}'")
        print(f"可用模型: {', '.join(MODELS.keys())}")
        return False

    model = MODELS[model_key]
    local_dir = Path(model["local_dir"])

    if local_dir.exists() and not force:
        print(f"模型已存在: {local_dir}")
        print("使用 --force 参数强制重新下载")
        return True

    print(f"\n{'='*60}")
    print(f"下载模型: {model['description']}")
    print(f"仓库: {model['repo']}")
    print(f"目标目录: {local_dir}")
    print(f"大小: {model['size']}")
    print(f"{'='*60}\n")

    local_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "huggingface-cli", "download",
        model["repo"],
        "--local-dir", str(local_dir),
    ]

    if "include" in model:
        cmd.extend(["--include", f"*{model['include']}*"])

    try:
        subprocess.run(cmd, check=True)
        print(f"\n模型下载完成: {local_dir}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n下载失败: {e}")
        return False


def download_all(force: bool = False) -> None:
    """下载所有模型"""
    print("下载所有嵌入模型...\n")
    success_count = 0
    for model_key in MODELS:
        if download_model(model_key, force):
            success_count += 1

    print(f"\n下载完成: {success_count}/{len(MODELS)} 个模型")


def list_models() -> None:
    """列出所有可用模型"""
    print("\n可用嵌入模型:\n")
    print(f"{'模型键':<20} {'描述':<40} {'大小':<10}")
    print("-" * 70)
    for key, model in MODELS.items():
        print(f"{key:<20} {model['description'][:40]:<40} {model['size']:<10}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="嵌入模型下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/download_models.py              # 下载默认模型 (qwen3-0.6b)
  python scripts/download_models.py --all        # 下载所有模型
  python scripts/download_models.py qwen3-4b     # 下载指定模型
  python scripts/download_models.py --list       # 列出所有可用模型
  python scripts/download_models.py --force      # 强制重新下载
        """,
    )

    parser.add_argument(
        "model",
        nargs="?",
        default="qwen3-0.6b",
        help="要下载的模型名称 (默认: qwen3-0.6b)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="下载所有模型",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有可用模型",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新下载已存在的模型",
    )

    args = parser.parse_args()

    os.chdir(Path(__file__).parent.parent)

    if not check_huggingface_cli():
        print("huggingface-cli 不可用")
        if not install_huggingface_hub():
            print("安装 huggingface_hub 失败，请手动安装:")
            print("  pip install huggingface_hub[cli]")
            sys.exit(1)

    if args.list:
        list_models()
        return

    if args.all:
        download_all(args.force)
    else:
        download_model(args.model, args.force)


if __name__ == "__main__":
    main()
