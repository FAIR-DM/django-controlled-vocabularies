"""Tests for the demo project's settings and URLs."""

import os
import subprocess
import sys

# Runs in a fresh interpreter because django.setup() runs once per process, and the
# script forces DJANGO_SETTINGS_MODULE because pytest-django exports tests.settings to
# subprocesses.
BOOT_SCRIPT = """
import os
os.environ["DJANGO_SETTINGS_MODULE"] = "demo.settings"
import django
django.setup()

from django.conf import settings
from django.core.checks import run_checks
from django.urls import resolve, reverse

# run_checks(), not call_command("check"): the command exits zero on warnings, and a
# demo that warns is a worked example of the mistake.
messages = run_checks()
assert not messages, "the demo must start silently: " + "; ".join(str(m) for m in messages)

assert settings.DEBUG is True, "the demo must be recognisable as a demo, not a deployment"
assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
assert settings.DATABASES["default"]["NAME"] != ":memory:", "the demo's database must be a local file"

list_url_name = "controlled_vocabularies_ui:vocabulary-list"
reverse(list_url_name)

root_match = resolve("/")
assert root_match.url_name == "home", root_match.url_name
assert root_match.func.view_class.__name__ == "RedirectView", root_match.func.view_class
assert root_match.func.view_initkwargs["pattern_name"] == list_url_name, root_match.func.view_initkwargs

print("DEMO_BOOT_OK")
"""


class TestDemoProject:
    def test_demo_boots_checks_clean_and_the_root_redirects_to_the_list(self):
        result = subprocess.run(  # noqa: S603 — fixed interpreter, literal script, no user input
            [sys.executable, "-c", BOOT_SCRIPT],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "DEMO_BOOT_OK" in result.stdout


# CONTROLLED_VOCABULARIES_BASE_URI must match where demo/urls.py mounts the browsing
# routes, or the demo is the misconfiguration controlled_vocabularies.ui.W001 reports.
# It runs against a temp database, never the repo's own demo/db.sqlite3.
BASE_ADDRESS_BOOT_SCRIPT = """
import os
os.environ["DJANGO_SETTINGS_MODULE"] = "demo.settings"
import django
django.setup()

from django.core.management import call_command
from django.conf import settings

call_command("migrate", run_syncdb=True, verbosity=0)

from demo.management.commands.seed_demo import Command
from controlled_vocabularies.models import ConceptScheme

call_command(Command())

authored = ConceptScheme.objects.get(static_uri__isnull=True)
imported = ConceptScheme.objects.get(static_uri__isnull=False)

assert authored.uri == authored.local_url, authored.uri
assert authored.uri.startswith(settings.CONTROLLED_VOCABULARIES_BASE_URI), authored.uri

assert imported.uri == imported.static_uri, imported.uri
assert not imported.uri.startswith(settings.CONTROLLED_VOCABULARIES_BASE_URI), imported.uri

print("DEMO_BASE_ADDRESS_OK")
"""


class TestDemoBaseAddress:
    def test_the_locally_authored_vocabularys_identifier_moves_and_the_imported_ones_does_not(
        self, tmp_path
    ):
        env = dict(os.environ, DEMO_DB_PATH=str(tmp_path / "demo.sqlite3"))
        result = subprocess.run(  # noqa: S603 — fixed interpreter, literal script, no user input
            [sys.executable, "-c", BASE_ADDRESS_BOOT_SCRIPT],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert "DEMO_BASE_ADDRESS_OK" in result.stdout
