"""Shared test fixtures."""
import os
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def isolate_outputs(tmp_path, monkeypatch):
    """Isolate outputs directory for each test."""
    monkeypatch.chdir(tmp_path)
    # Copy config and data dirs to tmp
    import shutil
    src = Path(__file__).parent.parent
    for d in ["config", "data", "samples"]:
        if (src / d).exists():
            shutil.copytree(src / d, tmp_path / d)
    (tmp_path / "outputs").mkdir(exist_ok=True)


@pytest.fixture
def no_gpu(monkeypatch):
    monkeypatch.setattr("modules.utils.is_cuda_available", lambda: False)


@pytest.fixture
def no_ffmpeg(monkeypatch):
    monkeypatch.setattr("modules.utils.is_ffmpeg_available", lambda: False)


@pytest.fixture
def no_llm_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
