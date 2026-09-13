"""Verify moved vector/graph algorithms against the Git baseline using AST only.

Run after structural extraction. No provider imports or runtime data operations.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
from pathlib import Path
import subprocess

BACKEND = Path(__file__).resolve().parents[1]


def baseline_source(ref, path):
    return subprocess.check_output(["git", "-c", "safe.directory=" + BACKEND.parent.as_posix(), "show", ref + ":backend/" + path], cwd=BACKEND.parent).decode("utf-8")


class NormalizeVector(ast.NodeTransformer):
    modules = {"state", "qdrant_client_factory", "embedding_encoder", "chunker", "qdrant_vector_store", "retrieval_ranker", "vector_maintenance"}

    def visit_Global(self, node):
        return None

    def visit_Attribute(self, node):
        node = self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id in self.modules:
            return ast.Name(id=node.attr, ctx=node.ctx)
        return node


def dump(node, vector=False):
    node = copy.deepcopy(node)
    if vector:
        node = NormalizeVector().visit(node)
    return ast.dump(node, include_attributes=False)


def all_methods(directory):
    result = {}
    for path in directory.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef):
                result[node.name] = node
    return result


def graph_constants(nodes):
    return Counter(" ".join(node.value.split()) for tree in nodes for node in ast.walk(tree)
                   if isinstance(node, ast.Constant) and isinstance(node.value, str)
                   and any(word in node.value for word in ("MATCH ", "MERGE ", "DROP CONSTRAINT", "CREATE CONSTRAINT", "CREATE INDEX", "FULLTEXT INDEX")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-ref", default="refactor-backend-baseline")
    args = parser.parse_args()
    vector_before = ast.parse(baseline_source(args.baseline_ref, "services/qdrant_service.py"))
    vector_after = {}
    for path in (BACKEND / "app/infrastructure/vector").glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                vector_after[node.name] = node
    errors = []
    count = 0
    for node in vector_before.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            count += 1
            if node.name not in vector_after or dump(node, vector=True) != dump(vector_after[node.name], vector=True):
                errors.append("Vector algorithm changed: " + node.name)

    graph_before = ast.parse(baseline_source(args.baseline_ref, "services/neo4j_service.py"))
    original = next(node for node in graph_before.body if isinstance(node, ast.ClassDef))
    graph_paths = list((BACKEND / "app/infrastructure/graph").glob("*.py")) + [BACKEND / "app/domain/graph/identity.py"]
    graph_after_trees = [ast.parse(path.read_text(encoding="utf-8")) for path in graph_paths]
    graph_after = {node.name: node for tree in graph_after_trees for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    graph_count = 0
    for node in original.body:
        if not isinstance(node, ast.FunctionDef) or node.name == "merge_knowledge":
            continue
        graph_count += 1
        if node.name not in graph_after or dump(node) != dump(graph_after[node.name]):
            errors.append("Graph method changed: " + node.name)

    # The long transaction callback is lifted into three methods. Its loop
    # statements must remain structurally identical, allowing indentation-only
    # whitespace changes in multiline Cypher literals.
    old_merge = next(node for node in original.body if isinstance(node, ast.FunctionDef) and node.name == "merge_knowledge")
    old_apply = next(node for node in old_merge.body if isinstance(node, ast.FunctionDef))
    resolver_index = next(index for index, node in enumerate(old_apply.body) if isinstance(node, ast.FunctionDef))

    class NormalizeStrings(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and "\n" in node.value:
                node.value = " ".join(node.value.split())
            return node

    def normalized_list(nodes):
        return ast.dump(NormalizeStrings().visit(copy.deepcopy(ast.Module(body=nodes, type_ignores=[]))), include_attributes=False)

    entity_method = graph_after["_write_entities"]
    if normalized_list(old_apply.body[1:resolver_index]) != normalized_list(entity_method.body[7:-1]):
        errors.append("Graph entity write statements changed")
    for iteration, method in (("edges", "_write_facts"), ("retractions", "_apply_retractions")):
        original_loop = next(node for node in old_apply.body if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id == iteration)
        moved_loop = next(node for node in graph_after[method].body if isinstance(node, ast.For))
        if normalized_list([original_loop]) != normalized_list([moved_loop]):
            errors.append("Graph loop changed: " + iteration)
    if graph_constants([graph_before]) != graph_constants(graph_after_trees):
        errors.append("Graph Cypher constants changed")
    policy_before = ast.parse(baseline_source(args.baseline_ref, "services/memory_policy.py"))
    policy_after = ast.parse((BACKEND / "app/domain/graph/fact_policy.py").read_text(encoding="utf-8"))
    if dump(policy_before) != dump(policy_after):
        errors.append("Graph evidence policy changed")
    print(f"Vector algorithms: {count}; unchanged graph methods: {graph_count}; graph write components: 3")
    for error in errors:
        print(error)
    if not errors:
        print("PASS: moved algorithms, graph query constants, and evidence policies match baseline")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
