"""L1 History Recall: video fingerprint matching against historical records."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from modules.schemas import (
    Decision,
    LayerResult,
    MediaResult,
    ReasonCode,
    Signal,
    SignalSource,
    Thresholds,
)
from modules.utils import hamming_distance, render_reason

logger = logging.getLogger(__name__)


class L1Recall:
    """L1 layer: recall historical fingerprints by pHash similarity."""

    def __init__(self, fingerprints_path: Path, thresholds: Thresholds) -> None:
        self.thresholds = thresholds
        self.fingerprints: list[dict[str, Any]] = []
        self._load_fingerprints(fingerprints_path)

    def recall(self, media: MediaResult) -> LayerResult:
        """Match current media fingerprint against history. Returns LayerResult."""
        # Guard: mock media or empty phash_list → NEXT
        if media.mock or not media.fingerprint.phash_list:
            reason = render_reason(ReasonCode.L1_NO_MATCH, {})
            return LayerResult(
                layer="L1",
                decision=Decision.NEXT,
                reason_code=ReasonCode.L1_NO_MATCH,
                reason=reason,
            )

        # Compute similarity ratio for each historical fingerprint
        best_match: dict[str, Any] | None = None
        best_ratio: float = 0.0

        for hist in self.fingerprints:
            hist_phash_list: list[str] = hist.get("phash_list", [])
            if not hist_phash_list:
                continue
            ratio = self._compute_similar_ratio(
                media.fingerprint.phash_list,
                hist_phash_list,
            )
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = hist

        # Decision based on best match
        if best_match is None or best_ratio < self.thresholds.l1_history_match_threshold:
            reason = render_reason(ReasonCode.L1_NO_MATCH, {})
            return LayerResult(
                layer="L1",
                decision=Decision.NEXT,
                reason_code=ReasonCode.L1_NO_MATCH,
                reason=reason,
            )

        history_id = best_match.get("history_id", "unknown")
        label = best_match.get("label", "unknown")
        ctx = {"history_id": history_id, "ratio": best_ratio}

        if label == "violation":
            reason_code = ReasonCode.L1_HISTORY_VIOLATION_HIT
            decision = Decision.REJECT
        elif label == "safe":
            reason_code = ReasonCode.L1_HISTORY_SAFE_HIT
            decision = Decision.APPROVE
        else:
            # Unknown label → treat as NEXT
            reason = render_reason(ReasonCode.L1_NO_MATCH, {})
            return LayerResult(
                layer="L1",
                decision=Decision.NEXT,
                reason_code=ReasonCode.L1_NO_MATCH,
                reason=reason,
            )

        reason = render_reason(reason_code, ctx)
        signals = [
            Signal(
                source=SignalSource.HISTORY,
                code=reason_code,
                detail=f"history_id={history_id}, ratio={best_ratio:.2f}",
                score_delta=0,
            )
        ]

        return LayerResult(
            layer="L1",
            decision=decision,
            reason_code=reason_code,
            reason=reason,
            signals=signals,
            extra={"history_id": history_id, "ratio": best_ratio},
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_fingerprints(self, path: Path) -> None:
        """Load history fingerprints from JSON file."""
        if not path.exists():
            logger.error("History fingerprints file %s not found", path)
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.fingerprints = data.get("fingerprints", [])
            logger.info("Loaded %d history fingerprints from %s", len(self.fingerprints), path)
        except (json.JSONDecodeError, Exception) as e:  # noqa: BLE001
            logger.error("Failed to load history fingerprints from %s: %s", path, e)

    def _compute_similar_ratio(
        self,
        current_phash_list: list[str],
        hist_phash_list: list[str],
    ) -> float:
        """Compute the ratio of current frames that match any historical frame."""
        if not current_phash_list:
            return 0.0
        threshold = self.thresholds.l1_hamming_threshold
        similar_count = 0
        for cur_phash in current_phash_list:
            for hist_phash in hist_phash_list:
                if hamming_distance(cur_phash, hist_phash) <= threshold:
                    similar_count += 1
                    break
        return similar_count / len(current_phash_list)
