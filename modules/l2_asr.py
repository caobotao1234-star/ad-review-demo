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
        self._model = None  # Lazy-loaded, reused across calls
        self._device: str | None = None
        self._compute_type: str | None = None

    def _get_model(self):
        """Lazy-load the WhisperModel once, reuse on subsequent calls."""
        if self._model is not None:
            return self._model

        device, compute_type = self._resolve_device()
        self._device = device
        self._compute_type = compute_type

        from faster_whisper import WhisperModel

        logger.info(
            "Loading faster-whisper model: size=%s device=%s compute=%s",
            self.runtime.asr_model_size, device, compute_type,
        )
        self._model = WhisperModel(
            self.runtime.asr_model_size,
            device=device,
            compute_type=compute_type,
        )
        logger.info("faster-whisper model loaded successfully")
        return self._model

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

        # Resolve device (may raise ConfigError for explicit cuda without CUDA)
        try:
            self._resolve_device()
        except ConfigError as e:
            logger.error("ASR device resolution failed: %s", e)
            raise

        # Attempt real transcription with cached model
        try:
            model = self._get_model()
            segments, _ = model.transcribe(media.audio_path)
            text = " ".join(seg.text for seg in segments)
            return ASRResult(text=text, mock=False)
        except ConfigError:
            raise
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
            return "cuda", self.runtime.asr_compute_type if self.runtime.asr_compute_type != "int8" else "float16"

        if cfg == "cpu":
            return "cpu", "int8"

        # auto mode
        if is_cuda_available():
            # Use configured compute_type, but avoid int8 on GPU (needs sm_89+)
            compute = self.runtime.asr_compute_type
            if compute == "int8":
                compute = "float16"  # int8 only works on 4090/A100+
            return "cuda", compute
        return "cpu", "int8"
