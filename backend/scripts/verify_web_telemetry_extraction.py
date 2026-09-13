"""Source-only equivalence for web policies/HTTP adapters and provider telemetry."""
import ast
import copy
from pathlib import Path
import subprocess

BACKEND = Path(__file__).resolve().parents[1]
REF = "refactor-stages-0-4-complete"
RENAMES = {"_tfidf_terms":"tfidf_terms","_rank_results_by_tfidf":"rank_results_by_tfidf",
           "_merge_result_groups":"merge_result_groups","_clean_text":"clean_text","_parse_results":"parse_results"}


class Normalize(ast.NodeTransformer):
    def visit_Name(self,node):
        node.id = RENAMES.get(node.id,node.id)
        return node
    def visit_FunctionDef(self,node):
        node.name = RENAMES.get(node.name,node.name)
        return self.generic_visit(node)
    visit_AsyncFunctionDef = visit_FunctionDef
    def visit_Expr(self,node):
        if isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=="emit_event":
            return None
        return self.generic_visit(node)
    def visit_Assign(self,node):
        if isinstance(node.targets[0],ast.Name) and node.targets[0].id=="version_purpose":
            return None
        return self.generic_visit(node)


def declarations(source):
    return {node.name:node for node in ast.parse(source).body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}


def main():
    groups = {
        "web_search_service": ["app/domain/web/intent_policy.py","app/domain/web/url_policy.py","app/domain/web/ranking.py","app/infrastructure/web/search_results.py","app/infrastructure/web/searxng_gateway.py"],
        "web_reader_service": ["app/infrastructure/web/page_reader.py"],
        "ai_usage_service": ["app/observability/ai_telemetry.py"],
    }
    failures=[]
    for service, paths in groups.items():
        original=declarations(subprocess.check_output(["git","show",REF+":backend/services/"+service+".py"],cwd=BACKEND.parent).decode("utf-8"))
        moved={}
        for path in paths: moved.update(declarations((BACKEND/path).read_text(encoding="utf-8")))
        count=0
        for name,node in original.items():
            owner=moved.get(RENAMES.get(name,name))
            before=ast.dump(Normalize().visit(copy.deepcopy(node)),include_attributes=False)
            after=ast.dump(Normalize().visit(copy.deepcopy(owner)),include_attributes=False) if owner else None
            if before!=after:
                failures.append(service+"."+name)
                count+=1
        print(f"{service}: {len(original)} declarations, {count} differences")
    for failure in failures: print(failure)
    return int(bool(failures))


if __name__=="__main__":
    raise SystemExit(main())

