"""Tests proving the core imports nothing from the opt-in ui front end (T004).

The subject is every module under ``controlled_vocabularies/`` outside ``controlled_vocabularies/
ui/``, not a single source module — there is no ``controlled_vocabularies/ui/architecture.py`` to
mirror against, so this file is one of the standing non-mirror exceptions
(``[tool.forge.conformance] non-mirror-paths``, T001).
"""

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "controlled_vocabularies"
UI_ROOT = PACKAGE_ROOT / "ui"

FORBIDDEN_ROOTS = (
    "mvp",
    "django_cotton",
    "crispy_forms",
    "easy_icons",
    "flex_menu",
    "controlled_vocabularies.ui",
)


def core_modules():
    return [
        path
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if UI_ROOT not in path.parents
    ]


def imported_names(path):
    """Every dotted name this module's import statements name.

    Parsed rather than grepped, so a forbidden name inside a docstring or a comment cannot fail
    the test and a real import cannot hide from it.
    """
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


class TestCoreImportsNothingFromTheUIStack:
    """FR-012's isolation — no core module names ``mvp``, its dependencies, or
    ``controlled_vocabularies.ui``."""

    @pytest.mark.parametrize(
        "path",
        core_modules(),
        ids=lambda p: str(p.relative_to(PACKAGE_ROOT)),
    )
    def test_module_imports_no_ui_dependency(self, path):
        imported = imported_names(path)
        offending = {
            name
            for name in imported
            if any(
                name == forbidden or name.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_ROOTS
            )
        }
        assert not offending, f"{path} imports forbidden module(s): {offending}"
