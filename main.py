"""Ad Review Demo CLI: layered ad content review system."""
from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("ad_review")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ad-review-demo", description="广告内容审核分层决策系统")
    sub = p.add_subparsers(dest="command", required=True)

    p_review = sub.add_parser("review", help="对单条广告执行主链路审核")
    p_review.add_argument("--meta", required=True, type=str, help="广告 JSON 文件路径")

    p_appeal = sub.add_parser("appeal", help="对单条申诉执行 L5 复核")
    p_appeal.add_argument("--appeal", required=True, type=str, help="申诉 JSON 文件路径")

    p_optimize = sub.add_parser("optimize", help="对优化日志执行 L5 策略分析")
    p_optimize.add_argument("--logs", required=True, type=str, help="优化日志 JSON 文件路径")

    return p


def run_review(meta_path: Path, config_dir: Path, output_root: Path) -> int:
    from modules.agent_client import AgentClient
    from modules.config_loader import load_all_configs
    from modules.l1_history_recall import L1Recall
    from modules.l2_asr import L2ASR
    from modules.l2_ocr import L2OCR
    from modules.l2_qr import L2QR
    from modules.l2_rule_engine import L2RuleEngine
    from modules.l3_consistency import L3Consistency
    from modules.l3_risk_fusion import L3RiskFusion
    from modules.l3_text_embedding import L3TextEmbedding
    from modules.l4_agent_review import L4AgentReview
    from modules.media_preprocess import MediaPreprocessor
    from modules.report_writer import ReportWriter
    from modules.schemas import AdMeta, Decision

    # Load configs
    runtime, thresholds, keywords, category_rules = load_all_configs(config_dir)

    # Parse ad meta
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    ad = AdMeta(**raw)

    # Initialize modules
    writer = ReportWriter(output_root)
    preprocessor = MediaPreprocessor(runtime, output_root / "cache")
    l1 = L1Recall(Path("data/history_fingerprints.json"), thresholds)
    l2_ocr = L2OCR(runtime)
    l2_asr = L2ASR(runtime)
    l2_qr = L2QR(runtime)
    l2_engine = L2RuleEngine(keywords, category_rules, thresholds)
    l3_consistency = L3Consistency()
    l3_embedding = L3TextEmbedding(runtime)
    l3_fusion = L3RiskFusion(thresholds)
    agent = AgentClient(runtime)
    l4 = L4AgentReview(agent, thresholds, Path("data/policy_docs.json"), Path("data/history_cases.json"))

    # --- Pipeline ---
    layers: list[dict] = []

    # Media preprocessing
    media = preprocessor.process(ad)
    writer.print_media({
        "mock": media.mock,
        "frame_count": len(media.sampled_frames),
        "audio_path": media.audio_path,
    })

    # L1
    l1_result = l1.recall(media)
    writer.print_layer("L1Recall", l1_result)
    layers.append(l1_result.model_dump())
    if l1_result.decision in (Decision.APPROVE, Decision.REJECT):
        summary = {"ad_id": ad.ad_id, "final_decision": l1_result.decision.value, "terminated_at": "L1", "layers": layers}
        out = writer.write_review(ad.ad_id, summary)
        writer.print_done(l1_result.decision.value, out)
        return 0

    # L2
    ocr_results = l2_ocr.extract(ad, media)
    asr_result = l2_asr.transcribe(ad, media)
    qr_results = l2_qr.detect(media)

    from modules.l2_rule_engine import FrameOCR as L2FrameOCR, ASRResult as L2ASRResult, QRHit as L2QRHit
    ocr_for_l2 = [L2FrameOCR(frame_id=o.frame_id, texts=o.texts) for o in ocr_results]
    asr_for_l2 = L2ASRResult(text=asr_result.text, mock=asr_result.mock, fallback_reason=asr_result.fallback_reason)
    qr_for_l2 = [L2QRHit(frame_id=q.frame_id, decoded_text=q.decoded_text, is_private_drainage=q.is_private_drainage) for q in qr_results]

    l2_result = l2_engine.evaluate(ad, ocr_for_l2, asr_for_l2, qr_for_l2)
    writer.print_layer("L2RuleEngine", l2_result)
    layers.append(l2_result.model_dump())
    if l2_result.decision in (Decision.APPROVE, Decision.REJECT):
        summary = {"ad_id": ad.ad_id, "final_decision": l2_result.decision.value, "terminated_at": "L2", "layers": layers}
        out = writer.write_review(ad.ad_id, summary)
        writer.print_done(l2_result.decision.value, out)
        return 0

    # L3
    # Build ad_claim_text
    ocr_texts = []
    for o in ocr_results:
        ocr_texts.extend(o.texts)
    ad_claim_text = " ".join(filter(None, [ad.title, ad.description] + ocr_texts + [asr_result.text]))

    consistency_result = l3_consistency.check(ad, ad_claim_text, l2_result.signals)
    embedding_result = l3_embedding.similarity(ad_claim_text, ad.landing_page.text)
    l3_result = l3_fusion.fuse(ad, l1_result, l2_result, consistency_result, embedding_result)
    writer.print_layer("L3RiskFusion", l3_result)
    layers.append(l3_result.model_dump())
    if l3_result.decision in (Decision.APPROVE, Decision.REJECT):
        summary = {"ad_id": ad.ad_id, "final_decision": l3_result.decision.value, "terminated_at": "L3", "layers": layers}
        out = writer.write_review(ad.ad_id, summary)
        writer.print_done(l3_result.decision.value, out)
        return 0

    # L4 (only if AGENT_REVIEW)
    l4_result = l4.review(ad, l1_result, l2_result, l3_result, media)
    writer.print_layer("L4AgentReview", l4_result)
    layers.append(l4_result.model_dump())
    summary = {"ad_id": ad.ad_id, "final_decision": l4_result.decision.value, "terminated_at": "L4", "layers": layers}
    out = writer.write_review(ad.ad_id, summary)
    writer.print_done(l4_result.decision.value, out)
    return 0


def run_appeal(appeal_path: Path, config_dir: Path, output_root: Path) -> int:
    from modules.agent_client import AgentClient
    from modules.config_loader import load_all_configs
    from modules.l5_appeal_agent import L5AppealAgent
    from modules.report_writer import ReportWriter

    runtime, _, _, _ = load_all_configs(config_dir)
    agent = AgentClient(runtime)
    appeal_agent = L5AppealAgent(agent, Path("data/policy_docs.json"))
    writer = ReportWriter(output_root)

    appeal_data = json.loads(appeal_path.read_text(encoding="utf-8"))
    appeal_id = appeal_data.get("appeal_id", "unknown")
    ad_id = appeal_data.get("ad_id", "")

    # Try to load original review result
    original = None
    original_path = output_root / f"review_result_{ad_id}.json"
    if original_path.exists():
        original = json.loads(original_path.read_text(encoding="utf-8"))

    result = appeal_agent.review_appeal(appeal_data, original)
    print(f"[L5AppealAgent] appeal_id={appeal_id} suggestion={result.appeal_suggestion} confidence={result.confidence:.2f}")
    print(f"  reason: {result.reason}")
    if result.required_extra_materials:
        print(f"  required_materials: {result.required_extra_materials}")

    out = writer.write_appeal(appeal_id, result)
    print(f"[Done] output={out}")
    return 0


def run_optimize(logs_path: Path, config_dir: Path, output_root: Path) -> int:
    from modules.agent_client import AgentClient
    from modules.config_loader import load_all_configs
    from modules.l5_strategy_agent import L5StrategyAgent
    from modules.report_writer import ReportWriter

    runtime, _, _, _ = load_all_configs(config_dir)
    agent = AgentClient(runtime)
    strategy_agent = L5StrategyAgent(agent)
    writer = ReportWriter(output_root)

    logs = json.loads(logs_path.read_text(encoding="utf-8"))
    result = strategy_agent.analyze(logs)

    print(f"[L5StrategyAgent] target={result.optimization_target}")
    print(f"  problem: {result.problem}")
    for s in result.suggestions:
        print(f"  suggestion: action={s.action} route={s.route} words={s.words[:5]}...")
    print(f"  requires_human_approval={result.requires_human_approval}")

    out = writer.write_strategy(result)
    # Write candidate keywords
    candidate_path = output_root / "candidate_keywords.yaml"
    strategy_agent.write_candidate_keywords(result.suggestions, candidate_path)
    print(f"[Done] output={out}")
    print(f"[Done] candidate_keywords={candidate_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 2

    config_dir = Path("config")
    output_root = Path("outputs")
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        if args.command == "review":
            meta_path = Path(args.meta)
            if not meta_path.exists():
                print(f"ERROR: input file not found: {meta_path}", file=sys.stderr)
                return 2
            return run_review(meta_path, config_dir, output_root)

        elif args.command == "appeal":
            appeal_path = Path(args.appeal)
            if not appeal_path.exists():
                print(f"ERROR: input file not found: {appeal_path}", file=sys.stderr)
                return 2
            return run_appeal(appeal_path, config_dir, output_root)

        elif args.command == "optimize":
            logs_path = Path(args.logs)
            if not logs_path.exists():
                print(f"ERROR: input file not found: {logs_path}", file=sys.stderr)
                return 2
            return run_optimize(logs_path, config_dir, output_root)

    except FileNotFoundError as e:
        print(f"ERROR: file not found: {e}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}", file=sys.stderr)
        return 2
    except ValidationError as e:
        print(f"ERROR: input validation failed: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        try:
            print(f"ERROR: unexpected: {e}", file=sys.stderr)
        except OSError:
            pass
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
