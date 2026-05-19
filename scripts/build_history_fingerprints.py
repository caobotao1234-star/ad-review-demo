#!/usr/bin/env python3
"""
傻瓜式脚本：从历史视频生成指纹库 data/history_fingerprints.json

用法：
1. 把历史违规/安全视频放到 history_videos/ 目录下
2. 编辑下面的 HISTORY_VIDEOS 列表
3. 运行: python scripts/build_history_fingerprints.py

输出：data/history_fingerprints.json（会覆盖原文件）
"""
import json
import sys
from pathlib import Path

# 确保能 import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.schemas import AdMeta, Merchant, Qualification, RuntimeConfig
from modules.media_preprocess import MediaPreprocessor
from modules.utils import compute_file_md5

# ============================================================
# 在这里编辑你的历史视频列表
# label: "violation" = 明确违规, "safe" = 明确安全
# ============================================================
HISTORY_VIDEOS = [
    {
        "path": "history_videos/violation_001.mp4",
        "label": "violation",
        "violation_type": "brand_counterfeit",
        "note": "示例：仿冒品牌箱包广告",
    },
    {
        "path": "history_videos/violation_002.mp4",
        "label": "violation",
        "violation_type": "financial_fraud",
        "note": "示例：虚假金融理财广告",
    },
    {
        "path": "history_videos/safe_001.mp4",
        "label": "safe",
        "note": "示例：正规日用品广告",
    },
    # 添加更多...
]


def main():
    runtime = RuntimeConfig()
    cache_root = Path("outputs/cache")
    preprocessor = MediaPreprocessor(runtime, cache_root)

    fingerprints = []
    for i, video in enumerate(HISTORY_VIDEOS, 1):
        video_path = Path(video["path"])
        if not video_path.exists():
            print(f"  ✗ 跳过（文件不存在）: {video['path']}")
            continue

        ad = AdMeta(
            ad_id=f"hist_{i:03d}",
            media_path=str(video_path),
            merchant=Merchant(merchant_id="history_builder", qualification=Qualification()),
        )
        result = preprocessor.process(ad)

        if result.mock:
            print(f"  ✗ 处理失败: {video['path']} (reason: {result.fallback_reason})")
            continue

        file_md5 = compute_file_md5(video_path)

        entry = {
            "history_id": f"hist_{i:03d}",
            "label": video["label"],
            "md5": file_md5,
            "phash_list": result.fingerprint.phash_list,
            "note": video.get("note", ""),
        }
        if video.get("violation_type"):
            entry["violation_type"] = video["violation_type"]

        fingerprints.append(entry)
        print(f"  ✓ {video['path']} → {len(result.fingerprint.phash_list)} 帧指纹, label={video['label']}")

    # 写入
    output_path = Path("data/history_fingerprints.json")
    output_path.write_text(
        json.dumps({"fingerprints": fingerprints}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n完成！写入 {len(fingerprints)} 条指纹到 {output_path}")
    print(f"（如果某些视频被跳过，请检查文件路径是否正确）")


if __name__ == "__main__":
    main()
