#!/usr/bin/env python3
"""
一键下载所有模型到本地 models/ 目录。

下载完成后，系统运行时不再需要联网。

用法:
    # 国内用户先设置镜像
    export HF_ENDPOINT=https://hf-mirror.com   # Linux/Mac
    $env:HF_ENDPOINT = "https://hf-mirror.com"  # Windows PowerShell

    # 然后运行
    python scripts/download_models.py

下载内容:
    - faster-whisper-small (~500MB) → models/faster-whisper-small/
    - sentence-transformers (~90MB) → models/paraphrase-multilingual-MiniLM-L12-v2/
    - PaddleOCR 中文模型 (~100MB) → models/paddleocr/
"""
import sys
from pathlib import Path

# 确保能 import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

MODELS_DIR = Path("models")
MODELS_DIR.mkdir(exist_ok=True)


def download_whisper():
    """Download faster-whisper model."""
    target = MODELS_DIR / "faster-whisper-small"
    if target.exists() and any(target.iterdir()):
        print(f"  ✓ faster-whisper-small 已存在: {target}")
        return

    print("  ⬇ 下载 faster-whisper-small (~500MB)...")
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(
            "Systran/faster-whisper-small",
            local_dir=str(target),
        )
        print(f"  ✓ 下载完成: {target}")
    except Exception as e:
        print(f"  ✗ 下载失败: {e}")
        print("    提示: 设置 HF_ENDPOINT=https://hf-mirror.com 后重试")


def download_sbert():
    """Download sentence-transformers model."""
    target = MODELS_DIR / "paraphrase-multilingual-MiniLM-L12-v2"
    if target.exists() and any(target.iterdir()):
        print(f"  ✓ sentence-transformers 已存在: {target}")
        return

    print("  ⬇ 下载 paraphrase-multilingual-MiniLM-L12-v2 (~90MB)...")
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        model.save(str(target))
        print(f"  ✓ 下载完成: {target}")
    except ImportError:
        print("  ✗ sentence-transformers 未安装，跳过")
        print("    安装: pip install sentence-transformers")
    except Exception as e:
        print(f"  ✗ 下载失败: {e}")


def download_paddleocr():
    """Download PaddleOCR models."""
    print("  ⬇ 初始化 PaddleOCR（首次会自动下载模型到 ~/.paddleocr/）...")
    try:
        from paddleocr import PaddleOCR
        # PaddleOCR v2: 首次初始化自动下载模型到 ~/.paddleocr/
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        print(f"  ✓ PaddleOCR 初始化成功（模型缓存在 ~/.paddleocr/）")
    except ImportError:
        print("  ✗ paddleocr 未安装，跳过")
        print("    安装: pip install 'paddleocr>=2.7,<3.0' paddlepaddle")
    except Exception as e:
        print(f"  ✗ 初始化失败: {e}")
        print("    尝试: pip uninstall paddleocr -y && pip install 'paddleocr>=2.7,<3.0'")


def main():
    print("=" * 50)
    print("模型一键下载（下载到 models/ 目录）")
    print("=" * 50)
    print()

    import os
    hf_endpoint = os.environ.get("HF_ENDPOINT", "")
    if hf_endpoint:
        print(f"  HF_ENDPOINT = {hf_endpoint}")
    else:
        print("  ⚠ 未设置 HF_ENDPOINT，如果下载慢请设置:")
        print("    export HF_ENDPOINT=https://hf-mirror.com")
    print()

    print("[1/3] faster-whisper (ASR 语音转写)")
    download_whisper()
    print()

    print("[2/3] sentence-transformers (文本嵌入)")
    download_sbert()
    print()

    print("[3/3] PaddleOCR (文字识别)")
    download_paddleocr()
    print()

    print("=" * 50)
    print("完成！模型已下载到 models/ 目录。")
    print("系统运行时将从本地加载，不再联网。")
    print("=" * 50)


if __name__ == "__main__":
    main()
