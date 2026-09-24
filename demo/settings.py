"""Django settings for the demo / dev server (T015, FR-014, FR-015, FR-018).

Written out in full rather than imported from the test settings: a reader comparing this
against README.md's "Finding a vocabulary" section should find the same wiring twice, and a
settings module that imports the tests' would teach nobody anything and would drag test-only
choices — an in-memory database, a fixed URI base — into the thing meant to look like a real
project (plan.md Complexity Tracking).
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# django.setup() imports every INSTALLED_APPS entry before any management command runs, so a
# missing 'ui' extra dependency has to be caught here, at settings-module load, or it surfaces
# as a raw traceback from deep inside whichever of mvp/django_cotton/etc. is missing.
try:
    import mvp  # noqa: F401
except ImportError:
    sys.stderr.write(
        "The demo needs the front end's dependencies, which are not installed. "
        "Install them with: pip install django-controlled-vocabularies[ui] "
        "(or uv sync --extra ui).\n"
    )
    sys.exit(1)

SECRET_KEY = "django-insecure-demo-secret-key-do-not-use-in-production"  # noqa: S105 — obviously throwaway, demo only (FR-018)

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# DEMO_DB_PATH lets a test run point the destructive seed_demo command at a scratch file
# instead of the developer's real demo database. With no variable set, the documented start
# path is unchanged.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DEMO_DB_PATH", str(BASE_DIR / "demo" / "db.sqlite3")),
    }
}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "demo",
    # The front end, wired exactly as README.md's "Finding a vocabulary" section documents —
    # the demo must match it, and if the two ever disagree the README is the thing that is
    # right (013-find-a-vocabulary task brief).
    "controlled_vocabularies",
    # The package's own concept search control, which its system checks require of any project
    # installing it — not only of one rendering the browsing pages. The demo's admin edits a
    # vocabulary, so a project reading these settings as an example gets the whole wiring.
    "django_tomselect",
    "django_cotton",
    "easy_icons",
    "flex_menu",
    # "mvp" before "crispy_tailwind": django-mvp ships an override of crispy-tailwind's
    # help-text template, and the first app to declare a template path wins.
    "mvp",
    "crispy_forms",
    "crispy_tailwind",
    "controlled_vocabularies.ui",
]

# crispy-forms 2.7's get_template_pack() is getattr(settings, "CRISPY_TEMPLATE_PACK") with no
# default, so leaving this unset is an AttributeError on the first form render rather than a
# fallback to another pack.
CRISPY_TEMPLATE_PACK = "tailwind"

# And the allowlist has to name it too. The {% crispy %} tag validates the pack at
# TEMPLATE-COMPILE time against CRISPY_ALLOWED_TEMPLATE_PACKS, whose default is
# ("uni_form", "bootstrap3", "bootstrap4") — so every template carrying the tag fails to
# compile.
CRISPY_ALLOWED_TEMPLATE_PACKS = ["tailwind"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Between SessionMiddleware and CommonMiddleware, Django's own required order —
    # without it every request reads in LANGUAGE_CODE regardless of what it asks for, and
    # a concept's own page could never show a value falling back from a reading language
    # to the vocabulary's default (015-read-single-record T024, FR-005, README's "Try it").
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # django-tomselect builds the concept search control's context from a thread-local request,
    # and only this middleware sets it. Without the entry the control renders as an empty select
    # carrying no search — which is why the package's own checks refuse to stay quiet about it.
    "django_tomselect.middleware.TomSelectMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # The shell's site name in every page title needs this (README.md).
                "mvp.context_processors.mvp_config",
            ],
        },
    }
]

ROOT_URLCONF = "demo.urls"

# Must match the path component of wherever demo/urls.py mounts controlled_vocabularies.ui's
# routes ("/browse/") — otherwise a locally authored vocabulary's identifier does not lead
# back to its own page (FR-004), which is exactly the misconfiguration
# controlled_vocabularies.ui.W001 exists to report (014-look-inside-a-vocabulary T006).
CONTROLLED_VOCABULARIES_BASE_URI = "http://localhost:8000/browse"

# mvp/base.html loads the packaged stylesheet with {% static %} unconditionally, so having
# django.contrib.staticfiles installed is not enough on its own (README.md).
STATIC_URL = "static/"

# Every icon the shell renders resolves through django-easy-icons; without a "default"
# renderer configured, opening any page in the UI app raises ImproperlyConfigured (README.md).
EASY_ICONS = {
    "default": {
        "renderer": "easy_icons.renderers.ProviderRenderer",
        "config": {"tag": "i"},
        "packs": ["mvp.utils.BS5_ICONS"],
    },
}

# The shell's sidebar and mobile navigation are rendered by django-flex-menus, which raises
# ValueError at render time without these renderers configured (README.md).
FLEX_MENUS = {
    "renderers": {
        "sidebar": "mvp.renderers.SidebarRenderer",
        "dock": "mvp.renderers.MobileFooterNavRenderer",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_TZ = True
TIME_ZONE = "UTC"
USE_I18N = True

# Django's own default (LANGUAGE_CODE="en-us") is not itself a member of the default
# LANGUAGES list, which the importer's own configuration check refuses to import against
# (controlled_vocabularies.exchange.skos.SkosImporter — DEFAULT_LANGUAGE_UNCONFIGURED) — the
# seed command fails without this, before it stores a single concept.
LANGUAGE_CODE = "en"
