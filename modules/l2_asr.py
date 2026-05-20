"""L2 ASR module: faster-whisper transcription with graceful fallback to mock."""

from __future__ import annotations

import logging
import time
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
        """Lazy-load the WhisperModel once, reuse on subsequent calls.
        
        Priority: local model path > HuggingFace download.
        If asr_model_path exists locally, load from there (no network needed).
        """
        if self._model is not None:
            return self._model

        device, compute_type = self._resolve_device()
        self._device = device
        self._compute_type = compute_type

        from faster_whisper import WhisperModel
        from pathlib import Path

        # Determine model source: local path or model name (triggers download)
        model_path = self.runtime.asr_model_path
        if Path(model_path).exists():
            model_source = model_path
            logger.info("Loading faster-whisper from LOCAL path: %s (device=%s, compute=%s)",
                       model_source, device, compute_type)
        else:
            model_source = self.runtime.asr_model_size
            logger.warning("Local model path '%s' not found, falling back to model name '%s' (may download from HuggingFace)",
                          model_path, model_source)

        t0 = time.perf_counter()
        self._model = WhisperModel(
            model_source,
            device=device,
            compute_type=compute_type,
            local_files_only=Path(model_path).exists(),  # 本地存在时禁止联网
        )
        elapsed = time.perf_counter() - t0
        logger.info("faster-whisper model loaded successfully (%.3fs)", elapsed)
        return self._model

    def transcribe(self, ad: AdMeta, media: MediaResult) -> ASRResult:
        """Transcribe audio from media. Falls back to mock_asr_text on failure."""
        logger.debug("L2ASR.transcribe: ad_id=%s, audio_path=%s, enable_asr=%s", ad.ad_id, media.audio_path, self.runtime.enable_asr)

        # Guard: ASR disabled
        if not self.runtime.enable_asr:
            logger.info("ASR fallback to mock: reason=%s", "disabled")
            return ASRResult(
                text=ad.mock_asr_text,
                mock=True,
                fallback_reason="disabled",
            )

        # Guard: no audio available
        if media.mock or media.audio_path is None:
            logger.info("ASR fallback to mock: reason=%s", "no_audio")
            return ASRResult(
                text=ad.mock_asr_text,
                mock=True,
                fallback_reason="no_audio",
            )

        # Resolve device (may raise ConfigError for explicit cuda without CUDA)
        try:
            device, compute_type = self._resolve_device()
            logger.debug("ASR device resolved: device=%s, compute_type=%s", device, compute_type)
        except ConfigError as e:
            logger.error("ASR device resolution failed: %s", e)
            raise

        # Attempt real transcription with cached model
        try:
            t_model_start = time.perf_counter()
            model = self._get_model()
            t_model_end = time.perf_counter()
            logger.debug("ASR model get: %.3fs (cached=%s)", t_model_end - t_model_start, self._model is not None)

            logger.debug("ASR transcribe start: audio=%s", media.audio_path)
            t_transcribe_start = time.perf_counter()
            segments, info = model.transcribe(media.audio_path)
            text_parts = []
            for seg in segments:
                text_parts.append(seg.text)
            text = " ".join(text_parts)
            t_transcribe_end = time.perf_counter()

            logger.info(
                "ASR transcribe done: device=%s, compute=%s, model_load=%.3fs, inference=%.3fs, text_len=%d chars",
                self._device, self._compute_type,
                t_model_end - t_model_start,
                t_transcribe_end - t_transcribe_start,
                len(text),
            )
            return ASRResult(text=text, mock=False)
        except ConfigError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("faster-whisper transcription failed: %s", e)
            logger.info("ASR fallback to mock: reason=%s", f"model_error:{e}")
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
