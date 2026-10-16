"""Guard: the core package imports no web framework and no API module, and stays on
the standard library, so the API and front-end can sit on top of it."""

import ast
import subprocess
import sys
from pathlib import Path

import edgar_rag

CORE = Path(edgar_rag.__file__).parent

WEB_FRAMEWORKS = {
    "aiohttp",
    "django",
    "fastapi",
    "flask",
    "sanic",
    "starlette",
    "tornado",
    "uvicorn",
}
# Packages that sit on top of the core: the API and the provider implementations.
OUTSIDE_CORE = {"api", "edgar_api", "edgar_answer"}


def _imported_modules(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


def test_the_core_package_imports_only_the_standard_library_and_itself():
    imports = {
        (path.name, module.split(".")[0])
        for path in CORE.glob("*.py")
        for module in _imported_modules(path)
    }

    outside = {
        (name, top)
        for name, top in imports
        if top != "edgar_rag" and top not in sys.stdlib_module_names
    }
    assert outside == set()
    assert not {top for _, top in imports} & (WEB_FRAMEWORKS | OUTSIDE_CORE)


def test_importing_every_core_module_loads_no_web_framework_or_api_module():
    modules = sorted(f"edgar_rag.{p.stem}" for p in CORE.glob("*.py") if p.stem != "__init__")
    code = (
        "import importlib, sys\n"
        f"for m in {modules!r}: importlib.import_module(m)\n"
        "print('\\n'.join(sorted({m.split('.')[0] for m in sys.modules})))"
    )

    loaded = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.split()

    assert not set(loaded) & (WEB_FRAMEWORKS | OUTSIDE_CORE | {"openai", "anthropic"})
