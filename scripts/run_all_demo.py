#!/usr/bin/env python3
"""
傻瓜式脚本：一键跑通所有 demo 样例，验证每个环节是否真实运行

用法: python scripts/run_all_demo.py

会依次执行：
1. 所有 samples/real_*.json 的 review
2. 所有 samples/appeal_*.json 的 appeal
3. optimization_logs 的 optimize
4. 打印汇总报告
"""
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def run(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(
        [sys.executable] + cmd,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(PROJECT_ROOT),
    )
    return r.returncode, r.stdout, r.stderr


def main():
    print("=" * 60)
    print("广告审核分层决策系统 - 全量 Demo 验证")
    print("=" * 60)

    results = []

    # 1. Review all ad samples
    samples_dir = PROJECT_ROOT / "samples"
    ad_files = sorted(samples_dir.glob("*.json"))
    ad_files = [f for f in ad_files if not f.name.startswith("appeal")]

    print(f"\n📋 找到 {len(ad_files)} 条广告样例")
    print("-" * 60)

    for ad_file in ad_files:
        code, stdout, stderr = run(["main.py", "review", "--meta", str(ad_file)])
        # Extract key info
        lines = stdout.strip().split("\n")
        media_line = next((l for l in lines if "[MediaPreprocessor]" in l), "")
        done_line = next((l for l in lines if "[Done]" in l), "")

        is_mock = "mock=True" in media_line
        final = "?"
        terminated = "?"
        if "final_decision=" in done_line:
            final = done_line.split("final_decision=")[1].split()[0]

        # Read output JSON for terminated_at
        output_json = PROJECT_ROOT / "outputs" / f"review_result_{ad_file.stem}.json"
        if output_json.exists():
            data = json.loads(output_json.read_text())
            terminated = data.get("terminated_at", "?")

        status = "✓" if code == 0 else "✗"
        mock_tag = "🎭 mock" if is_mock else "🎬 真实"
        results.append({
            "file": ad_file.name,
            "status": status,
            "mock": is_mock,
            "decision": final,
            "terminated_at": terminated,
        })
        print(f"  {status} {ad_file.name:20s} | {mock_tag} | 决策={final:12s} | 终止于={terminated}")

    # 2. Appeal
    print(f"\n📋 申诉复核")
    print("-" * 60)
    appeal_files = sorted(samples_dir.glob("appeal_*.json"))
    for appeal_file in appeal_files:
        code, stdout, stderr = run(["main.py", "appeal", "--appeal", str(appeal_file)])
        status = "✓" if code == 0 else "✗"
        suggestion = "?"
        for line in stdout.split("\n"):
            if "suggestion=" in line:
                suggestion = line.split("suggestion=")[1].split()[0]
        print(f"  {status} {appeal_file.name:20s} | suggestion={suggestion}")

    # 3. Optimize
    print(f"\n📋 策略优化")
    print("-" * 60)
    code, stdout, stderr = run(["main.py", "optimize", "--logs", "data/optimization_logs.json"])
    status = "✓" if code == 0 else "✗"
    print(f"  {status} optimization_logs.json")
    for line in stdout.split("\n"):
        if "suggestion:" in line or "problem:" in line:
            print(f"    {line.strip()}")

    # 4. Summary
    print("\n" + "=" * 60)
    print("📊 汇总")
    print("=" * 60)
    total = len(results)
    mock_count = sum(1 for r in results if r["mock"])
    real_count = total - mock_count
    print(f"  广告总数: {total}")
    print(f"  真实视频: {real_count} 条")
    print(f"  Mock 模式: {mock_count} 条")
    print()

    # Check which layers were hit
    layers_hit = set()
    for r in results:
        layers_hit.add(r["terminated_at"])
    print(f"  覆盖的终止层: {sorted(layers_hit)}")

    decisions = set(r["decision"] for r in results)
    print(f"  覆盖的决策类型: {sorted(decisions)}")

    # Warnings
    print()
    if mock_count == total:
        print("  ⚠️  所有视频都走了 mock！请把真实 .mp4 文件放到 samples/ 目录")
    if "L1" not in layers_hit:
        print("  ⚠️  L1 历史召回未命中任何样例。如需测试 L1，请：")
        print("     1. 运行 python scripts/build_history_fingerprints.py 生成真实指纹")
        print("     2. 用相同视频作为输入测试")
    if real_count > 0 and "APPROVE" not in decisions:
        print("  ⚠️  没有样例被 APPROVE，可能阈值设置过严")


if __name__ == "__main__":
    main()
