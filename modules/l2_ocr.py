"""L2 OCR module: PaddleOCR-based text extraction with mock fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from modules.schemas import AdMeta, MediaResult, RuntimeConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FrameOCR:
    frame_id: str
    texts: list[str]


# ---------------------------------------------------------------------------
# PaddleOCR availability check
# ---------------------------------------------------------------------------

_PADDLEOCR_AVAILABLE: bool | None = None


def _check_paddleocr() -> bool:
    """Check if PaddleOCR can be imported."""
    global _PADDLEOCR_AVAILABLE  # noqa: PLW0603
    if _PADDLEOCR_AVAILABLE is None:
        try:
            import paddleocr  # noqa: F401
            _PADDLEOCR_AVAILABLE = True
        except ImportError:
            _PADDLEOCR_AVAILABLE = False
            logger.warning("PaddleOCR not available, OCR will use mock mode")
    return _PADDLEOCR_AVAILABLE


# ---------------------------------------------------------------------------
# L2OCR class
# ---------------------------------------------------------------------------


class L2OCR:
    """L2 OCR extractor: uses PaddleOCR when available, otherwise falls back to mock."""

    def __init__(self, runtime: RuntimeConfig) -> None:
        self.runtime = runtime

    def extract(self, ad: AdMeta, media: MediaResult) -> list[FrameOCR]:
        """Extract OCR texts from sampled frames.

        Returns a list of FrameOCR, one per sampled frame.
        Falls back to mock_ocr_texts when OCR is disabled or PaddleOCR unavailable.
        """
        # Determine if we should use real OCR
        use_real_ocr = self.runtime.enable_ocr and _check_paddleocr()

        if not use_real_ocr:
            return self._mock_from_ad(ad, media)

        # Real OCR mode (TODO: implement actual PaddleOCR calls)
        # For now, fall back to mock as PaddleOCR integration is a placeholder
        return self._mock_from_ad(ad, media)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _mock_from_ad(self, ad: AdMeta, media: MediaResult) -> list[FrameOCR]:
        """Build mock FrameOCR results from ad.mock_ocr_texts."""
        mock_texts = ad.mock_ocr_texts if ad.mock_ocr_texts else []
        results: list[FrameOCR] = []

        if media.sampled_frames:
            for frame_ref in media.sampled_frames:
                results.append(FrameOCR(
                    frame_id=frame_ref.frame_id,
                    texts=list(mock_texts),
                ))
        else:
            # No sampled frames (mock media) → single entry
            results.append(FrameOCR(
                frame_id="frame_0000",
                texts=list(mock_texts),
            ))

        return results
