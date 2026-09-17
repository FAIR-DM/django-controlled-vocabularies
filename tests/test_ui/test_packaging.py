"""Tests proving django-mvp only ever arrives through the opt-in ``ui`` extra (T004).

There is no ``controlled_vocabularies/ui/packaging.py`` to mirror against — the subject is
``pyproject.toml`` itself — so this file is one of the standing non-mirror exceptions
(``[tool.forge.conformance] non-mirror-paths``, T001).
"""

from pathlib import Path

import tomllib

PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


def load_pyproject():
    return tomllib.loads(PYPROJECT_PATH.read_text())


class TestDjangoMVPIsOptOnly:
    """FR-012 — installing the core alone resolves no ui dependency."""

    def test_django_mvp_is_optional(self):
        pyproject = load_pyproject()
        dependency = pyproject["tool"]["poetry"]["dependencies"]["django-mvp"]
        assert dependency["optional"] is True

    def test_django_mvp_is_declared_in_the_ui_extra(self):
        pyproject = load_pyproject()
        extras = pyproject["tool"]["poetry"]["extras"]
        assert extras["ui"] == ["django-mvp"]

    def test_django_mvp_is_absent_from_every_other_extra(self):
        pyproject = load_pyproject()
        extras = pyproject["tool"]["poetry"]["extras"]
        for extra_name, packages in extras.items():
            if extra_name == "ui":
                continue
            assert "django-mvp" not in packages

    def test_django_mvp_is_absent_from_every_poetry_dependency_group(self):
        pyproject = load_pyproject()
        groups = pyproject["tool"]["poetry"].get("group", {})
        for group_name, group in groups.items():
            dependencies = group.get("dependencies", {})
            assert "django-mvp" not in dependencies, (
                f"django-mvp found in poetry group '{group_name}'"
            )


class TestToolingReadsCoreOnlySettings:
    """The type checker runs in a job that installs no extras, so anything it imports has to be
    resolvable without them.
    """

    def test_django_stubs_points_at_a_settings_module_that_installs_no_ui_app(self):
        # django-stubs' mypy plugin imports this module at startup. Pointed at tests.settings,
        # which installs django-mvp's stack, the plugin cannot be constructed in a job installed
        # without the `ui` extra — and it fails as an internal error naming the plugin, not the
        # import, on a machine where mypy passes locally because the extra happens to be there.
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
