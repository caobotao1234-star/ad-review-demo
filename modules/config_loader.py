"""Configuration loading layer for the ad-review-layered-decision system.

Each loader function reads a YAML file via load_yaml_with_default, constructs
the corresponding pydantic model, and falls back to built-in defaults on any
validation error — logging an ERROR with file path and exception summary but
never blocking the process.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import ValidationError

from modules.schemas import (
    CategoryRulesConfig,
    KeywordsConfig,
    RuntimeConfig,
    Thresholds,
)
from modules.utils import load_yaml_with_default

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in defaults (empty dicts let pydantic use field defaults)
# ---------------------------------------------------------------------------

_RUNTIME_DEFAULT: dict = {}
_THRESHOLDS_DEFAULT: dict = {}
_KEYWORDS_DEFAULT: dict = {"hard_block": [], "normalized_block": [], "suspicious_slang": []}
_CATEGORY_RULES_DEFAULT: dict = {"rules": []}


# ---------------------------------------------------------------------------
# Individual loaders
# ---------------------------------------------------------------------------


def load_runtime_config(path: Path) -> RuntimeConfig:
    """Load RuntimeConfig from a YAML file, falling back to defaults on error."""
    raw = load_yaml_with_default(path, _RUNTIME_DEFAULT)
    try:
        return RuntimeConfig(**raw)
    except (ValidationError, TypeError) as e:
        logger.error(
            "RuntimeConfig validation failed for %s (%s), using built-in defaults",
            path,
            _summarize_error(e),
        )
        return RuntimeConfig()


def load_thresholds(path: Path) -> Thresholds:
    """Load Thresholds from a YAML file, falling back to defaults on error."""
    raw = load_yaml_with_default(path, _THRESHOLDS_DEFAULT)
    try:
        return Thresholds(**raw)
    except (ValidationError, TypeError) as e:
        logger.error(
            "Thresholds validation failed for %s (%s), using built-in defaults",
            path,
            _summarize_error(e),
        )
        return Thresholds()


def load_keywords(path: Path) -> KeywordsConfig:
    """Load KeywordsConfig from a YAML file, falling back to defaults on error."""
    raw = load_yaml_with_default(path, _KEYWORDS_DEFAULT)
    try:
        return KeywordsConfig(**raw)
    except (ValidationError, TypeError) as e:
        logger.error(
            "KeywordsConfig validation failed for %s (%s), using built-in defaults",
            path,
            _summarize_error(e),
        )
        return KeywordsConfig()


def load_category_rules(path: Path) -> CategoryRulesConfig:
    """Load CategoryRulesConfig from a YAML file, falling back to defaults on error."""
    raw = load_yaml_with_default(path, _CATEGORY_RULES_DEFAULT)
    try:
        return CategoryRulesConfig(**raw)
    except (ValidationError, TypeError) as e:
        logger.error(
            "CategoryRulesConfig validation failed for %s (%s), using built-in defaults",
            path,
            _summarize_error(e),
        )
        return CategoryRulesConfig()


# ---------------------------------------------------------------------------
# One-stop loader
# ---------------------------------------------------------------------------


def load_all_configs(
    config_dir: Path,
) -> tuple[RuntimeConfig, Thresholds, KeywordsConfig, CategoryRulesConfig]:
    """Load all four configuration files from *config_dir* in order.

    Returns a tuple of (RuntimeConfig, Thresholds, KeywordsConfig, CategoryRulesConfig).
    Each config that fails to load is replaced by its built-in default without
    blocking the process.
    """
    runtime = load_runtime_config(config_dir / "runtime.yaml")
    thresholds = load_thresholds(config_dir / "thresholds.yaml")
    keywords = load_keywords(config_dir / "keywords.yaml")
    category_rules = load_category_rules(config_dir / "category_rules.yaml")
    return runtime, thresholds, keywords, category_rules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summarize_error(e: Exception) -> str:
    """Return a short one-line summary of an exception for log messages."""
    msg = str(e)
    # Truncate very long validation error messages
    if len(msg) > 200:
        msg = msg[:200] + "..."
    # Collapse newlines for single-line log output
    return msg.replace("\n", " | ")
