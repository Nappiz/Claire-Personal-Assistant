"""Check layer boundaries/cycles; optionally compare a recorded Git baseline.

Usage: python backend/scripts/check_architecture.py --baseline-ref refactor-backend-baseline
This script parses source only. It never imports production modules or stores.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path
import subprocess

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SOURCE_DIRS = {"app", "configs", "models", "routes", "schemas", "services"}


def module_name(path):
    parts = list(Path(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def current_sources():
    return {path.relative_to(BACKEND).as_posix(): path.read_text(encoding="utf-8")
            for path in BACKEND.rglob("*.py")
            if path.relative_to(BACKEND).parts[0] in SOURCE_DIRS
            and "__pycache__" not in path.parts} | {"main.py": (BACKEND / "main.py").read_text(encoding="utf-8")}


def git_sources(ref):
    # Scope safe.directory to this known workspace without changing Git config.
    git = ["git", "-c", "safe.directory=" + ROOT.as_posix()]
    paths = subprocess.check_output(git + ["ls-tree", "-r", "--name-only", ref, "backend"], cwd=ROOT).decode().splitlines()
    sources = {}
    for path in paths:
        relative = path.removeprefix("backend/")
        if path.endswith(".py") and (relative == "main.py" or relative.split("/")[0] in SOURCE_DIRS):
            sources[relative] = subprocess.check_output(git + ["show", ref + ":" + path], cwd=ROOT).decode("utf-8")
    return sources


def dependency_graph(sources):
    modules = {module_name(path): path for path in sources}
    graph = {module: set() for module in modules}
    violations = []
    for module, path in modules.items():
        tree = ast.parse(sources[path], filename=path)
        package = module if path.endswith("__init__.py") else module.rpartition(".")[0]
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = importlib.util.resolve_name("." * node.level + (node.module or ""), package) if node.level else (node.module or "")
                for alias in node.names:
                    child = base + "." + alias.name
                    targets.append(child if child in modules else base)
            for target in targets:
                if target in modules and target != module:
                    graph[module].add(target)
                forbidden = False
                if module.startswith("app.domain."):
                    forbidden = target.startswith(("app.api", "app.application", "app.infrastructure", "services", "configs")) or target.split(".")[0] in {"fastapi", "sqlalchemy", "openai", "neo4j", "qdrant_client", "sentence_transformers"}
                elif module.startswith("app.application."):
                    forbidden = target.startswith(("app.api", "app.infrastructure", "services", "configs", "models")) or target.split(".")[0] in {"fastapi", "sqlalchemy", "openai", "neo4j", "qdrant_client", "sentence_transformers"}
                elif module.startswith("app.api.routers."):
                    forbidden = target.startswith(("services", "models", "configs", "app.infrastructure")) or target.split(".")[0] in {"sqlalchemy", "openai", "neo4j", "qdrant_client", "sentence_transformers"}
                if forbidden:
                    violations.append(f"{path}:{node.lineno}: forbidden dependency {target}")
    return graph, violations


def cycles(graph):
    # Strongly connected components identify cycles without exponential path enumeration.
    counter, stack, indices, lowlinks, active, result = 0, [], {}, {}, set(), []

    def visit(node):
        nonlocal counter
        indices[node] = lowlinks[node] = counter
        counter += 1
        stack.append(node)
        active.add(node)
        for target in sorted(graph[node]):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in active:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component = []
            while True:
                target = stack.pop()
                active.remove(target)
                component.append(target)
                if target == node:
                    break
            if len(component) > 1:
                result.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-ref")
    args = parser.parse_args()
    sources = current_sources()
    graph, violations = dependency_graph(sources)
    current_cycles = cycles(graph)
    report = {"modules": len(graph), "edges": sum(map(len, graph.values())), "cycles": current_cycles,
              "violations": violations, "graph": {key: sorted(value) for key, value in sorted(graph.items())}}
    if args.baseline_ref:
        baseline_graph, _ = dependency_graph(git_sources(args.baseline_ref))
        report["baseline"] = {"ref": args.baseline_ref, "modules": len(baseline_graph), "cycles": cycles(baseline_graph),
                              "graph": {key: sorted(value) for key, value in sorted(baseline_graph.items())}}
    output = BACKEND / ".refactor/dependency-graph.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"graph", "baseline"}}, indent=2))
    if "baseline" in report:
        print("Baseline cycles:", report["baseline"]["cycles"])
    return 1 if violations or current_cycles else 0


if __name__ == "__main__":
    raise SystemExit(main())
