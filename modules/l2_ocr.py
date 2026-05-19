"""L2 OCR module: PaddleOCR-based text extraction with mock fallback."""

from __future__ import annotations

import logging
import time
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
        self._ocr_model = None  # Lazy-loaded PaddleOCR instance

    def _get_ocr_model(self):
        """Lazy-load PaddleOCR model (loaded once, reused across calls)."""
        if self._ocr_model is None:
            from paddleocr import PaddleOCR
            logger.debug("PaddleOCR model loading...")
            t0 = time.perf_counter()
            self._ocr_model = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            elapsed = time.perf_counter() - t0
            logger.info("PaddleOCR model loaded (%.3fs)", elapsed)
        return self._ocr_model

    def extract(self, ad: AdMeta, media: MediaResult) -> list[FrameOCR]:
        """Extract OCR texts from sampled frames.

        Returns a list of FrameOCR, one per sampled frame.
        Falls back to mock_ocr_texts when OCR is disabled or PaddleOCR unavailable.
        """
        logger.debug("L2OCR.extract: ad_id=%s, enable_ocr=%s, frame_count=%d", ad.ad_id, self.runtime.enable_ocr, len(media.sampled_frames))

        use_real_ocr = self.runtime.enable_ocr and _check_paddleocr()

        if not use_real_ocr:
            results = self._mock_from_ad(ad, media)
            logger.info("L2OCR done: mode=%s, frames_processed=%d, total_texts=%d", "mock", len(results), sum(len(r.texts) for r in results))
            return results

        # Real OCR mode: run PaddleOCR on each sampled frame
        if media.mock or not media.sampled_frames:
            results = self._mock_from_ad(ad, media)
            logger.info("L2OCR done: mode=%s, frames_processed=%d, total_texts=%d", "mock", len(results), sum(len(r.texts) for r in results))
            return results

        results: list[FrameOCR] = []
        ocr_model = self._get_ocr_model()

        for frame_ref in media.sampled_frames:
            try:
                t0 = time.perf_counter()
                ocr_result = ocr_model.ocr(frame_ref.frame_path, cls=True)
                texts = []
                if ocr_result and ocr_result[0]:
                    for line in ocr_result[0]:
                        if line and len(line) >= 2:
                            text_content = line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1])
                            texts.append(text_content)
                elapsed = time.perf_counter() - t0
                logger.debug("OCR frame %s: %d texts found (%.3fs)", frame_ref.frame_id, len(texts), elapsed)
                results.append(FrameOCR(frame_id=frame_ref.frame_id, texts=texts))
            except Exception as e:
                logger.warning("OCR failed on %s: %s", frame_ref.frame_id, e)
                results.append(FrameOCR(frame_id=frame_ref.frame_id, texts=[]))

        logger.info("L2OCR done: mode=%s, frames_processed=%d, total_texts=%d", "real", len(results), sum(len(r.texts) for r in results))
        return results

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
