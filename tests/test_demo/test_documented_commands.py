"""The commands the documentation gives are the commands the unattended walk runs (SC-007).

The demo's whole claim is that a stranger can follow three commands from a fresh clone and see
the page. Nothing else in this suite reads the documentation, so the documented commands could
drift from the working ones — and did: the section first shipped calling a bare
``python manage.py``, which on a machine whose path carries only ``python3`` fails at the demo's
own first step, while every test here and the walk in CI passed, because both go through
``poetry run``.

There is no ``demo/test_documented_commands.py`` for this to mirror — the subject is the
documentation and the workflow agreeing with each other — so this file is a non-mirror exception
(``[tool.forge.conformance] non-mirror-paths``).
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BROWSING_DOC = REPO_ROOT / "docs" / "browsing.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "demo.yml"

DEMO_SECTION_HEADING = "## Try it: the demo project"

#: A ``manage.py`` invocation, captured one line at a time — what runs before the interpreter,
#: and the subcommand after it. Line-scoped deliberately: a pattern free to cross newlines
#: swallows the surrounding prose into the prefix and reports the failure against that.
MANAGE_COMMAND = re.compile(
    r"^(.*?)\bpython\s+manage\.py\s+([a-z_]+)", flags=re.MULTILINE
)


def demo_section():
    """The page's text from the demo heading to the next heading of the same level or higher."""
    text = BROWSING_DOC.read_text(encoding="utf-8")
    start = text.index(DEMO_SECTION_HEADING)
    rest = text[start + len(DEMO_SECTION_HEADING) :]
    end = re.search(r"^#{1,2} ", rest, flags=re.MULTILINE)
    return rest[: end.start()] if end else rest


def documented_commands():
    """Every ``manage.py`` invocation the demo section documents, as (prefix, subcommand)."""
    return MANAGE_COMMAND.findall(demo_section())


class TestDocumentedCommands:
    """SC-007 — the documented demo commands are runnable as written, and the unattended walk
    runs the same ones, so the documentation cannot rot away from the thing it documents."""

    def test_the_documentation_gives_the_three_commands_the_demo_needs(self):
        subcommands = [subcommand for _, subcommand in documented_commands()]

        assert "migrate" in subcommands, subcommands
        assert "seed_demo" in subcommands, subcommands
        assert "runserver" in subcommands, subcommands

    @pytest.mark.parametrize(("prefix", "subcommand"), documented_commands())
    def test_every_documented_command_runs_in_the_installed_environment(
        self, prefix, subcommand
    ):
        """Every invocation the section carries, not only the three that start it: the same
        drift that shipped a bare ``python manage.py migrate`` can ship a bare
        ``createsuperuser`` beside it."""
        assert prefix.strip().endswith("poetry run"), (
            f"{BROWSING_DOC.name} documents '{prefix} python manage.py {subcommand}': a bare "
            "interpreter is not the environment 'poetry install' just built, and on a "
            "machine whose path carries only 'python3' it does not exist at all"
        )

    @pytest.mark.parametrize("subcommand", ["migrate", "seed_demo", "runserver"])
    def test_the_unattended_walk_runs_the_documented_commands(self, subcommand):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        assert f"manage.py {subcommand}" in workflow, (
            f"{BROWSING_DOC.name} documents 'manage.py {subcommand}' but {WORKFLOW.name} never "
            "runs it, so nothing checks that the documented path still works"
        )
