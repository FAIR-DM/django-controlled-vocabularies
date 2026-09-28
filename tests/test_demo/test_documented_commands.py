"""Tests that the documented demo commands are the ones the demo workflow runs."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BROWSING_DOC = REPO_ROOT / "docs" / "browsing.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "demo.yml"

DEMO_SECTION_HEADING = "## Try it: the demo project"

# Line-scoped on purpose: a pattern free to cross newlines swallows the surrounding
# prose into the prefix and reports the failure against that.
MANAGE_COMMAND = re.compile(
    r"^(.*?)\bpython\s+manage\.py\s+([a-z_]+)", flags=re.MULTILINE
)


def demo_section():
    """Return the demo section of the browsing page.

    Returns:
        The text from the demo heading to the next heading of the same level or higher.
    """
    text = BROWSING_DOC.read_text(encoding="utf-8")
    start = text.index(DEMO_SECTION_HEADING)
    rest = text[start + len(DEMO_SECTION_HEADING) :]
    end = re.search(r"^#{1,2} ", rest, flags=re.MULTILINE)
    return rest[: end.start()] if end else rest


def documented_commands():
    """Return every ``manage.py`` invocation the demo section documents.

    Returns:
        A ``(prefix, subcommand)`` pair for each invocation, the prefix being what runs
        before the interpreter.
    """
    return MANAGE_COMMAND.findall(demo_section())


class TestDocumentedCommands:
    def test_the_documentation_gives_the_three_commands_the_demo_needs(self):
        subcommands = [subcommand for _, subcommand in documented_commands()]

        assert "migrate" in subcommands, subcommands
        assert "seed_demo" in subcommands, subcommands
        assert "runserver" in subcommands, subcommands

    @pytest.mark.parametrize(("prefix", "subcommand"), documented_commands())
    def test_every_documented_command_runs_in_the_installed_environment(
        self, prefix, subcommand
    ):
        assert prefix.strip().endswith("uv run"), (
            f"{BROWSING_DOC.name} documents '{prefix} python manage.py {subcommand}': a bare "
            "interpreter is not the environment 'uv sync' just built, and on a "
            "machine whose path carries only 'python3' it does not exist at all"
        )

    @pytest.mark.parametrize("subcommand", ["migrate", "seed_demo", "runserver"])
    def test_the_unattended_walk_runs_the_documented_commands(self, subcommand):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        assert f"manage.py {subcommand}" in workflow, (
            f"{BROWSING_DOC.name} documents 'manage.py {subcommand}' but {WORKFLOW.name} never "
            "runs it, so nothing checks that the documented path still works"
        )
