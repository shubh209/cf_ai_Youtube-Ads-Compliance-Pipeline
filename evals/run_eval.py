"""
Golden dataset evaluation for the Brand Guardian compliance pipeline.
Runs each synthetic transcript through the audit pipeline and scores precision/recall.

Usage: PYTHONPATH=. uv run python evals/run_eval.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from src.pipeline.workflow import app as compliance_graph


def run_single(case: dict) -> dict:
    """Run one golden case through the pipeline, return raw result."""
    state = {
        "video_url": f"eval://{case['id']}",
        "video_id": case["id"],
        "transcript": case["transcript"],
        "ocr_text": [],
        "platforms": case["platforms"],
        "audit_mode": "eval",
        "compliance_results": [],
        "errors": [],
    }
    return compliance_graph.invoke(state)


def score(case: dict, result: dict) -> dict:
    """Score a single result against expected violations."""
    actual_status = result.get("final_status", "UNKNOWN")
    expected_status = case["expected_status"]
    violations = result.get("compliance_results", [])
    min_violations = case.get("min_violations", 0)

    status_correct = actual_status == expected_status
    violation_count_ok = len(violations) >= min_violations

    return {
        "id": case["id"],
        "name": case["name"],
        "expected_status": expected_status,
        "actual_status": actual_status,
        "status_correct": status_correct,
        "expected_min_violations": min_violations,
        "actual_violations": len(violations),
        "violation_count_ok": violation_count_ok,
        "pass": status_correct and violation_count_ok,
        "violations": [
            {"category": v.get("category"), "description": v.get("description", "")[:100]}
            for v in violations
        ],
        "report_snippet": result.get("final_report", "")[:200],
    }


def main():
    dataset_path = Path(__file__).parent / "golden_dataset.json"
    with open(dataset_path) as f:
        dataset = json.load(f)

    print(f"Running {len(dataset)} golden cases...\n")
    results = []

    for i, case in enumerate(dataset, 1):
        print(f"[{i}/{len(dataset)}] {case['name']}...", end=" ", flush=True)
        try:
            result = run_single(case)
            scored = score(case, result)
            results.append(scored)
            mark = "PASS" if scored["pass"] else "FAIL"
            print(f"{mark} (status={scored['actual_status']}, violations={scored['actual_violations']})")
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                "id": case["id"],
                "name": case["name"],
                "pass": False,
                "error": str(e),
            })

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r.get("pass"))
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{total} passed ({100*passed/total:.0f}%)")
    print(f"{'='*60}\n")

    # Failures detail
    failures = [r for r in results if not r.get("pass")]
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  [{f['id']}] {f['name']}")
            if f.get("error"):
                print(f"    Error: {f['error']}")
            else:
                print(f"    Expected: {f.get('expected_status')} | Got: {f.get('actual_status')}")
                print(f"    Min violations: {f.get('expected_min_violations')} | Got: {f.get('actual_violations')}")
                print(f"    Report: {f.get('report_snippet', '')}")
        print()

    # Save results
    output_path = Path(__file__).parent / "eval_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Full results saved to {output_path}")


if __name__ == "__main__":
    main()
