"""ReportWriter: console output and JSON file writing."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from modules.schemas import AppealResult, LayerResult, StrategyResult
from modules.utils import ensure_dir

logger = logging.getLogger(__name__)


class ReportWriter:
    def __init__(self, output_root: Path) -> None:
        self.output_root = ensure_dir(output_root)

    def print_layer(self, name: str, result: LayerResult) -> None:
        """Print a single layer result to stdout in structured format."""
        parts = [f"[{name}]"]
        parts.append(f"decision={result.decision.value}")
        if result.risk_score:
            parts.append(f"risk_score={result.risk_score}")
        if result.reason:
            parts.append(f"reason={result.reason}")
        print(" ".join(parts))

    def print_media(self, media_info: dict) -> None:
        """Print media preprocessing summary."""
        parts = ["[MediaPreprocessor]"]
        parts.append(f"mock={media_info.get('mock', False)}")
        parts.append(f"frames={media_info.get('frame_count', 0)}")
        if media_info.get("audio_path"):
            parts.append(f"audio={media_info['audio_path']}")
        print(" ".join(parts))

    def print_done(self, final_decision: str, output_path: Path) -> None:
        """Print final summary line."""
        print(f"[Done] final_decision={final_decision} output={output_path}")

    def write_review(self, ad_id: str, summary: dict) -> Path:
        """Write review result JSON."""
        out = self.output_root / f"review_result_{ad_id}.json"
        out.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out

    def write_appeal(self, appeal_id: str, result: AppealResult) -> Path:
        """Write appeal result JSON."""
        out = self.output_root / f"appeal_result_{appeal_id}.json"
        out.write_text(
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out

    def write_strategy(self, result: StrategyResult) -> Path:
        """Write strategy suggestion JSON."""
        out = self.output_root / "strategy_suggestion.json"
        out.write_text(
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out
