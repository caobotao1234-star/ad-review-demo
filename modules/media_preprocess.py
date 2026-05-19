"""Media preprocessing module: frame sampling, pHash fingerprinting, and audio extraction."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image

from modules.schemas import AdMeta, FrameRef, MediaResult, RuntimeConfig, VideoFingerprint
from modules.utils import compute_file_md5, ensure_dir, hamming_distance, is_ffmpeg_available, safe_filename

logger = logging.getLogger(__name__)


class MediaPreprocessor:
    """One-shot media preprocessor: frame sampling, pHash, ffmpeg audio extraction."""

    def __init__(self, runtime: RuntimeConfig, cache_root: Path) -> None:
        self.runtime = runtime
        self.cache_root = cache_root

    def process(self, ad: AdMeta) -> MediaResult:
        """Process a single ad's media file and return a MediaResult."""
        logger.debug("MediaPreprocessor.process: ad_id=%s, media_path=%s", ad.ad_id, ad.media_path)
        t_start = time.perf_counter()

        # --- Guard: missing media ---
        if not ad.media_path or not Path(ad.media_path).exists():
            logger.warning("media_path %s missing, returning mock MediaResult", ad.media_path)
            return MediaResult(ad_id=ad.ad_id, mock=True, fallback_reason="media_missing")

        media_path = Path(ad.media_path)
        ad_dir = ensure_dir(self.cache_root / safe_filename(ad.ad_id))
        frames_dir = ensure_dir(ad_dir / "frames")

        # --- Open video ---
        cap = cv2.VideoCapture(str(media_path))
        if not cap.isOpened():
            logger.warning("Cannot open video %s, returning mock MediaResult", media_path)
            return MediaResult(ad_id=ad.ad_id, mock=True, fallback_reason="decode_error")

        try:
            return self._process_video(ad, cap, media_path, frames_dir, ad_dir, t_start)
        except Exception as e:
            logger.error("Video decode error for %s: %s", ad.ad_id, e)
            return MediaResult(ad_id=ad.ad_id, mock=True, fallback_reason="decode_error")
        finally:
            cap.release()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process_video(
        self,
        ad: AdMeta,
        cap: cv2.VideoCapture,
        media_path: Path,
        frames_dir: Path,
        ad_dir: Path,
        t_start: float,
    ) -> MediaResult:
        t_md5_start = time.perf_counter()
        file_md5 = compute_file_md5(media_path)
        md5_time = time.perf_counter() - t_md5_start
        logger.debug("File MD5 computed: %s (%.3fs)", file_md5, md5_time)

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration_sec = frame_count / fps if fps > 0 else 0.0
        logger.debug("Video opened: fps=%.1f, frames=%d, resolution=%dx%d, duration=%.1fs", fps, frame_count, width, height, duration_sec)

        # --- Collect candidate frame indices ---
        candidate_indices: list[int] = []
        # First frame
        candidate_indices.append(0)
        # Last frame
        last_idx = max(frame_count - 1, 0)
        if last_idx > 0:
            candidate_indices.append(last_idx)
        # Fixed interval frames
        step = max(int(self.runtime.sample_interval_sec * fps), 1)
        for idx in range(step, frame_count - 1, step):
            if idx not in candidate_indices:
                candidate_indices.append(idx)

        candidate_indices = sorted(set(candidate_indices))

        # --- Read frames ---
        raw_frames: list[tuple[int, np.ndarray]] = []
        for idx in candidate_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret and frame is not None:
                raw_frames.append((idx, frame))

        # --- Scene change detection (histogram diff) ---
        scene_frames: list[tuple[int, np.ndarray]] = []
        for i in range(1, len(raw_frames)):
            diff = self._hist_diff(raw_frames[i - 1][1], raw_frames[i][1])
            if diff > 0.4:
                scene_frames.append(raw_frames[i])

        # Merge scene frames into raw_frames (deduplicate by index)
        existing_indices = {idx for idx, _ in raw_frames}
        for idx, frame in scene_frames:
            if idx not in existing_indices:
                raw_frames.append((idx, frame))
                existing_indices.add(idx)
        raw_frames.sort(key=lambda x: x[0])

        # --- Compute pHash for each frame ---
        resize = self.runtime.phash_resize
        frame_phashes: list[tuple[int, np.ndarray, str]] = []
        for idx, frame in raw_frames:
            phash_hex = self._compute_phash(frame, resize)
            frame_phashes.append((idx, frame, phash_hex))

        # --- Deduplicate by pHash hamming distance <= 4 ---
        kept_before_limit: list[tuple[int, np.ndarray, str]] = []
        for idx, frame, phash_hex in frame_phashes:
            if all(hamming_distance(phash_hex, k_phash) > 4 for _, _, k_phash in kept_before_limit):
                kept_before_limit.append((idx, frame, phash_hex))

        # --- Limit to max_sampled_frames (uniform downsample if exceeded) ---
        max_frames = self.runtime.max_sampled_frames
        kept = list(kept_before_limit)
        if len(kept) > max_frames:
            indices = np.linspace(0, len(kept) - 1, max_frames, dtype=int)
            kept = [kept[i] for i in indices]

        logger.debug("Frame sampling: candidates=%d, after_scene=%d, after_dedup=%d, final=%d", len(candidate_indices), len(raw_frames), len(kept_before_limit), len(kept))
        logger.debug("pHash computed for %d frames (resize=%d)", len(kept), resize)

        # --- Save frames and build FrameRef list ---
        sampled_frames: list[FrameRef] = []
        phash_list: list[str] = []
        for seq, (idx, frame, phash_hex) in enumerate(kept):
            frame_filename = f"frame_{seq:04d}.jpg"
            frame_path = frames_dir / frame_filename
            cv2.imwrite(str(frame_path), frame)
            timestamp = idx / fps if fps > 0 else 0.0
            sampled_frames.append(
                FrameRef(
                    frame_id=f"frame_{seq:04d}",
                    frame_path=str(frame_path),
                    timestamp_sec=round(timestamp, 3),
                )
            )
            phash_list.append(phash_hex)

        fingerprint = VideoFingerprint(phash_list=phash_list, frame_count=len(kept))

        # --- Audio extraction ---
        audio_out = ad_dir / "audio.wav"
        logger.debug("ffmpeg audio extraction: input=%s, output=%s", media_path, audio_out)
        audio_path = self._extract_audio(media_path, audio_out)
        logger.debug("ffmpeg done: success=%s, audio_path=%s", audio_path is not None, audio_path)

        t_end = time.perf_counter()
        logger.info("MediaPreprocessor done: ad_id=%s, mock=%s, frames=%d, md5=%s, audio=%s, took=%.3fs",
                    ad.ad_id, False, len(kept), file_md5, audio_path is not None, t_end - t_start)

        return MediaResult(
            ad_id=ad.ad_id,
            mock=False,
            file_md5=file_md5,
            duration_sec=round(duration_sec, 3),
            fps=round(fps, 2),
            width=width,
            height=height,
            sampled_frames=sampled_frames,
            fingerprint=fingerprint,
            audio_path=str(audio_path) if audio_path else None,
        )

    def _compute_phash(self, frame: np.ndarray, resize: int) -> str:
        """Resize frame and compute perceptual hash as hex string."""
        resized = cv2.resize(frame, (resize, resize))
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        pil_img = Image.fromarray(gray)
        return str(imagehash.phash(pil_img))

    def _hist_diff(self, frame_a: np.ndarray, frame_b: np.ndarray) -> float:
        """Compute normalized grayscale histogram difference between two frames."""
        gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
        gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
        hist_a = cv2.calcHist([gray_a], [0], None, [256], [0, 256])
        hist_b = cv2.calcHist([gray_b], [0], None, [256], [0, 256])
        cv2.normalize(hist_a, hist_a)
        cv2.normalize(hist_b, hist_b)
        # compareHist returns 0..1 for correlation; we want difference
        score = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
        return 1.0 - score  # higher = more different

    def _extract_audio(self, media_path: Path, audio_out: Path) -> Path | None:
        """Extract audio via ffmpeg. Returns None if unavailable or fails."""
        if not is_ffmpeg_available():
            logger.warning("ffmpeg not available, skip audio extraction")
            return None
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(media_path),
                    "-vn", "-ac", "1", "-ar", "16000",
                    str(audio_out),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            return audio_out
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("ffmpeg audio extraction failed: %s", e)
            return None
