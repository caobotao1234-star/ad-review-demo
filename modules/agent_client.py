"""AgentClient: LLM call wrapper with MockAgent fallback and JSON repair."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from modules.schemas import AgentResponse, RuntimeConfig

logger = logging.getLogger(__name__)


class MockAgent:
    """Deterministic mock agent for testing without LLM API key."""

    def call(self, system: str, user: str, schema_hint: dict) -> AgentResponse:
        """Return structured JSON based on schema_hint scenario."""
        scenario = schema_hint.get("scenario", "")

        if scenario == "l4_review":
            payload = self._mock_l4_review(user)
        elif scenario == "l5_appeal":
            payload = self._mock_l5_appeal(user)
        elif scenario == "l5_strategy":
            payload = self._mock_l5_strategy(user)
        else:
            payload = {
                "decision": "HUMAN_REVIEW",
                "confidence": 0.5,
                "reason": "Unknown scenario, defaulting to HUMAN_REVIEW",
            }

        return AgentResponse(
            parsed=payload,
            raw=json.dumps(payload, ensure_ascii=False),
            repair_applied=False,
            error=False,
        )

    def _mock_l4_review(self, user: str) -> dict[str, Any]:
        """Mock L4 review: decide based on risk_score in user prompt."""
        # Try to extract risk_score from user prompt
        risk_score = 0
        m = re.search(r"risk_score[\"']?\s*[:=]\s*(\d+)", user)
        if m:
            risk_score = int(m.group(1))

        if risk_score >= 70:
            return {
                "decision": "REJECT",
                "confidence": 0.85,
                "risk_types": ["high_risk_score"],
                "evidence_chain": ["risk_score exceeds threshold"],
                "policy_refs": [],
                "reason": f"Mock Agent: risk_score={risk_score} is high, rejecting",
                "next_action": "block",
            }
        elif risk_score <= 30:
            return {
                "decision": "APPROVE",
                "confidence": 0.80,
                "risk_types": [],
                "evidence_chain": ["risk_score is low"],
                "policy_refs": [],
                "reason": f"Mock Agent: risk_score={risk_score} is low, approving",
                "next_action": "none",
            }
        else:
            return {
                "decision": "HUMAN_REVIEW",
                "confidence": 0.55,
                "risk_types": ["gray_zone"],
                "evidence_chain": ["risk_score in gray zone"],
                "policy_refs": [],
                "reason": f"Mock Agent: risk_score={risk_score} in gray zone, needs human review",
                "next_action": "human_review",
            }

    def _mock_l5_appeal(self, user: str) -> dict[str, Any]:
        """Mock L5 appeal: decide based on extra_materials presence."""
        has_extra = "extra_materials" in user and '"extra_materials": [' not in user
        # Check if extra_materials list is non-empty
        m = re.search(r'"extra_materials"\s*:\s*\[([^\]]*)\]', user)
        has_materials = bool(m and m.group(1).strip())

        if has_materials:
            return {
                "appeal_suggestion": "SUGGEST_APPROVE_AFTER_HUMAN_REVIEW",
                "confidence": 0.70,
                "reason": "Mock: 申诉方提供了补充材料，建议人工复核后通过",
                "required_extra_materials": [],
                "policy_refs": ["policy_brand_001"],
            }
        else:
            return {
                "appeal_suggestion": "NEED_MORE_MATERIALS",
                "confidence": 0.65,
                "reason": "Mock: 缺少关键资质材料，需补充后重新审核",
                "required_extra_materials": ["品牌授权书"],
                "policy_refs": ["policy_brand_001"],
            }

    def _mock_l5_strategy(self, user: str) -> dict[str, Any]:
        """Mock L5 strategy: return fixed strategy suggestion structure."""
        return {
            "optimization_target": "减少箱包类目误放行",
            "problem": "黑话词汇未被现有规则覆盖，导致疑似仿冒广告通过审核",
            "suggestions": [
                {
                    "type": "keyword",
                    "words": ["柜姐渠道", "原厂尾单", "懂的来", "渠道价", "内部福利"],
                    "action": "add_to_suspicious_slang",
                    "route": "L3",
                }
            ],
            "validation_plan": "在测试集上验证新增词库的召回率和误伤率",
            "risk": "可能误伤正规代购商家",
            "requires_human_approval": True,
        }


class AgentClient:
    """OpenAI-compatible API client with MockAgent fallback."""

    def __init__(self, runtime: RuntimeConfig) -> None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            logger.warning("python-dotenv not installed, skipping .env loading")

        self._mode = self._resolve_mode(runtime.llm_enabled)
        self._base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self._api_key = os.getenv("LLM_API_KEY", "")
        self._model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self._mock_agent = MockAgent()

        logger.info("AgentClient initialized in mode=%s", self._mode)

    def _resolve_mode(self, llm_enabled: str) -> str:
        """Resolve agent mode: 'real' or 'mock'."""
        if llm_enabled == "false":
            return "mock"
        api_key = os.getenv("LLM_API_KEY", "")
        if llm_enabled in ("auto", "true"):
            return "real" if api_key else "mock"
        return "mock"

    def is_mock(self) -> bool:
        """Return True if running in mock mode."""
        return self._mode == "mock"

    def call(self, system: str, user: str, schema_hint: dict) -> AgentResponse:
        """Call LLM or MockAgent depending on mode."""
        if self._mode == "mock":
            return self._mock_agent.call(system, user, schema_hint)

        try:
            raw = self._call_openai_compat(system, user)
        except Exception as e:
            logger.warning("LLM call failed (%s), falling back to MockAgent", e)
            return self._mock_agent.call(system, user, schema_hint)

        return self._parse_with_repair(raw)

    def _call_openai_compat(self, system: str, user: str) -> str:
        """Call OpenAI-compatible chat completions API."""
        import requests

        url = self._base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _parse_with_repair(self, raw: str) -> AgentResponse:
        """Parse LLM output as JSON, attempting repair if needed."""
        # Try direct parse
        try:
            parsed = json.loads(raw)
            return AgentResponse(parsed=parsed, raw=raw, repair_applied=False)
        except json.JSONDecodeError:
            pass

        # Attempt repair
        repaired = self._repair_json(raw)
        if repaired is not None:
            try:
                parsed = json.loads(repaired)
                return AgentResponse(parsed=parsed, raw=raw, repair_applied=True)
            except json.JSONDecodeError:
                pass

        # Unrecoverable
        return AgentResponse(
            parsed=self._fallback_payload(),
            raw=raw,
            repair_applied=False,
            error=True,
            error_reason="json_unrecoverable",
        )

    def _repair_json(self, raw: str) -> str | None:
        """Attempt to extract valid JSON from raw text."""
        # Strip ```json ... ``` wrapper
        stripped = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        stripped = re.sub(r"\s*```$", "", stripped)
        if stripped != raw.strip():
            try:
                json.loads(stripped)
                return stripped
            except json.JSONDecodeError:
                pass

        # Find first { ... last }
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return m.group(0)

        return None

    def _fallback_payload(self) -> dict[str, Any]:
        """Return a safe fallback payload when JSON is unrecoverable."""
        return {
            "decision": "HUMAN_REVIEW",
            "confidence": 0.0,
            "risk_types": ["json_invalid"],
            "evidence_chain": [],
            "policy_refs": [],
            "reason": "Agent returned invalid JSON, fallback to HUMAN_REVIEW",
            "next_action": "human_review",
        }
