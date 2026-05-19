"""Unit tests for L3 Risk Fusion."""
import pytest
from modules.schemas import (
    AdMeta, Decision, LayerResult, Merchant, Qualification,
    ReasonCode, Signal, SignalSource, Thresholds,
)
from modules.l3_consistency import ConsistencyResult
from modules.l3_text_embedding import SimilarityResult
from modules.l3_risk_fusion import L3RiskFusion


def make_ad(**kwargs):
    defaults = {
        "ad_id": "test",
        "merchant": Merchant(merchant_id="m1", qualification=Qualification()),
    }
    defaults.update(kwargs)
    return AdMeta(**defaults)


@pytest.fixture
def thresholds():
    return Thresholds(l3_reject_score=120, l3_approve_score=20)


def empty_layer(layer="L1"):
    return LayerResult(layer=layer, decision=Decision.NEXT)


def test_low_risk_approves(thresholds):
    fusion = L3RiskFusion(thresholds)
    ad = make_ad()
    result = fusion.fuse(
        ad, empty_layer("L1"), empty_layer("L2"),
        ConsistencyResult(signals=[], extra_score=0),
        SimilarityResult(score=0.8, backend="token_overlap"),
    )
    assert result.decision == Decision.APPROVE


def test_high_risk_rejects(thresholds):
    fusion = L3RiskFusion(thresholds)
    ad = make_ad(merchant=Merchant(merchant_id="m1", qualification=Qualification(), history_violation_count=2))
    l2 = LayerResult(layer="L2", decision=Decision.NEXT, signals=[
        Signal(source=SignalSource.KEYWORD, code=ReasonCode.L2_SUSPICIOUS_SLANG_HIT, detail="test", score_delta=15),
        Signal(source=SignalSource.CATEGORY, code=ReasonCode.L2_MISSING_BRAND_AUTHORIZATION, detail="test", score_delta=30),
        Signal(source=SignalSource.LANDING_PAGE, code=ReasonCode.L2_PRIVATE_DOMAIN_DRAINAGE, detail="test", score_delta=20),
    ])
    consistency = ConsistencyResult(signals=[
        Signal(source=SignalSource.CONSISTENCY, code=ReasonCode.L3_OFFICIAL_NO_AUTHORIZATION, detail="test", score_delta=30),
        Signal(source=SignalSource.CONSISTENCY, code=ReasonCode.L3_OFFICIAL_VS_CHANNEL, detail="test", score_delta=20),
    ], extra_score=50)
    result = fusion.fuse(
        ad, empty_layer("L1"), l2, consistency,
        SimilarityResult(score=0.3, backend="token_overlap"),
    )
    assert result.decision == Decision.REJECT


def test_gray_zone_agent_review(thresholds):
    fusion = L3RiskFusion(thresholds)
    ad = make_ad()
    l2 = LayerResult(layer="L2", decision=Decision.NEXT, signals=[
        Signal(source=SignalSource.KEYWORD, code=ReasonCode.L2_SUSPICIOUS_SLANG_HIT, detail="test", score_delta=15),
    ])
    consistency = ConsistencyResult(signals=[
        Signal(source=SignalSource.CONSISTENCY, code=ReasonCode.L3_OFFICIAL_NO_AUTHORIZATION, detail="test", score_delta=30),
    ], extra_score=30)
    result = fusion.fuse(
        ad, empty_layer("L1"), l2, consistency,
        SimilarityResult(score=0.6, backend="token_overlap"),
    )
    assert result.decision == Decision.AGENT_REVIEW
