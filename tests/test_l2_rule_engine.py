"""Unit tests for L2 Rule Engine."""
import pytest
from modules.schemas import (
    AdMeta, Decision, KeywordsConfig, KeywordEntry,
    CategoryRulesConfig, CategoryRule, Thresholds, Merchant, Qualification, LandingPage,
)
from modules.l2_rule_engine import L2RuleEngine, FrameOCR, ASRResult, QRHit


def make_ad(**kwargs):
    defaults = {
        "ad_id": "test",
        "merchant": Merchant(merchant_id="m1", qualification=Qualification()),
    }
    defaults.update(kwargs)
    return AdMeta(**defaults)


def make_keywords(hard=None, normalized=None, slang=None):
    return KeywordsConfig(
        hard_block=[KeywordEntry(word=w, category="all") for w in (hard or [])],
        normalized_block=[KeywordEntry(word=w, category="all") for w in (normalized or [])],
        suspicious_slang=[KeywordEntry(word=w, category="all") for w in (slang or [])],
    )


@pytest.fixture
def thresholds():
    return Thresholds()


@pytest.fixture
def category_rules():
    return CategoryRulesConfig()


class TestHardBlock:
    def test_hard_block_in_title_rejects(self, thresholds, category_rules):
        kw = make_keywords(hard=["高仿"])
        ad = make_ad(title="这是高仿包包")
        engine = L2RuleEngine(kw, category_rules, thresholds)
        result = engine.evaluate(ad, [], ASRResult(text=""), [])
        assert result.decision == Decision.REJECT
        assert result.reason_code.value == "L2_HARD_BLOCK_HIT"

    def test_hard_block_in_landing_rejects(self, thresholds, category_rules):
        kw = make_keywords(hard=["A货"])
        ad = make_ad(landing_page=LandingPage(text="A货精品"))
        engine = L2RuleEngine(kw, category_rules, thresholds)
        result = engine.evaluate(ad, [], ASRResult(text=""), [])
        assert result.decision == Decision.REJECT


class TestSuspiciousSlang:
    def test_slang_does_not_reject(self, thresholds, category_rules):
        kw = make_keywords(slang=["柜姐渠道"])
        ad = make_ad(title="柜姐渠道好货")
        engine = L2RuleEngine(kw, category_rules, thresholds)
        result = engine.evaluate(ad, [], ASRResult(text=""), [])
        assert result.decision == Decision.NEXT
        assert result.risk_score >= 15


class TestCategoryQualification:
    def test_financial_sensitive_no_license_rejects(self, thresholds):
        rules = CategoryRulesConfig(rules=[
            CategoryRule(category="金融", required_qualifications=["financial_license"],
                        sensitive_claims=["稳赚", "保本"])
        ])
        kw = make_keywords()
        ad = make_ad(category="金融", title="稳赚不赔的好项目",
                     merchant=Merchant(merchant_id="m1", qualification=Qualification()))
        engine = L2RuleEngine(kw, rules, thresholds)
        result = engine.evaluate(ad, [], ASRResult(text=""), [])
        assert result.decision == Decision.REJECT
