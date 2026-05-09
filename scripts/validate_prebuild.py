#!/usr/bin/env python3
from __future__ import annotations

import ast
import compileall
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_MAIN = ROOT / "app" / "backend" / "main.py"
BACKEND_DIR = ROOT / "app" / "backend"
FRONTEND_SEARCH = ROOT / "app" / "frontend" / "pages" / "search.js"
BACKEND_PARSER = ROOT / "app" / "backend" / "chat_parser.py"
BACKEND_SEARCH = ROOT / "app" / "backend" / "search.py"
BACKEND_CHAT_SEARCH = ROOT / "app" / "backend" / "chat_search.py"

ANON_API_WHITELIST = {
    "/api/auth/login",
    "/api/auth/logout",
}
AUTH_GUARDS = {"get_current_user", "require_admin"}


def fail(message: str) -> None:
    print(f"[validate] ERROR: {message}")
    raise SystemExit(1)


def check_backend_compiles() -> None:
    ok = compileall.compile_dir(str(BACKEND_DIR), force=False, quiet=1)
    if not ok:
        fail("backend python compile failed")
    print("[validate] backend compile check passed")


def _decorator_route_path(decorator: ast.expr) -> str | None:
    if not isinstance(decorator, ast.Call):
        return None
    if not isinstance(decorator.func, ast.Attribute):
        return None
    if not isinstance(decorator.func.value, ast.Name):
        return None
    if decorator.func.value.id != "app":
        return None
    if decorator.func.attr not in {"get", "post", "put", "delete", "patch"}:
        return None
    if not decorator.args:
        return None
    first_arg = decorator.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value
    return None


def _has_auth_guard(fn: ast.FunctionDef) -> bool:
    all_defaults = list(fn.args.defaults) + list(fn.args.kw_defaults)
    for default in all_defaults:
        if not isinstance(default, ast.Call):
            continue
        if not isinstance(default.func, ast.Name) or default.func.id != "Depends":
            continue
        if not default.args:
            continue
        dep = default.args[0]
        if isinstance(dep, ast.Name) and dep.id in AUTH_GUARDS:
            return True
    return False


def check_backend_api_auth() -> None:
    tree = ast.parse(BACKEND_MAIN.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        route_paths = [path for deco in node.decorator_list if (path := _decorator_route_path(deco))]
        for path in route_paths:
            if not path.startswith("/api/"):
                continue
            if path in ANON_API_WHITELIST:
                continue
            if not _has_auth_guard(node):
                violations.append(path)
    if violations:
        fail(f"api auth guard missing for routes: {', '.join(sorted(set(violations)))}")
    print("[validate] backend api auth guard check passed")


def check_papers_pagination_regression() -> None:
    content = FRONTEND_SEARCH.read_text(encoding="utf-8")
    required_snippets = [
        "const [query, setQuery] = useState('');",
        "runSearch(undefined, 1);",
        "const [totalPages, setTotalPages] = useState(0);",
        "const [pageHint, setPageHint] = useState('');",
        "已自动跳到最后一页",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in content]
    if missing:
        fail("papers pagination regression check failed")
    print("[validate] papers pagination regression check passed")


def check_generic_semantic_retrieval_guards() -> None:
    parser_content = BACKEND_PARSER.read_text(encoding="utf-8")
    search_content = BACKEND_SEARCH.read_text(encoding="utf-8")
    chat_search_content = BACKEND_CHAT_SEARCH.read_text(encoding="utf-8")

    parser_required = [
        "def classify_query_type(",
        "def _ensure_query_type_cache_table()",
        "_load_query_type_cache(",
        "_save_query_type_cache(",
        "fallback = \"specific\"",
        "query_type=classify_query_type(query, topic)",
    ]
    search_required = [
        "query_type: str = \"specific\"",
        "elif query_type == \"generic\":",
        "blend_mode = \"semantic_first\"",
    ]
    chat_search_required = [
        "structured_query.query_type == \"generic\"",
        "recall_limit = max(structured_query.top_k * 8, 48)",
        "\"query_type\": structured_query.query_type",
    ]

    if any(item not in parser_content for item in parser_required):
        fail("generic query detection guard check failed")
    if any(item not in search_content for item in search_required):
        fail("dynamic semantic rerank guard check failed")
    if any(item not in chat_search_content for item in chat_search_required):
        fail("generic recall tuning guard check failed")
    print("[validate] generic semantic retrieval guard check passed")


def main() -> None:
    print("[validate] running prebuild checks...")
    # This validation script is intentionally offline-only.
    # Do not add any LLM, network, or external API calls here.
    check_backend_compiles()
    check_backend_api_auth()
    check_papers_pagination_regression()
    check_generic_semantic_retrieval_guards()
    print("[validate] all checks passed")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        fail(f"unexpected failure: {exc}")
