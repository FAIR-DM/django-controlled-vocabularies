"""Tests for controlled_vocabularies.ui.apps and the ui package ``__init__``."""

import ast
import subprocess
import sys
from pathlib import Path

INIT_PATH = (
    Path(__file__).resolve().parents[2]
    / "controlled_vocabularies"
    / "ui"
    / "__init__.py"
)

# Runs in a fresh subprocess because django.setup() only runs once per interpreter and the
# pytest session has already populated the app registry from tests.settings.
BOOT_SCRIPT = """
import django
from django.conf import settings

settings.configure(
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "controlled_vocabularies",
        "controlled_vocabularies.ui",
    ],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
)
django.setup()

from django.apps import apps

core = apps.get_app_config("controlled_vocabularies")
ui = apps.get_app_config("controlled_vocabularies_ui")
assert ui.name == "controlled_vocabularies.ui"
assert ui.label == "controlled_vocabularies_ui"
assert ui.label != core.label
print("BOOT_OK")
"""


class TestUIAppConfig:
    def test_app_registers_alongside_the_core_app_under_a_distinct_label(self):
        result = subprocess.run(  # noqa: S603 — fixed interpreter, literal script, no user input
            [sys.executable, "-c", BOOT_SCRIPT],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "BOOT_OK" in result.stdout

    def test_init_module_is_a_docstring_and_nothing_else(self):
        tree = ast.parse(INIT_PATH.read_text())
        assert len(tree.body) == 1
        (statement,) = tree.body
        assert isinstance(statement, ast.Expr)
        assert isinstance(statement.value, ast.Constant)
        assert isinstance(statement.value.value, str)
