"""Contract tests: validates architectural layer boundary and dependency direction invariants."""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SIMULATOR_SRC = REPO_ROOT / "apps" / "backend" / "src" / "simulator"


def _get_imports(file_path: Path) -> list[str]:
    """Parse AST and return list of imported module names."""
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(file_path))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def test_domain_layer_isolation() -> None:
    domain_dir = SIMULATOR_SRC / "domain"
    domain_files = list(domain_dir.glob("*.py"))
    assert len(domain_files) > 0, "No domain files found"

    forbidden_prefixes = (
        "simulator.application",
        "simulator.infrastructure",
        "simulator.interfaces",
        "simulator.bootstrap",
        "fastapi",
        "starlette",
        "pydantic",
        "sqlalchemy",
        "sqlite3",
        "requests",
        "httpx",
        "aiohttp",
        "flask",
        "mcp",
    )

    for py_file in domain_files:
        imports = _get_imports(py_file)
        for imp in imports:
            for forbidden in forbidden_prefixes:
                assert not imp.startswith(forbidden), (
                    f"Architectural boundary violation: domain file {py_file.name} "
                    f"imports forbidden module {imp!r}"
                )


def test_application_layer_isolation() -> None:
    app_dir = SIMULATOR_SRC / "application"
    app_files = list(app_dir.rglob("*.py"))
    assert len(app_files) > 0, "No application files found"

    forbidden_prefixes = (
        "simulator.infrastructure",
        "simulator.interfaces",
        "simulator.bootstrap",
        "fastapi",
        "starlette",
        "pydantic",
        "sqlalchemy",
        "sqlite3",
        "requests",
        "httpx",
        "aiohttp",
        "flask",
        "mcp",
    )

    for py_file in app_files:
        imports = _get_imports(py_file)
        for imp in imports:
            for forbidden in forbidden_prefixes:
                assert not imp.startswith(forbidden), (
                    f"Architectural boundary violation: application file {py_file.name} "
                    f"imports forbidden module {imp!r}"
                )
