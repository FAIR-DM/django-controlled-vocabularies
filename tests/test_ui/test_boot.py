"""Tests that the core boots and passes system checks with no ui app installed."""

import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "controlled_vocabularies"
UI_ROOT = PACKAGE_ROOT / "ui"


def core_module_names():
    """List every importable dotted module name outside ``controlled_vocabularies.ui``.

    Migration filenames such as ``0001_initial`` are not valid Python identifiers, so the
    subprocess script below imports each name with ``importlib.import_module`` rather than a
    literal ``import`` statement.

    Returns:
        The dotted module names, sorted by path.
    """
    names = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if UI_ROOT in path.parents:
            continue
        parts = list(path.relative_to(PACKAGE_ROOT.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.append(".".join(parts))
    return names


# Runs in a fresh subprocess because django.setup() only runs once per interpreter, and the
# settings module is forced inside the script because pytest-django exports tests.settings.
BOOT_SCRIPT_TEMPLATE = """
import importlib
import os
import sys

os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings_core"
import django
django.setup()

from django.core.management import call_command
call_command("check")

for name in {module_names!r}:
    importlib.import_module(name)

assert "controlled_vocabularies.ui" not in sys.modules, "controlled_vocabularies.ui was imported by the core boot"
print("BOOT_OK")
"""


class TestCoreBootsWithNoUIAppInstalled:
    def test_core_boots_checks_clean_and_imports_every_core_module(self):
        script = BOOT_SCRIPT_TEMPLATE.format(module_names=core_module_names())
        result = subprocess.run(  # noqa: S603 — fixed interpreter, literal script, no user input
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "BOOT_OK" in result.stdout
