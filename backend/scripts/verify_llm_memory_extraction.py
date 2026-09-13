"""Characterize stage-5/6 extraction against its Git checkpoint, without imports.

Compare moved function bodies after reversing only documented DI, query lifting,
and helper extraction. Runtime behavior is additionally protected by the suite.
"""
from __future__ import annotations
import argparse
import ast
import copy
from pathlib import Path
import subprocess

BACKEND = Path(__file__).resolve().parents[1]


def baseline(ref, filename):
    return ast.parse(subprocess.check_output(["git", "show", ref + ":backend/services/" + filename + ".py"], cwd=BACKEND.parent).decode("utf-8"))


def methods(paths):
    result = {}
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result[node.name] = node
    return result


class Normalize(ast.NodeTransformer):
    def __init__(self, originals, moved, queries, context):
        self.aliases = {name.lstrip("_"): name for name in originals}
        self.moved, self.queries, self.context = moved, queries, context
        self.eligible = None

    def visit_ImportFrom(self, node): return None
    def visit_Import(self, node): return None

    def visit_arg(self, node):
        node.annotation = None
        return node

    def visit_AnnAssign(self, node):
        return self.visit(ast.Assign(targets=[node.target], value=node.value))

    def visit_FunctionDef(self, node):
        node.name = self.aliases.get(node.name, node.name)
        if node.args.args and node.args.args[0].arg == "self": node.args.args.pop(0)
        node.returns = None
        node.type_comment = None
        if node.name == "_claim_memory_job":
            eligible = next((item for item in ast.walk(node) if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name) and item.targets[0].id == "eligible"), None)
            self.eligible = copy.deepcopy(eligible.value) if eligible is not None else None
        return self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Name(self, node):
        if node.id == "eligible" and isinstance(node.ctx, ast.Load) and self.eligible is not None:
            return self.visit(copy.deepcopy(self.eligible))
        node.id = self.aliases.get(node.id, node.id)
        for prefix in ("MEMORY_", "HISTORICAL_RE", "SEARCH_STOPWORDS", "VAGUE_PROJECT_REFERENCE_RE", "CONTEXT_REFERENCE_RE", "GENERIC_ENTITY_REFERENCES", "QUESTION_CLAUSE_RE", "WEB_TOOL_"):
            if node.id.startswith(prefix) and not node.id.startswith("_"):
                node.id = "_" + node.id
                break
        return node

    def visit_Attribute(self, node):
        rendered = ast.unparse(node)
        direct = {"self.config": "settings", "self.persistence.open": "SessionLocal",
                  "self.graph": "neo4j_client", "self.vector": "vector_store",
                  "self.threadpool": "run_in_threadpool", "self.ground_locations": "ground_locations",
                  "self.usage_context": "usage_context", "self.executor": "_MEMORY_RETRIEVAL_EXECUTOR",
                  "self.retrieval_executor.submit": "_submit_retrieval", "self.db": "db"}
        for name in ("tracked_sync_completion", "tracked_async_completion", "route_memory_query", "extract_knowledge", "search_memory", "search_project_memory_candidates", "save_memory", "reconcile_memory", "reconcile_extracted_knowledge", "save_knowledge_to_graph", "generate_session_summary", "generate_session_title"):
            direct["self.gateway." + name] = name
            direct["self." + name] = name
        direct["self.references.reference_matches"] = "_reference_matches"
        if rendered in direct: return ast.Name(id=direct[rendered], ctx=node.ctx)
        if isinstance(node.value, ast.Name) and node.value.id == "state":
            return ast.Name(id=node.attr, ctx=node.ctx)
        if rendered.startswith("self.") and node.attr in self.aliases:
            return ast.Name(id=self.aliases[node.attr], ctx=node.ctx)
        if rendered.startswith("db.new_"):
            aliases = {"new_message": "Message", "new_conversation": "Conversation", "new_outbox": "MemoryOutbox", "new_usage": "LLMUsageLog"}
            if node.attr in aliases: return ast.Name(id=aliases[node.attr], ctx=node.ctx)
        return self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "db" and node.func.attr in self.queries:
            method = self.queries[node.func.attr]
            replacements = dict(zip([arg.arg for arg in method.args.args[1:]], node.args))
            expression = next(item.value for item in method.body if isinstance(item, ast.Return))
            eligible = next((item for item in method.body if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name) and item.targets[0].id == "eligible"), None)
            if eligible is not None: replacements["eligible"] = eligible.value
            class Substitute(ast.NodeTransformer):
                def visit_Name(self, item):
                    if item.id in replacements: return copy.deepcopy(replacements[item.id])
                    return item
            expression = Substitute().visit(copy.deepcopy(expression))
            return self.visit(expression)
        return self.generic_visit(node)

    def visit_Assign(self, node):
        if isinstance(node.targets[0], ast.Name) and node.targets[0].id == "eligible": return None
        if isinstance(node.value, ast.Call):
            rendered = ast.unparse(node.value.func)
            lifted = {"self.prompts.build_extraction_prompt": "build_extraction_prompt",
                      "self.prompts.build_memory_query_prompt": "build_memory_query_prompt",
                      "self.turn.normalize_completion": "normalize_completion",
                      "self.outbox.finalize_updates": "finalize_updates"}
            if rendered in lifted:
                return [self.visit(copy.deepcopy(item)) for item in self.moved[lifted[rendered]].body if not isinstance(item, ast.Return)]
            if rendered in {"self.persistence.wrap", "ToolLoopState"}: return None
        # Synthetic bindings around the lifted planning phase have no business logic.
        if isinstance(node.value, ast.Attribute) and ast.unparse(node.value).startswith("self.web"): return None
        if isinstance(node.targets[0], ast.Tuple) and isinstance(node.value, ast.Tuple) and any(isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name) and item.value.id == "state" for item in ast.walk(node.value)): return None
        return self.generic_visit(node)

    def visit_AsyncWith(self, node):
        context = node.items[0].context_expr
        if isinstance(context, ast.Call) and isinstance(context.func, ast.Name) and context.func.id == "aclosing" and context.args and isinstance(context.args[0], ast.Call) and ast.unparse(context.args[0].func) == "self.execute_web_tool_loop":
            return [value for item in self.moved["execute_web_tool_loop"].body if (value := self.visit(copy.deepcopy(item))) is not None]
        return self.generic_visit(node)


def compare(ref, filename, paths, extras=()):
    before = baseline(ref, filename)
    originals = {node.name: node for node in before.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    after = methods(paths)
    after.update(methods(extras))
    if filename == "llm_service":
        after.update(methods([BACKEND / "app/infrastructure/llm/client_factory.py"]))
    queries = methods(path for path in (BACKEND / "app/infrastructure/persistence/memory").glob("*.py") if path.name != "transaction.py") if filename == "memory_service" else {}
    failures = []
    for name, old in originals.items():
        public = "submit" if name == "_submit_retrieval" else name.lstrip("_")
        new = after.get(public)
        if new is None:
            failures.append(name + ": missing owner")
            continue
        normalizer = Normalize(originals, after, queries, filename)
        old_dump = ast.dump(normalizer.visit(copy.deepcopy(old)), include_attributes=False)
        normalizer = Normalize(originals, after, queries, filename)
        normalized = normalizer.visit(copy.deepcopy(new))
        if name == "_submit_retrieval": normalized.name = name
        new_dump = ast.dump(normalized, include_attributes=False)
        if old_dump != new_dump:
            failures.append(name + ": body differs")
            diagnostic = BACKEND / ".refactor" / (filename + "_" + name.lstrip("_"))
            diagnostic.parent.mkdir(exist_ok=True)
            diagnostic.with_suffix(".before.txt").write_text(old_dump, encoding="utf-8")
            diagnostic.with_suffix(".after.txt").write_text(new_dump, encoding="utf-8")
    print(f"{filename}: {len(originals)} functions, {len(failures)} differences")
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-ref", default="refactor-stages-0-4-complete")
    args = parser.parse_args()
    llm_paths = list((BACKEND / "app/domain/llm").glob("*.py")) + list((BACKEND / "app/infrastructure/llm").glob("*.py"))
    for relative in ("chat/generate_response", "chat/stream_response", "chat/execute_web_tool_loop", "memory/extract_knowledge", "memory/route_memory_query", "conversations/generate_title", "conversations/generate_summary", "diagnostics/analyze_error"):
        llm_paths.append(BACKEND / "app/application" / (relative + ".py"))
    memory_paths = list((BACKEND / "app/domain/memory").glob("*.py"))
    for relative in ("memory/resolve_project_scope", "memory/retrieve_context", "conversations/read_history", "conversations/begin_turn", "conversations/complete_turn", "conversations/persist_interaction", "memory/outbox_snapshots", "memory/outbox_leases", "memory/process_outbox_job", "memory/retry_due_jobs", "conversations/cancel_conversation_jobs", "conversations/process_summary", "conversations/record_internal_error", "memory/reindex_vectors", "conversations/save_title"):
        memory_paths.append(BACKEND / "app/application" / (relative + ".py"))
    failures = compare(args.baseline_ref, "llm_service", llm_paths)
    failures += compare(args.baseline_ref, "memory_service", memory_paths, [BACKEND / "app/infrastructure/memory/retrieval_executor.py"])
    for failure in failures: print(failure)
    if not failures: print("PASS: extracted bodies and SQL expressions match checkpoint")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
