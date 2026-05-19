"""L3 Text Embedding: semantic similarity between ad claim and landing page text."""

from __future__ import annotations

import logging
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
        """Lazy-load the sbert model."""
        if self._sbert_model is None:
            from sentence_transformers import SentenceTransformer
            self._sbert_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        return self._sbert_model

    def similarity(self, ad_claim: str, landing_text: str) -> SimilarityResult:
        """Compute similarity between ad_claim and landing_text."""
        if not self.runtime.enable_text_embedding or not self._sbert_available:
            score = _token_overlap(ad_claim, landing_text)
            return SimilarityResult(score=score, backend="token_overlap")

        try:
            import numpy as np
            model = self._get_sbert_model()
            embeddings = model.encode([ad_claim, landing_text], normalize_embeddings=True)
            score = float(np.dot(embeddings[0], embeddings[1]))
            return SimilarityResult(score=score, backend="sbert")
        except Exception as e:
            logger.warning("sbert similarity failed: %s, falling back to token_overlap", e)
            score = _token_overlap(ad_claim, landing_text)
            return SimilarityResult(score=score, backend="token_overlap")
