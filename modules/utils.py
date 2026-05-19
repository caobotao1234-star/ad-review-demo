"""Common utility functions for the ad-review-layered-decision system."""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from modules.schemas import ReasonCode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Text Normalization
# ---------------------------------------------------------------------------

_REPLACE_TABLE: dict[str, str] = {
    "v信": "微信",
    "ｖ信": "微信",
    "1比1": "1:1",
    "wx": "微信",
}


def compute_file_md5(path: Path) -> str:
    """Compute MD5 hash of a file. Reads in 8KB chunks for efficiency."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def normalize_text(text: str) -> str:
    """Normalize text: NFKC → lowercase → strip whitespace → apply replace table."""
    s = unicodedata.normalize("NFKC", text).lower()
    s = re.sub(r"[\s\u3000]+", "", s)
    for k, v in _REPLACE_TABLE.items():
        s = s.replace(k, v)
    return s


# ---------------------------------------------------------------------------
# pHash Hamming Distance
# ---------------------------------------------------------------------------


def hamming_distance(h1: str, h2: str) -> int:
    """Compute hamming distance between two hex pHash strings."""
    i1 = int(h1, 16)
    i2 = int(h2, 16)
    xor = i1 ^ i2
    return bin(xor).count("1")


# ---------------------------------------------------------------------------
# Reason Rendering
# ---------------------------------------------------------------------------

_REASON_TEMPLATES: dict[ReasonCode, str] = {
    # L1
    ReasonCode.L1_HISTORY_VIOLATION_HIT: "历史指纹召回命中违规记录，历史ID: {history_id}，相似度: {ratio:.2f}",
    ReasonCode.L1_HISTORY_SAFE_HIT: "历史指纹召回命中安全记录，历史ID: {history_id}，相似度: {ratio:.2f}",
    ReasonCode.L1_MD5_VIOLATION_HIT: "文件 MD5 完全匹配历史违规记录，历史ID: {history_id}，MD5: {md5}",
    ReasonCode.L1_NO_MATCH: "历史指纹未命中任何记录",
    # L2 keywords
    ReasonCode.L2_HARD_BLOCK_HIT: "命中强违规关键词: {keyword}，来源: {source}",
    ReasonCode.L2_NORMALIZED_BLOCK_HIT: "归一化匹配命中违规词: {keyword}（原文: {raw_text}），来源: {source}",
    ReasonCode.L2_SUSPICIOUS_SLANG_HIT: "命中可疑黑话: {keyword}，来源: {source}，加中风险分",
    # L2 category
    ReasonCode.L2_MISSING_BRAND_AUTHORIZATION: "类目[{category}]缺失品牌授权资质",
    ReasonCode.L2_MISSING_FINANCIAL_LICENSE: "类目[{category}]缺失金融资质",
    ReasonCode.L2_MISSING_MEDICAL_LICENSE: "类目[{category}]缺失医疗资质",
    # L2 landing
    ReasonCode.L2_PRIVATE_DOMAIN_DRAINAGE: "检测到私域引流信号: {detail}",
    ReasonCode.L2_PRICE_INCONSISTENT: "广告宣称低价/免费，但落地页价格为 {price}，存在价格冲突",
    # L3
    ReasonCode.L3_OFFICIAL_NO_AUTHORIZATION: "素材宣称官方正品但缺失品牌授权资质",
    ReasonCode.L3_OFFICIAL_VS_CHANNEL: "素材宣称正品但落地页含渠道货/尾单/复刻等表述",
    ReasonCode.L3_PRICE_CONFLICT: "素材宣称低价/免费但落地页实际价格为 {price}",
    ReasonCode.L3_CATEGORY_MISMATCH: "类目为[{category}]但文本含跨类目内容: {detail}",
    ReasonCode.L3_PRIVATE_DOMAIN_CONFLICT: "素材宣称平台内购买但落地页含私域引流词: {detail}",
    ReasonCode.L3_LOW_SEMANTIC_SIMILARITY: "广告文案与落地页语义相似度偏低: {score:.2f}",
    ReasonCode.L3_RISK_SCORE_OVER_REJECT: "综合风险分 {risk_score} 超过拒绝阈值 {threshold}，判定拒绝",
    ReasonCode.L3_RISK_SCORE_UNDER_APPROVE: "综合风险分 {risk_score} 低于通过阈值 {threshold}，判定通过",
    ReasonCode.L3_AGENT_REVIEW: "综合风险分 {risk_score} 处于灰区，需 Agent 复核",
    # L4
    ReasonCode.L4_AGENT_DECISION: "Agent 复核决策: {decision}，置信度: {confidence:.2f}，理由: {reason}",
    ReasonCode.L4_AGENT_LOW_CONFIDENCE: "Agent 置信度 {confidence:.2f} 低于阈值 {threshold}，转人工复核",
    ReasonCode.L4_AGENT_OUTPUT_INVALID: "Agent 输出无法解析为合法 JSON，转人工复核",
    ReasonCode.L4_HIGH_SENSITIVE_CATEGORY: "高敏感类目[{category}]下 Agent 建议通过，强制转人工复核",
}


def render_reason(template_key: ReasonCode, ctx: dict[str, Any]) -> str:
    """Render a reason string from a ReasonCode template and context dict."""
    template = _REASON_TEMPLATES.get(template_key)
    if template is None:
        return f"{template_key.value}: {ctx}"
    try:
        return template.format(**ctx)
    except (KeyError, ValueError, IndexError):
        # Fallback: return template key + raw context if formatting fails
        return f"{template_key.value}: {ctx}"


# ---------------------------------------------------------------------------
# File / Directory Utilities
# ---------------------------------------------------------------------------


def ensure_dir(path: Path) -> Path:
    """Create directory (and parents) if it does not exist. Returns the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(s: str) -> str:
    """Sanitize a string for use as a directory/file name (cross-platform safe)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", s)


# ---------------------------------------------------------------------------
# Environment Detection
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available on the system PATH."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@lru_cache(maxsize=1)
def is_cuda_available() -> bool:
    """Check if CUDA is available (via torch or ctranslate2)."""
    # Prefer torch if installed
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        pass
    # Fallback to ctranslate2
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# YAML Loading
# ---------------------------------------------------------------------------


def load_yaml_with_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    """Load a YAML file, returning *default* on missing file or parse error."""
    if not path.exists():
        logger.error("YAML file %s not found, using default values", path)
        return default
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            # Empty YAML file
            return default
        if not isinstance(raw, dict):
            logger.error(
                "YAML file %s did not parse to a dict (got %s), using default values",
                path,
                type(raw).__name__,
            )
            return default
        return raw
    except (yaml.YAMLError, Exception) as e:  # noqa: BLE001
        logger.error("YAML file %s is invalid (%s), using default values", path, e)
        return default
