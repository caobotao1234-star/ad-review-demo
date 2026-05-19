"""L3 Risk Fusion: aggregate signals from L1/L2/L3 and make threshold-based decision."""

from __future__ import annotations

import logging

from modules.l3_consistency import ConsistencyResult
from modules.l3_text_embedding import SimilarityResult
from modules.schemas import (
    AdMeta,
    Decision,
    LayerResult,
    ReasonCode,
    Signal,
    SignalSource,
    Thresholds,
)
from modules.utils import render_reason

logger = logging.getLogger(__name__)

# Conflict codes that force AGENT_REVIEW even at low risk scores
CONFLICT_CODES = {
    ReasonCode.L3_OFFICIAL_NO_AUTHORIZATION,
    ReasonCode.L3_OFFICIAL_VS_CHANNEL,
    ReasonCode.L3_PRICE_CONFLICT,
    ReasonCode.L3_CATEGORY_MISMATCH,
    ReasonCode.L3_PRIVATE_DOMAIN_CONFLICT,
}


class L3RiskFusion:
    """Fuse all signals from L1/L2/L3Consistency/L3TextEmbedding into a final L3 decision."""

    def __init__(self, thresholds: Thresholds) -> None:
        self.thresholds = thresholds

    def fuse(
        self,
        ad: AdMeta,
        l1: LayerResult,
        l2: LayerResult,
        consistency: ConsistencyResult,
        embedding: SimilarityResult,
    ) -> LayerResult:
        """Aggregate signals, compute risk_score, and decide REJECT/APPROVE/AGENT_REVIEW."""
        all_signals: list[Signal] = []

        # Collect signals from L1, L2, and L3 consistency
        all_signals.extend(l1.signals)
        all_signals.extend(l2.signals)
        all_signals.extend(consistency.signals)

        # Compute base risk score from all signal deltas
        risk_score = sum(s.score_delta for s in all_signals)

        # Merchant history violation bonus
        if ad.merchant.history_violation_count > 0:
            risk_score += 10
            all_signals.append(Signal(
                source=SignalSource.HISTORY,
                code=ReasonCode.L3_AGENT_REVIEW,
                detail=f"merchant history_violation_count={ad.merchant.history_violation_count}",
                score_delta=10,
            ))

        # Low embedding similarity bonus
        if embedding.score < 0.5:
            risk_score += 10
            all_signals.append(Signal(
                source=SignalSource.EMBEDDING,
                code=ReasonCode.L3_LOW_SEMANTIC_SIMILARITY,
                detail=f"embedding_score={embedding.score:.2f}",
                score_delta=10,
            ))

        # Check for conflict codes
        has_conflict = any(s.code in CONFLICT_CODES for s in all_signals)

        # Threshold-based decision
        if risk_score >= self.thresholds.l3_reject_score:
            reason = render_reason(
                ReasonCode.L3_RISK_SCORE_OVER_REJECT,
                {"risk_score": risk_score, "threshold": self.thresholds.l3_reject_score},
            )
            return LayerResult(
                layer="L3",
                decision=Decision.REJECT,
                risk_score=risk_score,
                reason_code=ReasonCode.L3_RISK_SCORE_OVER_REJECT,
                reason=reason,
                signals=all_signals,
            )

        if risk_score <= self.thresholds.l3_approve_score and not has_conflict:
            reason = render_reason(
                ReasonCode.L3_RISK_SCORE_UNDER_APPROVE,
                {"risk_score": risk_score, "threshold": self.thresholds.l3_approve_score},
            )
            return LayerResult(
                layer="L3",
                decision=Decision.APPROVE,
                risk_score=risk_score,
                reason_code=ReasonCode.L3_RISK_SCORE_UNDER_APPROVE,
                reason=reason,
                signals=all_signals,
            )

        # Gray zone → AGENT_REVIEW
        reason = render_reason(
            ReasonCode.L3_AGENT_REVIEW,
            {"risk_score": risk_score},
        )
        return LayerResult(
            layer="L3",
            decision=Decision.AGENT_REVIEW,
            risk_score=risk_score,
            reason_code=ReasonCode.L3_AGENT_REVIEW,
            reason=reason,
            signals=all_signals,
        )
