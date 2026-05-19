"""CLI integration tests covering review/appeal/optimize commands."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def run_cli(*args):
    """Run main.py with given args and return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py")] + list(args),
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(PROJECT_ROOT),
    )


class TestReview:
    def test_review_ad_003_approve(self):
        r = run_cli("review", "--meta", "samples/ad_003.json")
        assert r.returncode == 0
        assert "APPROVE" in r.stdout
        assert Path(PROJECT_ROOT / "outputs/review_result_ad_003.json").exists()

    def test_review_ad_002_reject_at_l2(self):
        r = run_cli("review", "--meta", "samples/ad_002.json")
        assert r.returncode == 0
        assert "REJECT" in r.stdout
        result = json.loads((PROJECT_ROOT / "outputs/review_result_ad_002.json").read_text())
        assert result["terminated_at"] == "L2"

    def test_review_ad_001_enters_l4(self):
        r = run_cli("review", "--meta", "samples/ad_001.json")
        assert r.returncode == 0
        assert "L4AgentReview" in r.stdout

    def test_review_ad_004_reject(self):
        r = run_cli("review", "--meta", "samples/ad_004.json")
        assert r.returncode == 0
        assert "REJECT" in r.stdout


class TestAppeal:
    def test_appeal_001(self):
        # First run review to generate original result
        run_cli("review", "--meta", "samples/ad_001.json")
        r = run_cli("appeal", "--appeal", "samples/appeal_001.json")
        assert r.returncode == 0
        assert "appeal_001" in r.stdout
        assert Path(PROJECT_ROOT / "outputs/appeal_result_appeal_001.json").exists()


class TestOptimize:
    def test_optimize(self):
        r = run_cli("optimize", "--logs", "data/optimization_logs.json")
        assert r.returncode == 0
        assert "L5StrategyAgent" in r.stdout
        assert Path(PROJECT_ROOT / "outputs/strategy_suggestion.json").exists()
        assert Path(PROJECT_ROOT / "outputs/candidate_keywords.yaml").exists()


class TestErrors:
    def test_meta_not_found_exit_2(self):
        r = run_cli("review", "--meta", "nonexistent.json")
        assert r.returncode == 2

    def test_invalid_json_exit_2(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        r = run_cli("review", "--meta", str(bad))
        assert r.returncode == 2

    def test_appeal_not_found_exit_2(self):
        r = run_cli("appeal", "--appeal", "nonexistent.json")
        assert r.returncode == 2

    def test_optimize_not_found_exit_2(self):
        r = run_cli("optimize", "--logs", "nonexistent.json")
        assert r.returncode == 2
