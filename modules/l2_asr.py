"""L2 ASR module: faster-whisper transcription with graceful fallback to mock."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from modules.schemas import AdMeta, MediaResult, RuntimeConfig
from modules.utils import is_cuda_available

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised when configuration is invalid and cannot be resolved."""
    pass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ASRResult:
    text: str
    mock: bool = False
    fallback_reason: str | None = None


# ---------------------------------------------------------------------------
# L2ASR class
# ---------------------------------------------------------------------------


class L2ASR:
    """L2 ASR transcriber: uses faster-whisper when available, otherwise mock."""

    def __init__(self, runtime: RuntimeConfig) -> None:
        self.runtime = runtime

    def transcribe(self, ad: AdMeta, media: MediaResult) -> ASRResult:
        """Transcribe audio from media. Falls back to mock_asr_text on failure."""
        # Guard: ASR disabled
        if not self.runtime.enable_asr:
            return ASRResult(
                text=ad.mock_asr_text,
                mock=True,
                fallback_reason="disabled",
            )

        # Guard: no audio available
        if media.mock or media.audio_path is None:
            return ASRResult(
                text=ad.mock_asr_text,
                mock=True,
                fallback_reason="no_audio",
            )

        # Resolve device
        try:
            device, compute_type = self._resolve_device()
        except ConfigError as e:
            logger.error("ASR device resolution failed: %s", e)
            raise

        # Attempt real transcription
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(
                self.runtime.asr_model_size,
                device=device,
                compute_type=compute_type,
            )
            segments, _ = model.transcribe(media.audio_path)
            text = " ".join(seg.text for seg in segments)
            return ASRResult(text=text, mock=False)
        except Exception as e:  # noqa: BLE001
            logger.warning("faster-whisper transcription failed: %s", e)
            return ASRResult(
                text=ad.mock_asr_text,
                mock=True,
                fallback_reason=f"model_error:{e}",
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_device(self) -> tuple[str, str]:
        """Resolve ASR device and compute type based on runtime config.

        Returns:
            Tuple of (device, compute_type).

        Raises:
            ConfigError: If asr_device=cuda but CUDA is not available.
        """
        cfg = self.runtime.asr_device

        if cfg == "cuda":
            if not is_cuda_available():
                raise ConfigError("asr_device=cuda but CUDA not available")
            return "cuda", "float16"

        if cfg == "cpu":
            return "cpu", "int8"

        # auto mode
        if is_cuda_available():
            return "cuda", "float16"
        return "cpu", "int8"
