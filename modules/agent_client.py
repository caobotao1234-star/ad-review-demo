"""AgentClient: LLM call wrapper with MockAgent fallback, JSON repair, vision, and tool calling."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from modules.schemas import AgentResponse, RuntimeConfig

logger = logging.getLogger(__name__)


class MockAgent:
    """Deterministic mock agent for testing without LLM API key."""

    def call(self, system: str, user: str, schema_hint: dict) -> AgentResponse:
        """Return structured JSON based on schema_hint scenario."""
        scenario = schema_hint.get("scenario", "")
        logger.debug("MockAgent.call: scenario=%s", scenario)

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
                "visual_analysis": "Mock模式：未分析实际画面",
                "cross_verification": {
                    "claim_vs_visual": "Mock模式：未执行图文交叉验证",
                    "claim_vs_landing": "Mock模式：未执行文案与落地页交叉验证",
                    "visual_vs_landing": "Mock模式：未执行画面与落地页交叉验证",
                },
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
                "visual_analysis": "Mock模式：未分析实际画面",
                "cross_verification": {
                    "claim_vs_visual": "Mock模式：未执行图文交叉验证",
                    "claim_vs_landing": "Mock模式：未执行文案与落地页交叉验证",
                    "visual_vs_landing": "Mock模式：未执行画面与落地页交叉验证",
                },
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
                "visual_analysis": "Mock模式：未分析实际画面",
                "cross_verification": {
                    "claim_vs_visual": "Mock模式：未执行图文交叉验证",
                    "claim_vs_landing": "Mock模式：未执行文案与落地页交叉验证",
                    "visual_vs_landing": "Mock模式：未执行画面与落地页交叉验证",
                },
            }

    def _mock_l5_appeal(self, user: str) -> dict[str, Any]:
        """Mock L5 appeal: decide based on extra_materials presence."""
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
    """OpenAI-compatible API client with MockAgent fallback, vision, and tool calling."""

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
        self._registered_tools: dict[str, Any] = {}

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

    def register_tools(self, tools: dict[str, Any]) -> None:
        """Register tool implementations for function calling.

        Args:
            tools: Dict mapping tool name to callable(args: dict) -> dict
        """
        self._registered_tools.update(tools)

    # ------------------------------------------------------------------
    # Public API: text-only call (backward compatible)
    # ------------------------------------------------------------------

    def call(self, system: str, user: str, schema_hint: dict) -> AgentResponse:
        """Call LLM or MockAgent depending on mode."""
        logger.debug("AgentClient.call: mode=%s, system_len=%d, user_len=%d", self._mode, len(system), len(user))

        if self._mode == "mock":
            return self._mock_agent.call(system, user, schema_hint)

        try:
            raw = self._call_openai_compat(system, user)
        except Exception as e:
            logger.warning("LLM call failed (%s), falling back to MockAgent", e)
            return self._mock_agent.call(system, user, schema_hint)

        return self._parse_with_repair(raw)

    # ------------------------------------------------------------------
    # Public API: vision + tool calling
    # ------------------------------------------------------------------

    def call_with_vision(
        self,
        system: str,
        user_text: str,
        images: list[str],
        tools: list[dict] | None = None,
        schema_hint: dict | None = None,
    ) -> AgentResponse:
        """Call LLM with vision (images as base64) and optional tool definitions.

        Args:
            system: System prompt
            user_text: Text part of user message
            images: List of base64-encoded image strings (JPEG)
            tools: Optional list of tool definitions for function calling
            schema_hint: Hint for MockAgent
        """
        logger.debug("AgentClient.call: mode=%s, system_len=%d, user_len=%d", self._mode, len(system), len(user_text))

        if self._mode == "mock":
            return self._mock_agent.call(system, user_text, schema_hint or {})

        try:
            raw = self._call_vision_api(system, user_text, images, tools)
        except Exception as e:
            logger.warning("LLM vision call failed (%s), falling back to MockAgent", e)
            return self._mock_agent.call(system, user_text, schema_hint or {})

        return self._parse_with_repair(raw)

    # ------------------------------------------------------------------
    # Private: text-only API call
    # ------------------------------------------------------------------

    def _call_openai_compat(self, system: str, user: str) -> str:
        """Call OpenAI-compatible chat completions API."""
        import requests

        url = self._base_url.rstrip("/") + "/chat/completions"
        logger.debug("LLM API request: url=%s, model=%s", url, self._model)
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

        t0 = time.perf_counter()
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        elapsed = time.perf_counter() - t0
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        logger.debug("LLM API response: status=%d, content_len=%d, took=%.3fs", resp.status_code, len(content), elapsed)
        return content

    # ------------------------------------------------------------------
    # Private: vision API call with optional tools
    # ------------------------------------------------------------------

    def _call_vision_api(
        self,
        system: str,
        user_text: str,
        images: list[str],
        tools: list[dict] | None = None,
    ) -> str:
        """Call OpenAI-compatible vision API with images and optional tools."""
        import requests

        url = self._base_url.rstrip("/") + "/chat/completions"
        logger.debug("LLM API request: url=%s, model=%s", url, self._model)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        # Build multimodal user content
        user_content: list[dict] = [{"type": "text", "text": user_text}]
        for img_b64 in images[:3]:  # Limit to 3 images to control token cost
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
            })

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "max_tokens": 2000,
        }

        # Add tools if provided (function calling)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = requests.post(url, json=payload, headers=headers, timeout=90)
        resp.raise_for_status()
        data = resp.json()

        # Handle tool calls response
        message = data["choices"][0]["message"]
        if message.get("tool_calls"):
            tool_calls = message["tool_calls"]
            logger.debug("LLM tool_calls: %d calls, functions=%s", len(tool_calls), [tc["function"]["name"] for tc in tool_calls])
            # Execute tool calls and make follow-up request
            return self._handle_tool_calls(message, payload, headers, url)

        content = message.get("content", "")
        logger.debug("LLM API response: status=%d, content_len=%d, took=%.3fs", resp.status_code, len(content), 0.0)
        return content

    # ------------------------------------------------------------------
    # Private: function calling handler
    # ------------------------------------------------------------------

    def _handle_tool_calls(
        self,
        assistant_message: dict,
        original_payload: dict,
        headers: dict,
        url: str,
    ) -> str:
        """Handle function calling: execute tools and get final response."""
        import requests

        tool_results = []
        for tool_call in assistant_message["tool_calls"]:
            func_name = tool_call["function"]["name"]
            func_args = json.loads(tool_call["function"]["arguments"])

            # Execute the tool locally
            result = self._execute_tool(func_name, func_args)
            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })

        # Follow-up call with tool results
        messages = original_payload["messages"] + [assistant_message] + tool_results
        follow_up = {
            "model": original_payload["model"],
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2000,
        }

        resp = requests.post(url, json=follow_up, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"].get("content", "")

    def _execute_tool(self, func_name: str, func_args: dict) -> dict:
        """Execute a tool call locally. Tools are registered by L4AgentReview."""
        if func_name in self._registered_tools:
            result = self._registered_tools[func_name](func_args)
            logger.debug("Tool executed: %s, result_keys=%s", func_name, list(result.keys()))
            return result
        return {"error": f"Unknown tool: {func_name}"}

    # ------------------------------------------------------------------
    # Private: JSON parsing and repair
    # ------------------------------------------------------------------

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
                logger.debug("JSON repair attempted: success=%s, method=%s", True, "strip_markdown")
                return stripped
            except json.JSONDecodeError:
                pass

        # Find first { ... last }
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            logger.debug("JSON repair attempted: success=%s, method=%s", True, "brace_extract")
            return m.group(0)

        logger.debug("JSON repair attempted: success=%s, method=%s", False, "none")
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
