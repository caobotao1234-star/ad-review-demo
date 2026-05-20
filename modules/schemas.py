"""Pydantic models and enums for the ad-review-layered-decision system."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    NEXT = "NEXT"
    AGENT_REVIEW = "AGENT_REVIEW"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class ReasonCode(str, Enum):
    # L1
    L1_HISTORY_VIOLATION_HIT = "L1_HISTORY_VIOLATION_HIT"
    L1_HISTORY_SAFE_HIT = "L1_HISTORY_SAFE_HIT"
    L1_MD5_VIOLATION_HIT = "L1_MD5_VIOLATION_HIT"
    L1_NO_MATCH = "L1_NO_MATCH"
    # L2 keywords
    L2_HARD_BLOCK_HIT = "L2_HARD_BLOCK_HIT"
    L2_NORMALIZED_BLOCK_HIT = "L2_NORMALIZED_BLOCK_HIT"
    L2_SUSPICIOUS_SLANG_HIT = "L2_SUSPICIOUS_SLANG_HIT"
    # L2 category
    L2_MISSING_BRAND_AUTHORIZATION = "L2_MISSING_BRAND_AUTHORIZATION"
    L2_MISSING_FINANCIAL_LICENSE = "L2_MISSING_FINANCIAL_LICENSE"
    L2_MISSING_MEDICAL_LICENSE = "L2_MISSING_MEDICAL_LICENSE"
    # L2 landing
    L2_PRIVATE_DOMAIN_DRAINAGE = "L2_PRIVATE_DOMAIN_DRAINAGE"
    L2_PRICE_INCONSISTENT = "L2_PRICE_INCONSISTENT"
    # L3
    L3_OFFICIAL_NO_AUTHORIZATION = "L3_OFFICIAL_NO_AUTHORIZATION"
    L3_OFFICIAL_VS_CHANNEL = "L3_OFFICIAL_VS_CHANNEL"
    L3_PRICE_CONFLICT = "L3_PRICE_CONFLICT"
    L3_CATEGORY_MISMATCH = "L3_CATEGORY_MISMATCH"
    L3_PRIVATE_DOMAIN_CONFLICT = "L3_PRIVATE_DOMAIN_CONFLICT"
    L3_LOW_SEMANTIC_SIMILARITY = "L3_LOW_SEMANTIC_SIMILARITY"
    L3_RISK_SCORE_OVER_REJECT = "L3_RISK_SCORE_OVER_REJECT"
    L3_RISK_SCORE_UNDER_APPROVE = "L3_RISK_SCORE_UNDER_APPROVE"
    L3_AGENT_REVIEW = "L3_AGENT_REVIEW"
    # L4
    L4_AGENT_DECISION = "L4_AGENT_DECISION"
    L4_AGENT_LOW_CONFIDENCE = "L4_AGENT_LOW_CONFIDENCE"
    L4_AGENT_OUTPUT_INVALID = "L4_AGENT_OUTPUT_INVALID"
    L4_HIGH_SENSITIVE_CATEGORY = "L4_HIGH_SENSITIVE_CATEGORY"


class SignalSource(str, Enum):
    OCR = "ocr"
    ASR = "asr"
    QR = "qr"
    KEYWORD = "keyword"
    CATEGORY = "category"
    LANDING_PAGE = "landing_page"
    HISTORY = "history"
    EMBEDDING = "embedding"
    CONSISTENCY = "consistency"


# ---------------------------------------------------------------------------
# Input Models
# ---------------------------------------------------------------------------


class Qualification(BaseModel):
    business_license: str | None = None
    brand_authorization: str | None = None
    financial_license: str | None = None
    medical_license: str | None = None


class Merchant(BaseModel):
    merchant_id: str
    qualification: Qualification = Field(default_factory=Qualification)
    history_violation_count: int = 0


class LandingPage(BaseModel):
    url: str = ""
    text: str = ""
    price: float | None = None


class AdMeta(BaseModel):
    ad_id: str
    media_type: str = "video"
    media_path: str = ""
    title: str = ""
    description: str = ""
    category: str = "其他"
    brand: str = ""
    mock_asr_text: str = ""
    mock_ocr_texts: list[str] = Field(default_factory=list)
    landing_page: LandingPage = Field(default_factory=LandingPage)
    merchant: Merchant

    @field_validator("ad_id")
    @classmethod
    def _ad_id_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("ad_id must not be empty")
        return v


# ---------------------------------------------------------------------------
# Media Preprocessing Models
# ---------------------------------------------------------------------------


class FrameRef(BaseModel):
    frame_id: str
    frame_path: str
    timestamp_sec: float


class VideoFingerprint(BaseModel):
    phash_list: list[str] = Field(default_factory=list)
    frame_count: int = 0


class MediaResult(BaseModel):
    ad_id: str
    mock: bool = False
    fallback_reason: str | None = None
    file_md5: str | None = None  # 视频文件 MD5
    duration_sec: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    sampled_frames: list[FrameRef] = Field(default_factory=list)
    fingerprint: VideoFingerprint = Field(default_factory=VideoFingerprint)
    audio_path: str | None = None


# ---------------------------------------------------------------------------
# Layer Output Models
# ---------------------------------------------------------------------------


class Signal(BaseModel):
    source: SignalSource
    code: ReasonCode
    detail: str = ""
    score_delta: int = 0


class Evidence(BaseModel):
    source: SignalSource
    raw: str = ""
    normalized: str = ""
    location: str = ""


class LayerResult(BaseModel):
    layer: str
    decision: Decision
    risk_score: int = 0
    reason_code: ReasonCode | None = None
    reason: str = ""
    signals: list[Signal] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent Models
# ---------------------------------------------------------------------------


class AgentResponse(BaseModel):
    parsed: dict[str, Any]
    raw: str
    repair_applied: bool = False
    error: bool = False
    error_reason: str | None = None


class L4AgentJSON(BaseModel):
    decision: str
    confidence: float
    risk_types: list[str] = Field(default_factory=list)
    evidence_chain: list[str] = Field(default_factory=list)
    policy_refs: list[str] = Field(default_factory=list)
    reason: str = ""
    next_action: str = ""


class AppealResult(BaseModel):
    appeal_id: str
    appeal_suggestion: str
    confidence: float
    reason: str
    required_extra_materials: list[str] = Field(default_factory=list)
    policy_refs: list[str] = Field(default_factory=list)


class Suggestion(BaseModel):
    type: str
    words: list[str] = Field(default_factory=list)
    action: str
    route: str


class StrategyResult(BaseModel):
    optimization_target: str
    problem: str
    suggestions: list[Suggestion]
    validation_plan: str
    risk: str
    requires_human_approval: bool = True


# ---------------------------------------------------------------------------
# Configuration Models
# ---------------------------------------------------------------------------


class RuntimeConfig(BaseModel):
    max_sampled_frames: int = 12
    sample_interval_sec: float = 1.0
    phash_resize: int = 64
    enable_ocr: bool = True
    enable_asr: bool = True
    enable_qr: bool = True
    enable_text_embedding: bool = True
    llm_enabled: str = "auto"
    # ASR
    asr_model_size: str = "small"
    asr_model_path: str = "models/faster-whisper-small"  # 本地模型路径（优先）
    asr_device: str = "auto"
    asr_compute_type: str = "float16"
    # OCR
    ocr_model_dir: str = "models/paddleocr"  # PaddleOCR 本地模型目录
    # Text Embedding
    embedding_model_path: str = "models/paraphrase-multilingual-MiniLM-L12-v2"


class Thresholds(BaseModel):
    l1_history_match_threshold: float = 0.85
    l1_hamming_threshold: int = 8
    l2_reject_score: int = 60
    l3_reject_score: int = 85
    l3_approve_score: int = 20
    agent_confidence_auto_threshold: float = 0.7


class KeywordEntry(BaseModel):
    word: str
    category: str = "all"


class KeywordsConfig(BaseModel):
    hard_block: list[KeywordEntry] = Field(default_factory=list)
    normalized_block: list[KeywordEntry] = Field(default_factory=list)
    suspicious_slang: list[KeywordEntry] = Field(default_factory=list)


class CategoryRule(BaseModel):
    category: str
    required_qualifications: list[str] = Field(default_factory=list)
    sensitive_claims: list[str] = Field(default_factory=list)


class CategoryRulesConfig(BaseModel):
    rules: list[CategoryRule] = Field(default_factory=list)
