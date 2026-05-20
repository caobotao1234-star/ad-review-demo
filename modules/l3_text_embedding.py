"""L3 Text Embedding: semantic similarity between ad claim and landing page text."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from modules.schemas import RuntimeConfig

logger = logging.getLogger(__name__)


@dataclass
class SimilarityResult:
    score: float
    backend: str  # "sbert" | "token_overlap"


def _token_overlap(a: str, b: str) -> float:
    """Character-level Jaccard similarity (each character is a token)."""
    ta = set(a)
    tb = set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class L3TextEmbedding:
    """Compute semantic similarity between ad claim text and landing page text."""

    def __init__(self, runtime: RuntimeConfig) -> None:
        self.runtime = runtime
        self._sbert_model = None
        self._sbert_available = self._check_sbert()

    def _check_sbert(self) -> bool:
        """Check if sentence-transformers is importable."""
        if not self.runtime.enable_text_embedding:
            return False
        try:
            import sentence_transformers  # noqa: F401
            return True
        except ImportError:
            logger.warning("sentence-transformers not available, will use token_overlap fallback")
            return False

    def _get_sbert_model(self):
        """Lazy-load the sbert model from local path (no network needed if exists)."""
        if self._sbert_model is None:
            from sentence_transformers import SentenceTransformer
            from pathlib import Path

            model_path = self.runtime.embedding_model_path
            use_local = Path(model_path).exists()

            if use_local:
                logger.info("Loading SBERT from LOCAL path: %s", model_path)
                source = model_path
            else:
                source = "paraphrase-multilingual-MiniLM-L12-v2"
                logger.warning("Local embedding model '%s' not found, will download from HuggingFace", model_path)

            logger.debug("SBERT model loading...")
            t0 = time.perf_counter()
            self._sbert_model = SentenceTransformer(source)
            elapsed = time.perf_counter() - t0
            logger.info("SBERT model loaded (%.3fs)", elapsed)
        return self._sbert_model

    def similarity(self, ad_claim: str, landing_text: str) -> SimilarityResult:
        """Compute similarity between ad_claim and landing_text."""
        backend = "sbert" if (self.runtime.enable_text_embedding and self._sbert_available) else "token_overlap"
        logger.debug("L3TextEmbedding.similarity: claim_len=%d, landing_len=%d, backend=%s", len(ad_claim), len(landing_text), backend)

        if not self.runtime.enable_text_embedding or not self._sbert_available:
            score = _token_overlap(ad_claim, landing_text)
            logger.info("L3TextEmbedding result: score=%.4f, backend=%s", score, "token_overlap")
            return SimilarityResult(score=score, backend="token_overlap")

        try:
            import numpy as np
            model = self._get_sbert_model()
            embeddings = model.encode([ad_claim, landing_text], normalize_embeddings=True)
            score = float(np.dot(embeddings[0], embeddings[1]))
            logger.info("L3TextEmbedding result: score=%.4f, backend=%s", score, "sbert")
            return SimilarityResult(score=score, backend="sbert")
        except Exception as e:
            logger.warning("sbert similarity failed: %s, falling back to token_overlap", e)
            score = _token_overlap(ad_claim, landing_text)
            logger.info("L3TextEmbedding result: score=%.4f, backend=%s", score, "token_overlap")
            return SimilarityResult(score=score, backend="token_overlap")
