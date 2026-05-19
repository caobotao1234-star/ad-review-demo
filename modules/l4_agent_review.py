"""L4 Agent Review: LLM-based complex ad review with multimodal vision, tool calling, and cross-verification."""

from __future__ import annotations

import base64
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

# ---------------------------------------------------------------------------
# System Prompt: multimodal + cross-verification + tool calling
# ---------------------------------------------------------------------------

_L4_SYSTEM_PROMPT = """你是广告合规复核 Agent，具备多模态审核能力。

你的任务：
1. 分析广告文案、落地页文本、商家资质信息
2. 观察广告画面截图，判断画面内容是否与文案一致
3. 使用工具检索相关政策和历史案例
4. 进行交叉验证：对比"文案宣称" vs "画面实际内容" vs "落地页描述"
5. 综合所有证据给出最终判定

你可以使用以下工具：
- search_policy: 检索相关审核政策条文
- search_cases: 检索相似的历史审核案例
- cross_verify: 交叉验证文案宣称与实际证据是否一致

交叉验证重点关注：
- 文案说"官方正品"，画面中是否有品牌标识/授权标志？
- 文案说"专柜品质"，画面中商品做工是否精细？
- 落地页说"渠道货/尾单"，是否与文案"正品"矛盾？
- 画面中是否有二维码/微信号等私域引流元素？
- 画面中是否有夸大宣传的文字（如收益截图）？

最终必须严格输出 JSON：
{
  "decision": "REJECT | APPROVE | HUMAN_REVIEW",
  "confidence": 0.0-1.0,
  "risk_types": ["..."],
  "evidence_chain": ["..."],
  "policy_refs": ["..."],
  "reason": "...",
  "next_action": "...",
  "visual_analysis": "对画面内容的分析描述",
  "cross_verification": {
    "claim_vs_visual": "文案与画面是否一致的判断",
    "claim_vs_landing": "文案与落地页是否一致的判断",
    "visual_vs_landing": "画面与落地页是否一致的判断"
  }
}"""

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function calling format)
# ---------------------------------------------------------------------------

_L4_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": "检索与查询相关的广告审核政策条文",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词，如'品牌授权'、'金融资质'"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_cases",
            "description": "检索相似的历史广告审核案例",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "案例检索关键词"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cross_verify",
            "description": "交叉验证：对比广告文案宣称与实际证据（落地页/OCR/ASR）是否一致",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "广告文案中的宣称内容"},
                    "evidence": {"type": "string", "description": "实际证据（落地页文本/OCR识别/ASR转写）"},
                    "aspect": {"type": "string", "description": "验证维度：brand/price/category/drainage"},
                },
                "required": ["claim", "evidence", "aspect"],
            },
        },
    },
]


class L4AgentReview:
    """L4 layer: Agent-based complex review with multimodal vision, tool calling, and cross-verification."""

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

        # Register tool implementations for function calling
        self.agent.register_tools({
            "search_policy": self._tool_search_policy,
            "search_cases": self._tool_search_cases,
            "cross_verify": self._cross_verify_impl,
        })

    # ------------------------------------------------------------------
    # JSON loading
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # RAG retrieval methods (used by tools)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Tool implementations for function calling
    # ------------------------------------------------------------------

    def _tool_search_policy(self, args: dict) -> dict:
        """Tool: search_policy(query) → 检索政策文档."""
        query = args.get("query", "")
        results = self.policy_rag(query, top_k=3)
        return {"query": query, "results": results, "count": len(results)}

    def _tool_search_cases(self, args: dict) -> dict:
        """Tool: search_cases(query) → 检索历史案例."""
        query = args.get("query", "")
        results = self.history_case_rag(query, top_k=3)
        return {"query": query, "results": results, "count": len(results)}

    def _cross_verify_impl(self, args: dict) -> dict:
        """Tool: cross_verify(claim, evidence, aspect) → 交叉验证文案与证据是否一致."""
        claim = args.get("claim", "")
        evidence = args.get("evidence", "")
        aspect = args.get("aspect", "general")

        claim_norm = normalize_text(claim)
        evidence_norm = normalize_text(evidence)

        # Simple consistency check based on aspect
        contradictions = []

        if aspect == "brand":
            if "正品" in claim_norm and any(
                w in evidence_norm for w in ["渠道货", "尾单", "复刻", "高仿"]
            ):
                contradictions.append("文案宣称正品，但证据含渠道/仿冒表述")
            if "官方" in claim_norm and "授权" not in evidence_norm and "官方" not in evidence_norm:
                contradictions.append("文案宣称官方，但证据中无官方授权信息")
        elif aspect == "price":
            if any(w in claim_norm for w in ["免费", "低价"]) and any(
                w in evidence_norm for w in ["高价", "原价"]
            ):
                contradictions.append("文案宣称低价/免费，但证据显示高价")
        elif aspect == "category":
            if "日用品" in claim_norm and any(
                w in evidence_norm for w in ["减肥", "治疗", "理财"]
            ):
                contradictions.append("宣称日用品类目，但证据含医疗/金融内容")
        elif aspect == "drainage":
            if any(w in evidence_norm for w in ["微信", "私聊", "加好友"]):
                contradictions.append("证据含私域引流内容")

        return {
            "consistent": len(contradictions) == 0,
            "contradictions": contradictions,
            "claim_summary": claim[:100],
            "evidence_summary": evidence[:100],
        }

    # ------------------------------------------------------------------
    # Multimodal: select representative frames → base64
    # ------------------------------------------------------------------

    def _select_representative_frames(self, media: MediaResult, max_frames: int = 3) -> list[str]:
        """Select representative frames and encode as base64 JPEG strings.

        Strategy: pick first frame + middle frame + last frame (up to max_frames).
        """
        if media.mock or not media.sampled_frames:
            return []

        frames = media.sampled_frames
        # Select first, middle, last
        indices = [0]
        if len(frames) > 2:
            indices.append(len(frames) // 2)
        if len(frames) > 1:
            indices.append(len(frames) - 1)

        images_b64: list[str] = []
        for idx in indices[:max_frames]:
            frame_path = Path(frames[idx].frame_path)
            if frame_path.exists():
                try:
                    img_bytes = frame_path.read_bytes()
                    images_b64.append(base64.b64encode(img_bytes).decode("utf-8"))
                except OSError as e:
                    logger.warning("Failed to read frame %s: %s", frame_path, e)

        return images_b64

    # ------------------------------------------------------------------
    # Main review method
    # ------------------------------------------------------------------

    def review(
        self,
        ad: AdMeta,
        l1: LayerResult,
        l2: LayerResult,
        l3: LayerResult,
        media: MediaResult,
    ) -> LayerResult:
        """Perform L4 agent review with multimodal vision and cross-verification."""
        logger.debug("L4AgentReview.review: ad_id=%s, l3_score=%d, frames_available=%d", ad.ad_id, l3.risk_score, len(media.sampled_frames))

        # Build query for RAG pre-fetch (context for user prompt)
        query = f"{ad.title} {ad.description} {ad.category} {ad.brand}"
        policy_excerpts = self.policy_rag(query)
        history_cases = self.history_case_rag(query)
        logger.debug("L4 policy_rag: query_len=%d, results=%d", len(query), len(policy_excerpts))

        # Build user prompt
        user_prompt = self._build_user_prompt(ad, l1, l2, l3, media, policy_excerpts, history_cases)

        # Select representative frames for multimodal analysis
        images = self._select_representative_frames(media)
        logger.debug("L4 frame encoding: %d frames selected, total_b64_size=%d bytes", len(images), sum(len(i) for i in images))

        # Call agent: use vision if we have real frames, otherwise fallback to text-only
        if images:
            logger.info("L4 calling agent: mode=%s, vision=%s, tools=%s, prompt_len=%d", "vision", True, True, len(user_prompt))
            response = self.agent.call_with_vision(
                _L4_SYSTEM_PROMPT,
                user_prompt,
                images,
                tools=_L4_TOOLS,
                schema_hint={"scenario": "l4_review"},
            )
        else:
            logger.info("L4 calling agent: mode=%s, vision=%s, tools=%s, prompt_len=%d", "text", False, False, len(user_prompt))
            response = self.agent.call(
                _L4_SYSTEM_PROMPT, user_prompt, {"scenario": "l4_review"}
            )

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

        logger.info("L4 agent response: error=%s, repair=%s, decision=%s, confidence=%.2f", response.error, response.repair_applied, decision_str, confidence)

        # High-sensitive category override: 金融/医疗
        if ad.category in {"金融", "医疗"}:
            if decision_str == "APPROVE":
                logger.info("L4 sensitive category override: %s → HUMAN_REVIEW", ad.category)
                decision_str = "HUMAN_REVIEW"
                reason_code = ReasonCode.L4_HIGH_SENSITIVE_CATEGORY

        # Low confidence override
        if confidence < self.thresholds.agent_confidence_auto_threshold:
            if decision_str != "HUMAN_REVIEW":
                logger.info("L4 low confidence override: %.2f < %.2f → HUMAN_REVIEW", confidence, self.thresholds.agent_confidence_auto_threshold)
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

        # Extract cross-verification and visual analysis from response
        visual_analysis = response.parsed.get("visual_analysis", "")
        cross_verification = response.parsed.get("cross_verification", {})

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
                "visual_analysis": visual_analysis,
                "cross_verification": cross_verification,
                "multimodal_used": len(images) > 0,
                "frames_sent": len(images),
            },
        )

    # ------------------------------------------------------------------
    # User prompt builder
    # ------------------------------------------------------------------

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
        """Build the user prompt for L4 agent with cross-verification context."""
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
            "=== 交叉验证要求 ===",
            "请执行以下三维交叉验证：",
            f"1. 文案宣称 vs 画面内容：广告文案「{ad.title}」是否与画面实际展示一致？",
            f"2. 文案宣称 vs 落地页：广告文案是否与落地页内容「{ad.landing_page.text[:100]}」一致？",
            f"3. 画面内容 vs 落地页：画面展示是否与落地页描述一致？",
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
