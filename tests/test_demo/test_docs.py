"""Tests for the demo project serving the package's documentation as its pages."""

import os
import subprocess
import sys

# Runs in a fresh interpreter for the reason test_demo.py gives, against a scratch database and a
# scratch documentation build, never the developer's own.
DOCS_SCRIPT = """
import os
import re
os.environ["DJANGO_SETTINGS_MODULE"] = "demo.settings"
import django
django.setup()

from django.core.management import call_command
from django.test import Client
from django.urls import reverse

call_command("migrate", run_syncdb=True, verbosity=0)
call_command("build_docs", verbosity=0)

# The sidebar's <nav> comes from the installed shell and carries no id, so it is the <nav> that
# holds the docs page link.
NAVS = re.compile(r"<nav\\b.*?</nav>", re.DOTALL)
list_url = reverse("controlled_vocabularies_ui:vocabulary-list")
docs_page_url = reverse("docs:page", kwargs={"path": "browsing/"})

# "testserver", the test client's default host, is not one the demo allows.
client = Client(HTTP_HOST="localhost")
front = client.get("/", follow=True)
assert front.status_code == 200, front.status_code
assert front.redirect_chain[-1][0] == reverse("docs:front_page"), front.redirect_chain

for response in (front, client.get(docs_page_url), client.get(list_url)):
    assert response.status_code == 200, response.status_code
    navs = NAVS.findall(response.content.decode())
    sidebar = next((n for n in navs if f'href="{docs_page_url}"' in n), None)
    assert sidebar is not None, navs
    assert f'href="{list_url}"' in sidebar, sidebar

print("DEMO_DOCS_OK")
"""


class TestDemoDocumentation:
    def test_the_root_opens_the_docs_and_every_sidebar_leads_to_the_list_and_the_docs(
        self, tmp_path
    ):
        env = dict(
            os.environ,
            DEMO_DB_PATH=str(tmp_path / "demo.sqlite3"),
            DEMO_DOCS_BUILD_DIR=str(tmp_path / "docs"),
        )
        result = subprocess.run(  # noqa: S603 — fixed interpreter, literal script, no user input
            [sys.executable, "-c", DOCS_SCRIPT],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert "DEMO_DOCS_OK" in result.stdout
