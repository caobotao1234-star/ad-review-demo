"""L5 Appeal Agent: structured appeal review suggestions."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from modules.agent_client import AgentClient
from modules.schemas import AppealResult

logger = logging.getLogger(__name__)


class L5AppealAgent:
    def __init__(self, agent: AgentClient, policy_docs_path: Path) -> None:
        self.agent = agent
        self.policy_docs: list[dict] = []
        if policy_docs_path.exists():
            self.policy_docs = json.loads(policy_docs_path.read_text(encoding="utf-8"))

    def review_appeal(self, appeal: dict, original: dict | None) -> AppealResult:
        """Generate appeal review suggestion."""
        system = (
            "你是广告申诉复核 Agent。你必须严格输出 JSON，包含以下字段：\n"
            "appeal_id, appeal_suggestion (KEEP_REJECT|SUGGEST_APPROVE_AFTER_HUMAN_REVIEW|NEED_MORE_MATERIALS|HUMAN_REVIEW), "
            "confidence (0-1), reason, required_extra_materials (list), policy_refs (list)\n"
            "你不能直接改判，只能输出建议。"
        )
        user = json.dumps({
            "appeal": appeal,
            "original_review": original,
            "policy_docs_summary": [d.get("text", "")[:200] for d in self.policy_docs[:5]],
        }, ensure_ascii=False)

        response = self.agent.call(system, user, {"scenario": "l5_appeal"})

        if response.error:
            # Fallback
            return self._mock_appeal(appeal, original)

        try:
            return AppealResult(**response.parsed)
        except Exception:
            return self._mock_appeal(appeal, original)

    def _mock_appeal(self, appeal: dict, original: dict | None) -> AppealResult:
        """Deterministic mock logic for appeal review."""
        appeal_id = appeal.get("appeal_id", "unknown")
        extra_materials = appeal.get("extra_materials", [])

        if original is None:
            return AppealResult(
                appeal_id=appeal_id,
                appeal_suggestion="HUMAN_REVIEW",
                confidence=0.5,
                reason="原始审核结论不可用，建议人工复核",
                required_extra_materials=[],
                policy_refs=[],
            )

        # Check if original had qualification issues
        missing_quals = []
        layers = original.get("layers", [])
        for layer in layers:
            for sig in layer.get("signals", []):
                code = sig.get("code", "")
                if "MISSING_BRAND" in code:
                    missing_quals.append("品牌授权书")
                elif "MISSING_FINANCIAL" in code:
                    missing_quals.append("金融业务许可证")
                elif "MISSING_MEDICAL" in code:
                    missing_quals.append("医疗广告审查证明")

        missing_quals = list(set(missing_quals))

        if missing_quals and not extra_materials:
            return AppealResult(
                appeal_id=appeal_id,
                appeal_suggestion="NEED_MORE_MATERIALS",
                confidence=0.8,
                reason="原审核因资质缺失拒绝，申诉未提供补充材料",
                required_extra_materials=missing_quals,
                policy_refs=["policy_brand_001"],
            )

        if missing_quals and extra_materials:
            return AppealResult(
                appeal_id=appeal_id,
                appeal_suggestion="SUGGEST_APPROVE_AFTER_HUMAN_REVIEW",
                confidence=0.7,
                reason="商家已补充材料，建议人工核验后考虑改判",
                required_extra_materials=[],
                policy_refs=["policy_brand_001"],
            )

        return AppealResult(
            appeal_id=appeal_id,
            appeal_suggestion="KEEP_REJECT",
            confidence=0.75,
            reason="申诉缺乏有效反驳依据，建议维持原判",
            required_extra_materials=missing_quals,
            policy_refs=[],
        )
