"""Run versioned AI/RAG regression fixtures with the isolated offline runner."""
from pathlib import Path
import json
import subprocess
import sys

BACKEND = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((BACKEND / "evals/manifest.json").read_text(encoding="utf-8"))
    patterns = [pattern for group in manifest["groups"].values() for pattern in group]
    if len(patterns) != len(set(patterns)):
        raise ValueError("Evaluation groups must not duplicate tests")
    for pattern in patterns:
        if not list((BACKEND / "tests").glob(pattern)):
            raise ValueError("Missing evaluation test: " + pattern)
    result = subprocess.run([sys.executable, str(BACKEND / "scripts/run_tests.py"), *patterns])
    raw = json.loads((BACKEND / ".refactor/test-results.json").read_text(encoding="utf-8"))
    failed = set(raw["failures"] + raw["errors"] + [item[0] for item in raw["skipped"]])
    metrics = {}
    for group, members in manifest["groups"].items():
        modules = {Path(member).stem for member in members}
        ids = [identifier for identifier in raw["test_ids"] if identifier.split(".")[0] in modules]
        passed = sum(identifier not in failed for identifier in ids)
        metrics[group] = {"cases": len(ids), "passed": passed,
                          "fidelity": passed / len(ids) if ids else None}
    accepted = result.returncode == 0 and all(
        metric["fidelity"] is not None and metric["fidelity"] >= manifest["threshold"]
        for metric in metrics.values())
    report = {"version": manifest["version"], "mode": manifest["mode"],
              "accepted": accepted, "metrics": metrics,
              "live_answer_quality": "not_evaluated"}
    (BACKEND / ".refactor/eval-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
