"""L5 Strategy Agent: discover candidate slang and optimization suggestions."""
from __future__ import annotations
import collections
import json
import logging
from pathlib import Path
from typing import Any

from modules.agent_client import AgentClient
from modules.schemas import StrategyResult, Suggestion
from modules.utils import normalize_text

logger = logging.getLogger(__name__)


class L5StrategyAgent:
    def __init__(self, agent: AgentClient) -> None:
        self.agent = agent

    def analyze(self, logs: list[dict]) -> StrategyResult:
        """Analyze optimization logs and produce strategy suggestions."""
        # Local frequency-based candidate discovery (deterministic, no LLM needed)
        candidates = self._discover_candidate_slang(logs)

        # Use agent for problem summarization (optional, MockAgent works too)
        system = (
            "你是策略优化 Agent。分析以下审核日志，输出 JSON：\n"
            "optimization_target, problem, suggestions[{type,words,action,route}], "
            "validation_plan, risk, requires_human_approval=true"
        )
        user = json.dumps({
            "log_count": len(logs),
            "candidate_slang": candidates,
            "log_types": [l.get("type") for l in logs],
        }, ensure_ascii=False)

        response = self.agent.call(system, user, {"scenario": "l5_strategy"})

        # Build result from local analysis (agent response is supplementary)
        suggestions = [
            Suggestion(
                type="keyword",
                words=candidates,
                action="add_to_suspicious_slang",
                route="L3",
            )
        ]

        problem = "箱包类广告中频繁出现未被现有词库覆盖的黑话表述，导致漏判"
        if response.parsed and not response.error:
            problem = response.parsed.get("problem", problem)

        return StrategyResult(
            optimization_target="L2_keyword_rules",
            problem=problem,
            suggestions=suggestions,
            validation_plan="对候选词进行回放验证，评估误杀率后灰度上线",
            risk="新增词可能导致部分正常代购广告被加分进入 L3 复核",
            requires_human_approval=True,
        )

    def write_candidate_keywords(self, suggestions: list[Suggestion], path: Path) -> None:
        """Write candidate keywords YAML with candidate status markers."""
        import yaml

        content = {
            "status": "candidate",
            "auto_apply": False,
            "requires_human_approval": True,
            "suggestions": [
                {
                    "type": s.type,
                    "action": s.action,
                    "route": s.route,
                    "words": s.words,
                }
                for s in suggestions
            ],
        }

        header = (
            "# ===== 候选词库, 不自动上线 =====\n"
            "# 由 L5StrategyAgent 生成\n"
            "# 必须经过人工审批后再合并到 config/keywords.yaml\n\n"
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(header)
            yaml.dump(content, f, allow_unicode=True, default_flow_style=False)

    def _discover_candidate_slang(self, logs: list[dict]) -> list[str]:
        """Frequency-based n-gram candidate discovery from logs."""
        # Focus on problematic logs
        target_types = {"false_approve", "human_reject", "appeal_overturn"}
        target_logs = [l for l in logs if l.get("type") in target_types]

        counter: collections.Counter = collections.Counter()
        for log in target_logs:
            text = normalize_text(log.get("text", ""))
            # n-gram extraction (n=2..6)
            for n in range(2, 7):
                for i in range(len(text) - n + 1):
                    gram = text[i:i + n]
                    counter[gram] += 1

        # Filter: frequency >= 2, length >= 2
        candidates = [
            word for word, count in counter.most_common(100)
            if count >= 2 and len(word) >= 3
        ]

        # Deduplicate substrings (keep longer ones)
        final: list[str] = []
        for w in candidates:
            if not any(w in other and w != other for other in candidates[:50]):
                final.append(w)
            if len(final) >= 20:
                break

        return final[:20]
