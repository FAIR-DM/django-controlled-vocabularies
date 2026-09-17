"""Tests for ``controlled_vocabularies/ui/apps.py`` and ``__init__.py`` (T002).

Run in a fresh subprocess, never the pytest process itself: ``django.setup()`` only ever runs
once per interpreter, and the pytest session has already populated the app registry from
``tests.settings`` before this test executes (the repo's existing out-of-process precedent,
``tests/settings_no_admin.py``). ``controlled_vocabularies.ui`` is not yet installed by
``tests.settings`` at this point in the story (T003 widens it), so this configures its own
minimal registry inline rather than depending on either settings module.
"""

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
    """The ui app registers alongside the core app without raising, under a label distinct
    from the core app's, and its ``__init__.py`` stays inert (FR-012)."""

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
