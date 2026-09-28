"""Tests for the demo project's admin."""

import subprocess
import sys

# Runs in a fresh interpreter because django.setup() runs once per process. Walks the
# documented instruction end to end: a bare registration would pass a registered-only
# check yet refuse the form, since slug is required.
ADMIN_SCRIPT = """
import os, tempfile
os.environ["DJANGO_SETTINGS_MODULE"] = "demo.settings"
os.environ["DEMO_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "db.sqlite3")
import django
django.setup()

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.test.utils import setup_test_environment
from django.urls import reverse

from controlled_vocabularies.models import ConceptScheme

setup_test_environment()
call_command("migrate", verbosity=0)

client = Client()
client.force_login(get_user_model().objects.create_superuser("demo", "demo@example.com", "pw"))

add_url = reverse("admin:controlled_vocabularies_conceptscheme_add")
assert client.get(add_url).status_code == 200, "the admin serves no form for adding a vocabulary"

client.post(add_url, {"name": "Added By Hand", "description": "Typed in.", "default_language": "", "static_uri": ""})
assert ConceptScheme.objects.filter(name="Added By Hand").exists(), "the submitted form stored nothing"

listing = client.get(reverse("controlled_vocabularies_ui:vocabulary-list")).content.decode()
assert "Added By Hand" in listing, "the hand-added vocabulary is absent from the list"

print("DEMO_ADMIN_OK")
"""


class TestDemoAdmin:
    def test_a_vocabulary_added_through_the_admin_appears_on_the_list(self):
        result = subprocess.run(  # noqa: S603 — fixed interpreter, literal script, no user input
            [sys.executable, "-c", ADMIN_SCRIPT],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "DEMO_ADMIN_OK" in result.stdout
