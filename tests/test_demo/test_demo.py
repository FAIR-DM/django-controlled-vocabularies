"""The demo project boots and serves the list at its root (T015, FR-014, FR-015, FR-018,
User Story 3 scenarios 1 and 4).

Run in a fresh subprocess, never the pytest process itself: ``django.setup()`` only ever runs
once per interpreter, and the pytest session has already populated the app registry from
``tests.settings`` before this test executes (the same reason ``tests/test_ui/test_boot.py``
boots its own subject in a subprocess). ``DJANGO_SETTINGS_MODULE`` is forced inside the
subprocess script itself, not read from the parent's exported environment variable, because
pytest-django exports ``DJANGO_SETTINGS_MODULE=tests.settings`` and this subprocess inherits it
by default.

There is no ``demo/test_demo.py`` for this to mirror — the subject is a whole project booting,
not one module — so this file is a non-mirror exception (``[tool.forge.conformance]
non-mirror-paths``, T015).
"""

import os
import subprocess
import sys

BOOT_SCRIPT = """
import os
os.environ["DJANGO_SETTINGS_MODULE"] = "demo.settings"
import django
django.setup()

from django.conf import settings
from django.core.checks import run_checks
from django.urls import resolve, reverse

# run_checks(), not call_command("check"): the management command exits zero on warnings, so it
# passes a configuration that tells its own user something is wrong on every startup. The demo
# is read as an example of how to wire this package, and an example that warns is a worked
# example of the mistake. Assert the silence rather than the exit code.
messages = run_checks()
assert not messages, "the demo must start silently: " + "; ".join(str(m) for m in messages)

assert settings.DEBUG is True, "the demo must be recognisable as a demo, not a deployment (FR-018)"
assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
assert settings.DATABASES["default"]["NAME"] != ":memory:", "the demo's database must be a local file (FR-018)"

list_url_name = "controlled_vocabularies_ui:vocabulary-list"
reverse(list_url_name)

root_match = resolve("/")
assert root_match.url_name == "home", root_match.url_name
assert root_match.func.view_class.__name__ == "RedirectView", root_match.func.view_class
assert root_match.func.view_initkwargs["pattern_name"] == list_url_name, root_match.func.view_initkwargs

print("DEMO_BOOT_OK")
"""


class TestDemoProject:
    """FR-014, FR-015, FR-018 — the demo settings module boots and passes ``manage.py check``,
    its list route reverses under its own urlconf, and its root address is configured to
    redirect to it, with a local database and ``DEBUG`` on so the demo is recognisable as one
    (User Story 3 scenarios 1 and 4)."""

    def test_demo_boots_checks_clean_and_the_root_redirects_to_the_list(self):
        result = subprocess.run(  # noqa: S603 — fixed interpreter, literal script, no user input
            [sys.executable, "-c", BOOT_SCRIPT],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "DEMO_BOOT_OK" in result.stdout


# T006: CONTROLLED_VOCABULARIES_BASE_URI must match where demo/urls.py mounts the browsing
# routes ("/browse/") — without it the demo is exactly the misconfiguration T005's check
# exists to report. Migrates and seeds in the same fresh subprocess (a local sqlite file
# under a temp path, never the repo's own demo/db.sqlite3) so the assertions run against a
# real demo database rather than one asserted about from the outside.
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
    """The demonstration is configured so its identifiers resolve (T006, US-1 scenario 4 in
    the demonstration, SC-007)."""

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
