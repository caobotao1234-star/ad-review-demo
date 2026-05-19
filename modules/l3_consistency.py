"""L3 Consistency: 5 rules checking ad claim vs landing page vs qualification."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from modules.schemas import (
    AdMeta,
    ReasonCode,
    Signal,
    SignalSource,
)
from modules.utils import normalize_text, render_reason

logger = logging.getLogger(__name__)


@dataclass
class ConsistencyResult:
    signals: list[Signal] = field(default_factory=list)
    extra_score: int = 0


class L3Consistency:
    """5 deterministic consistency rules between ad claim, landing page, category, and qualification."""

    def check(self, ad: AdMeta, ad_claim_text: str, l2_signals: list[Signal]) -> ConsistencyResult:
        """Run 5 consistency rules and return aggregated signals + extra score."""
        signals: list[Signal] = []

        norm_claim = normalize_text(ad_claim_text)
        norm_landing = normalize_text(ad.landing_page.text)

        # Rule 1: 官方正品 in claim but missing brand_authorization
        if "官方正品" in norm_claim and not ad.merchant.qualification.brand_authorization:
            signals.append(Signal(
                source=SignalSource.CONSISTENCY,
                code=ReasonCode.L3_OFFICIAL_NO_AUTHORIZATION,
                detail="素材宣称官方正品但缺失品牌授权",
                score_delta=30,
            ))

        # Rule 2: 正品 in claim and landing contains 渠道货/尾单/复刻
        if "正品" in norm_claim and any(w in norm_landing for w in ["渠道货", "尾单", "复刻"]):
            signals.append(Signal(
                source=SignalSource.CONSISTENCY,
                code=ReasonCode.L3_OFFICIAL_VS_CHANNEL,
                detail="素材宣称正品但落地页含渠道货/尾单/复刻",
                score_delta=20,
            ))

        # Rule 3: 低价/免费 in claim but landing price > 100
        if any(w in norm_claim for w in ["低价", "免费"]):
            if ad.landing_page.price is not None and ad.landing_page.price > 100:
                signals.append(Signal(
                    source=SignalSource.CONSISTENCY,
                    code=ReasonCode.L3_PRICE_CONFLICT,
                    detail=f"素材宣称低价/免费但落地页价格为{ad.landing_page.price}",
                    score_delta=20,
                ))

        # Rule 4: category==日用品 and claim+landing contains 减肥/治疗/理财/投资
        if ad.category == "日用品":
            combined = norm_claim + norm_landing
            if any(w in combined for w in ["减肥", "治疗", "理财", "投资"]):
                matched = [w for w in ["减肥", "治疗", "理财", "投资"] if w in combined]
                signals.append(Signal(
                    source=SignalSource.CONSISTENCY,
                    code=ReasonCode.L3_CATEGORY_MISMATCH,
                    detail=f"类目为日用品但文本含跨类目内容: {','.join(matched)}",
                    score_delta=30,
                ))

        # Rule 5: 平台内购买/站内下单 in claim and landing contains 微信咨询/私聊
        if any(w in norm_claim for w in ["平台内购买", "站内下单"]):
            if any(w in norm_landing for w in ["微信咨询", "私聊"]):
                signals.append(Signal(
                    source=SignalSource.CONSISTENCY,
                    code=ReasonCode.L3_PRIVATE_DOMAIN_CONFLICT,
                    detail="素材宣称平台内购买但落地页含私域引流词",
                    score_delta=25,
                ))

        extra_score = sum(s.score_delta for s in signals)
        return ConsistencyResult(signals=signals, extra_score=extra_score)
