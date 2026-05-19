"""L4 Agent Review: LLM-based complex ad review with policy RAG and history case RAG."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from modules.agent_client import AgentClient
from modules.schemas import (
    AdMeta,
    Decision,
    L4AgentJSON,
    LayerResult,
    MediaResult,
    ReasonCode,
    Signal,
    SignalSource,
    Thresholds,
)
from modules.utils import normalize_text, render_reason

logger = logging.getLogger(__name__)

# System prompt for L4 Agent
_L4_SYSTEM_PROMPT = """你是广告合规复核 Agent。你必须严格输出 JSON, 不允许包含任何解释性文字。
你不能调用任何修改文件、修改配置、访问网络、加载图像 embedding 的工具。
你只能引用我提供的政策文档摘录和历史案例文本作为依据。

输出格式:
{
  "decision": "REJECT | APPROVE | HUMAN_REVIEW",
  "confidence": 0.0-1.0,
  "risk_types": ["..."],
  "evidence_chain": ["..."],
  "policy_refs": ["..."],
  "reason": "...",
  "next_action": "..."
}"""


class L4AgentReview:
    """L4 layer: Agent-based complex review for gray-zone ads."""

    def __init__(
        self,
        agent: AgentClient,
        thresholds: Thresholds,
        policy_docs_path: Path,
        history_cases_path: Path,
    ) -> None:
        self.agent = agent
        self.thresholds = thresholds
        self._policy_docs = self._load_json(policy_docs_path)
        self._history_cases = self._load_json(history_cases_path)

    def _load_json(self, path: Path) -> list[dict[str, Any]]:
        """Load a JSON file, returning empty list on failure."""
        if not path.exists():
            logger.warning("File %s not found, using empty list", path)
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            return []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s", path, e)
            return []

    def policy_rag(self, query: str, top_k: int = 5) -> list[str]:
        """Simple Jaccard text retrieval from policy docs."""
        qn = normalize_text(query)
        scored = []
        for doc in self._policy_docs:
            text = doc.get("text", "")
            dn = normalize_text(text)
            score = self._jaccard(qn, dn)
            scored.append((score, text))
        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored[:top_k]]

    def history_case_rag(self, query: str, top_k: int = 5) -> list[str]:
        """Simple Jaccard text retrieval from history cases."""
        qn = normalize_text(query)
        scored = []
        for case in self._history_cases:
            text = case.get("text", "")
            cn = normalize_text(text)
            score = self._jaccard(qn, cn)
            scored.append((score, text))
        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored[:top_k]]

    def _jaccard(self, a: str, b: str) -> float:
        """Character-level Jaccard similarity."""
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def review(
        self,
        ad: AdMeta,
        l1: LayerResult,
        l2: LayerResult,
        l3: LayerResult,
        media: MediaResult,
    ) -> LayerResult:
        """Perform L4 agent review."""
        # Build query for RAG
        query = f"{ad.title} {ad.description} {ad.category} {ad.brand}"
        policy_excerpts = self.policy_rag(query)
        history_cases = self.history_case_rag(query)

        # Build user prompt
        user_prompt = self._build_user_prompt(ad, l1, l2, l3, media, policy_excerpts, history_cases)

        # Call agent
        response = self.agent.call(_L4_SYSTEM_PROMPT, user_prompt, {"scenario": "l4_review"})

        # Handle agent error
        if response.error:
            reason = render_reason(ReasonCode.L4_AGENT_OUTPUT_INVALID, {})
            return LayerResult(
                layer="L4",
                decision=Decision.HUMAN_REVIEW,
                risk_score=l3.risk_score,
                reason_code=ReasonCode.L4_AGENT_OUTPUT_INVALID,
                reason=reason,
                signals=[Signal(
                    source=SignalSource.CONSISTENCY,
                    code=ReasonCode.L4_AGENT_OUTPUT_INVALID,
                    detail="Agent JSON unrecoverable",
                    score_delta=0,
                )],
                extra={"agent_error": response.error_reason},
            )

        # Parse agent response
        try:
            payload = L4AgentJSON(**response.parsed)
        except Exception:
            reason = render_reason(ReasonCode.L4_AGENT_OUTPUT_INVALID, {})
            return LayerResult(
                layer="L4",
                decision=Decision.HUMAN_REVIEW,
                risk_score=l3.risk_score,
                reason_code=ReasonCode.L4_AGENT_OUTPUT_INVALID,
                reason=reason,
                signals=[],
                extra={"agent_raw": response.raw},
            )

        decision_str = payload.decision.upper()
        confidence = payload.confidence
        reason_code = ReasonCode.L4_AGENT_DECISION

        # High-sensitive category override: 金融/医疗
        if ad.category in {"金融", "医疗"}:
            if decision_str == "APPROVE":
                decision_str = "HUMAN_REVIEW"
                reason_code = ReasonCode.L4_HIGH_SENSITIVE_CATEGORY

        # Low confidence override
        if confidence < self.thresholds.agent_confidence_auto_threshold:
            if decision_str != "HUMAN_REVIEW":
                decision_str = "HUMAN_REVIEW"
                reason_code = ReasonCode.L4_AGENT_LOW_CONFIDENCE

        # Map to Decision enum
        decision_map = {
            "REJECT": Decision.REJECT,
            "APPROVE": Decision.APPROVE,
            "HUMAN_REVIEW": Decision.HUMAN_REVIEW,
        }
        decision = decision_map.get(decision_str, Decision.HUMAN_REVIEW)

        # Render reason
        if reason_code == ReasonCode.L4_AGENT_LOW_CONFIDENCE:
            reason = render_reason(reason_code, {
                "confidence": confidence,
                "threshold": self.thresholds.agent_confidence_auto_threshold,
            })
        elif reason_code == ReasonCode.L4_HIGH_SENSITIVE_CATEGORY:
            reason = render_reason(reason_code, {"category": ad.category})
        else:
            reason = render_reason(reason_code, {
                "decision": decision_str,
                "confidence": confidence,
                "reason": payload.reason,
            })

        return LayerResult(
            layer="L4",
            decision=decision,
            risk_score=l3.risk_score,
            reason_code=reason_code,
            reason=reason,
            signals=[],
            extra={
                "confidence": confidence,
                "risk_types": payload.risk_types,
                "evidence_chain": payload.evidence_chain,
                "policy_refs": payload.policy_refs,
                "agent_reason": payload.reason,
                "repair_applied": response.repair_applied,
            },
        )

    def _build_user_prompt(
        self,
        ad: AdMeta,
        l1: LayerResult,
        l2: LayerResult,
        l3: LayerResult,
        media: MediaResult,
        policy_excerpts: list[str],
        history_cases: list[str],
    ) -> str:
        """Build the user prompt for L4 agent."""
        parts = [
            "=== 广告审核复核请求 ===",
            f"ad_id: {ad.ad_id}",
            f"category: {ad.category}",
            f"brand: {ad.brand}",
            f"title: {ad.title}",
            f"description: {ad.description}",
            f"merchant_id: {ad.merchant.merchant_id}",
            f"history_violation_count: {ad.merchant.history_violation_count}",
            f"qualification: business_license={ad.merchant.qualification.business_license}, "
            f"brand_authorization={ad.merchant.qualification.brand_authorization}, "
            f"financial_license={ad.merchant.qualification.financial_license}, "
            f"medical_license={ad.merchant.qualification.medical_license}",
            "",
            f"landing_page_text: {ad.landing_page.text}",
            f"landing_page_price: {ad.landing_page.price}",
            "",
            f"media_mock: {media.mock}",
            f"media_duration: {media.duration_sec}s",
            f"sampled_frames: {len(media.sampled_frames)}",
            "",
            f"l1_decision: {l1.decision.value}",
            f"l1_reason: {l1.reason}",
            f"l2_decision: {l2.decision.value}",
            f"l2_risk_score: {l2.risk_score}",
            f"l2_reason: {l2.reason}",
            f"l3_decision: {l3.decision.value}",
            f"l3_risk_score: {l3.risk_score}",
            f"l3_reason: {l3.reason}",
            f"risk_score: {l3.risk_score}",
            "",
            "=== 相关政策文档 ===",
        ]
        for i, excerpt in enumerate(policy_excerpts, 1):
            parts.append(f"{i}. {excerpt}")

        parts.append("")
        parts.append("=== 相关历史案例 ===")
        for i, case in enumerate(history_cases, 1):
            parts.append(f"{i}. {case}")

        return "\n".join(parts)
