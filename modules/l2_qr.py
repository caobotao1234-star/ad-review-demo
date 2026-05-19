"""L2 QR module: QR code detection and private domain drainage identification."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import cv2

from modules.schemas import MediaResult, RuntimeConfig
from modules.utils import normalize_text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class QRHit:
    frame_id: str
    decoded_text: str
    is_private_drainage: bool = False


# ---------------------------------------------------------------------------
# L2QR class
# ---------------------------------------------------------------------------


class L2QR:
    """L2 QR detector: detects QR codes in sampled frames and flags private drainage."""

    def __init__(self, runtime: RuntimeConfig) -> None:
        self.runtime = runtime

    def detect(self, media: MediaResult) -> list[QRHit]:
        """Detect QR codes in all sampled frames.

        Returns a list of QRHit for each successfully decoded QR code.
        Returns empty list if QR detection is disabled or media is mock.
        """
        if not self.runtime.enable_qr or media.mock:
            return []

        detector = cv2.QRCodeDetector()
        hits: list[QRHit] = []

        for frame_ref in media.sampled_frames:
            img = cv2.imread(frame_ref.frame_path)
            if img is None:
                logger.warning("Cannot read frame image: %s", frame_ref.frame_path)
                continue

            try:
                decoded, points, _ = detector.detectAndDecode(img)
                if decoded:
                    hits.append(QRHit(
                        frame_id=frame_ref.frame_id,
                        decoded_text=decoded,
                        is_private_drainage=self._is_private_drainage(decoded),
                    ))
            except Exception as e:  # noqa: BLE001
                logger.warning("QR detection failed on %s: %s", frame_ref.frame_id, e)

        return hits

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _is_private_drainage(text: str) -> bool:
        """Determine if decoded QR text indicates private domain drainage.

        Checks for:
        - WeChat-related keywords (微信, vx, wechat)
        - Phone number pattern (1[3-9]\\d{9})
        - HTTP links
        """
        norm = normalize_text(text)
        # WeChat keywords
        if any(kw in norm for kw in ["微信", "vx", "wechat"]):
            return True
        # Phone number
        if re.search(r"1[3-9]\d{9}", norm):
            return True
        # HTTP link
        if norm.startswith("http"):
            return True
        return False
