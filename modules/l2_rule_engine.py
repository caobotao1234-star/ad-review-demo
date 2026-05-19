"""L2 Rule Engine: keyword matching, category qualification, and landing page rules."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from modules.schemas import (
    AdMeta,
    CategoryRulesConfig,
    Decision,
    Evidence,
    KeywordsConfig,
    LayerResult,
    ReasonCode,
    Signal,
    SignalSource,
    Thresholds,
)
from modules.utils import normalize_text, render_reason

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local dataclasses for L2 inputs
# ---------------------------------------------------------------------------


@dataclass
class FrameOCR:
    frame_id: str
    texts: list[str]


@dataclass
class ASRResult:
    text: str
    mock: bool = False
    fallback_reason: str | None = None


@dataclass
class QRHit:
    frame_id: str
    decoded_text: str
    is_private_drainage: bool = False


# ---------------------------------------------------------------------------
# L2 Rule Engine
# ---------------------------------------------------------------------------


class L2RuleEngine:
    """L2 layer: deterministic rule-based evaluation combining keywords, category, and landing page."""

    def __init__(
        self,
        keywords: KeywordsConfig,
        category_rules: CategoryRulesConfig,
        thresholds: Thresholds,
    ) -> None:
        self.keywords = keywords
        self.category_rules = category_rules
        self.thresholds = thresholds

    def evaluate(
        self,
        ad: AdMeta,
        ocr: list[FrameOCR],
        asr: ASRResult,
        qr: list[QRHit],
    ) -> LayerResult:
        """Run all L2 rules and return a LayerResult."""
        signals: list[Signal] = []
        evidence: list[Evidence] = []
        risk_score = 0

        # --- 1. Build ad_claim_text (kept for category/landing checks) ---
        ocr_texts = []
        for frame_ocr in ocr:
            ocr_texts.extend(frame_ocr.texts)

        ad_claim_text = " ".join(
            filter(None, [ad.title, ad.description] + ocr_texts + [asr.text])
        )

        # --- 2. Build text_sources for per-source keyword matching ---
        text_sources: list[tuple[str, str]] = [
            ("title", ad.title),
            ("description", ad.description),
        ]
        for frame_ocr in ocr:
            text_sources.append((f"ocr:{frame_ocr.frame_id}", " ".join(frame_ocr.texts)))
        text_sources.append(("asr", asr.text))
        text_sources.append(("landing_page", ad.landing_page.text))

        logger.debug("L2RuleEngine.evaluate: ad_id=%s, category=%s, text_sources=%d", ad.ad_id, ad.category, len(text_sources))

        # Normalize claim text for category/landing checks (unchanged)
        norm_claim = normalize_text(ad_claim_text)

        # --- 3. Hard block keywords (per-source matching) ---
        for entry in self.keywords.hard_block:
            if entry.category != "all" and entry.category != ad.category:
                continue
            norm_word = normalize_text(entry.word)
            for source_name, source_text in text_sources:
                norm_source = normalize_text(source_text)
                if norm_word in norm_source:
                    logger.debug("L2 keyword hit: type=%s, word=%s, source=%s", "hard_block", entry.word, source_name)
                    reason = render_reason(
                        ReasonCode.L2_HARD_BLOCK_HIT,
                        {"keyword": entry.word, "source": source_name},
                    )
                    signals.append(Signal(
                        source=SignalSource.KEYWORD,
                        code=ReasonCode.L2_HARD_BLOCK_HIT,
                        detail=f"{entry.word} (来源: {source_name})",
                        score_delta=40,
                    ))
                    evidence.append(Evidence(
                        source=SignalSource.KEYWORD,
                        raw=entry.word,
                        normalized=norm_word,
                        location=source_name,
                    ))
                    return LayerResult(
                        layer="L2",
                        decision=Decision.REJECT,
                        risk_score=risk_score + 40,
                        reason_code=ReasonCode.L2_HARD_BLOCK_HIT,
                        reason=reason,
                        signals=signals,
                        evidence=evidence,
                    )

        # --- 4. Normalized block keywords (per-source matching) ---
        for entry in self.keywords.normalized_block:
            if entry.category != "all" and entry.category != ad.category:
                continue
            norm_word = normalize_text(entry.word)
            for source_name, source_text in text_sources:
                norm_source = normalize_text(source_text)
                if norm_word in norm_source:
                    logger.debug("L2 keyword hit: type=%s, word=%s, source=%s", "normalized_block", entry.word, source_name)
                    reason = render_reason(
                        ReasonCode.L2_NORMALIZED_BLOCK_HIT,
                        {"keyword": entry.word, "raw_text": entry.word, "source": source_name},
                    )
                    signals.append(Signal(
                        source=SignalSource.KEYWORD,
                        code=ReasonCode.L2_NORMALIZED_BLOCK_HIT,
                        detail=f"{entry.word} (来源: {source_name})",
                        score_delta=40,
                    ))
                    evidence.append(Evidence(
                        source=SignalSource.KEYWORD,
                        raw=entry.word,
                        normalized=norm_word,
                        location=source_name,
                    ))
                    return LayerResult(
                        layer="L2",
                        decision=Decision.REJECT,
                        risk_score=risk_score + 40,
                        reason_code=ReasonCode.L2_NORMALIZED_BLOCK_HIT,
                        reason=reason,
                        signals=signals,
                        evidence=evidence,
                    )

        # --- 5. Suspicious slang (per-source matching) ---
        for entry in self.keywords.suspicious_slang:
            if entry.category != "all" and entry.category != ad.category:
                continue
            norm_word = normalize_text(entry.word)
            for source_name, source_text in text_sources:
                norm_source = normalize_text(source_text)
                if norm_word in norm_source:
                    logger.debug("L2 keyword hit: type=%s, word=%s, source=%s", "suspicious_slang", entry.word, source_name)
                    risk_score += 15
                    signals.append(Signal(
                        source=SignalSource.KEYWORD,
                        code=ReasonCode.L2_SUSPICIOUS_SLANG_HIT,
                        detail=f"{entry.word} (来源: {source_name})",
                        score_delta=15,
                    ))
                    evidence.append(Evidence(
                        source=SignalSource.KEYWORD,
                        raw=entry.word,
                        normalized=norm_word,
                        location=source_name,
                    ))
                    break  # 每个关键词只记录第一个命中源

        # --- 6. Category qualification check ---
        cat_signals = self._check_category_qualification(ad, norm_claim)
        logger.debug("L2 category check: category=%s, has_sensitive=%s, missing_quals=%s", ad.category, any(s.code == ReasonCode.L2_HARD_BLOCK_HIT for s in cat_signals), [s.detail for s in cat_signals if s.code != ReasonCode.L2_HARD_BLOCK_HIT])
        for sig in cat_signals:
            # Financial sensitive claim + missing license → direct REJECT
            if sig.code == ReasonCode.L2_HARD_BLOCK_HIT:
                risk_score += sig.score_delta
                signals.append(sig)
                reason = render_reason(
                    ReasonCode.L2_MISSING_FINANCIAL_LICENSE,
                    {"category": ad.category},
                )
                return LayerResult(
                    layer="L2",
                    decision=Decision.REJECT,
                    risk_score=risk_score,
                    reason_code=ReasonCode.L2_MISSING_FINANCIAL_LICENSE,
                    reason=reason,
                    signals=signals,
                    evidence=evidence,
                )
            risk_score += sig.score_delta
            signals.append(sig)

        # --- 7. Landing page rules ---
        landing_signals = self._check_landing_page(ad, qr, norm_claim)
        for sig in landing_signals:
            risk_score += sig.score_delta
            signals.append(sig)

        # --- 8/9. Final decision ---
        # No hard_block/normalized_block hit reached here → decision=NEXT
        reason_code = None
        reason = ""
        if signals:
            # Use the first signal's code as representative
            reason_code = signals[0].code
            reason = render_reason(reason_code, {"keyword": signals[0].detail, "source": "L2"})

        logger.info("L2RuleEngine result: decision=%s, risk_score=%d, signals=%d, reason_code=%s", Decision.NEXT.value, risk_score, len(signals), reason_code)

        return LayerResult(
            layer="L2",
            decision=Decision.NEXT,
            risk_score=risk_score,
            reason_code=reason_code,
            reason=reason,
            signals=signals,
            evidence=evidence,
        )

    # ------------------------------------------------------------------
    # Internal: Category qualification
    # ------------------------------------------------------------------

    def _check_category_qualification(self, ad: AdMeta, norm_claim: str) -> list[Signal]:
        """Check category-specific qualification requirements."""
        signals: list[Signal] = []
        cat = ad.category

        for rule in self.category_rules.rules:
            if rule.category != cat:
                continue

            # Check if any sensitive claim is present
            has_sensitive_claim = any(
                normalize_text(claim) in norm_claim for claim in rule.sensitive_claims
            )

            # Check required qualifications
            for qual_name in rule.required_qualifications:
                qual_value = getattr(ad.merchant.qualification, qual_name, None)
                if not qual_value:
                    # Missing qualification
                    if qual_name == "brand_authorization":
                        signals.append(Signal(
                            source=SignalSource.CATEGORY,
                            code=ReasonCode.L2_MISSING_BRAND_AUTHORIZATION,
                            detail=f"category={cat}",
                            score_delta=30,
                        ))
                    elif qual_name == "financial_license":
                        signals.append(Signal(
                            source=SignalSource.CATEGORY,
                            code=ReasonCode.L2_MISSING_FINANCIAL_LICENSE,
                            detail=f"category={cat}",
                            score_delta=30,
                        ))
                        # Financial: sensitive claim + missing license → REJECT
                        if has_sensitive_claim:
                            signals.append(Signal(
                                source=SignalSource.CATEGORY,
                                code=ReasonCode.L2_HARD_BLOCK_HIT,
                                detail=f"金融敏感宣称+缺资质, category={cat}",
                                score_delta=40,
                            ))
                    elif qual_name == "medical_license":
                        signals.append(Signal(
                            source=SignalSource.CATEGORY,
                            code=ReasonCode.L2_MISSING_MEDICAL_LICENSE,
                            detail=f"category={cat}",
                            score_delta=30,
                        ))

        return signals

    # ------------------------------------------------------------------
    # Internal: Landing page rules
    # ------------------------------------------------------------------

    def _check_landing_page(
        self,
        ad: AdMeta,
        qr_hits: list[QRHit],
        norm_claim: str,
    ) -> list[Signal]:
        """Check landing page for private drainage and price inconsistency."""
        signals: list[Signal] = []
        norm_landing = normalize_text(ad.landing_page.text)

        # Private domain drainage
        drainage_words = ["微信咨询", "加微信", "vx", "私聊"]
        has_drainage = any(w in norm_landing for w in drainage_words)
        has_qr_drainage = any(q.is_private_drainage for q in qr_hits)

        if has_drainage or has_qr_drainage:
            detail = "landing_text" if has_drainage else "qr_code"
            signals.append(Signal(
                source=SignalSource.LANDING_PAGE,
                code=ReasonCode.L2_PRIVATE_DOMAIN_DRAINAGE,
                detail=detail,
                score_delta=20,
            ))

        # Price inconsistency: claim low price/free but landing price > 100
        low_price_words = ["低价", "免费"]
        if any(w in norm_claim for w in low_price_words):
            if ad.landing_page.price is not None and ad.landing_page.price > 100:
                signals.append(Signal(
                    source=SignalSource.LANDING_PAGE,
                    code=ReasonCode.L2_PRICE_INCONSISTENT,
                    detail=f"price={ad.landing_page.price}",
                    score_delta=10,
                ))

        return signals
