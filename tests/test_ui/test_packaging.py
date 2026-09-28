"""Tests that django-mvp only arrives through the opt-in ``ui`` extra."""

import tomllib
from pathlib import Path

PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


def load_pyproject():
    """Parse the repository's pyproject.toml.

    Returns:
        The parsed document.
    """
    return tomllib.loads(PYPROJECT_PATH.read_text())


class TestDjangoMVPIsOptOnly:
    def test_django_mvp_is_absent_from_the_core_dependencies(self):
        pyproject = load_pyproject()
        assert not any(
            requirement.startswith("django-mvp")
            for requirement in pyproject["project"]["dependencies"]
        )

    def test_django_mvp_is_declared_in_the_ui_extra(self):
        pyproject = load_pyproject()
        extras = pyproject["project"]["optional-dependencies"]
        assert [requirement.split(">")[0] for requirement in extras["ui"]] == [
            "django-mvp"
        ]

    def test_django_mvp_is_absent_from_every_other_extra(self):
        pyproject = load_pyproject()
        extras = pyproject["project"]["optional-dependencies"]
        for extra_name, requirements in extras.items():
            if extra_name == "ui":
                continue
            assert not any(
                requirement.startswith("django-mvp") for requirement in requirements
            )


class TestToolingReadsCoreOnlySettings:
    def test_django_stubs_points_at_a_settings_module_that_installs_no_ui_app(self):
        # The mypy plugin imports this module at startup, and the type-check job installs no
        # extras. Pointed at tests.settings it fails there as an internal plugin error, while
        # passing locally where the ui extra happens to be installed.
        settings_module = load_pyproject()["tool"]["django-stubs"][
            "django_settings_module"
        ]

        assert settings_module == "tests.settings_core"

        source = (
            (PYPROJECT_PATH.parent / settings_module.replace(".", "/"))
            .with_suffix(".py")
            .read_text()
        )
        for ui_app in (
            "mvp",
            "django_cotton",
            "crispy_forms",
            "crispy_tailwind",
            "easy_icons",
            "flex_menu",
        ):
            assert f'"{ui_app}"' not in source, f"{settings_module} installs {ui_app}"
