"""Django settings for the demo development server."""

import os
import sys
from pathlib import Path

# Written out in full rather than imported from the test settings, whose in-memory database and
# fixed URI base would not look like a real project.
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

SECRET_KEY = "django-insecure-demo-secret-key-do-not-use-in-production"  # noqa: S105 — obviously throwaway, demo only

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
    # Wired as README.md's "Finding a vocabulary" section documents; the README wins any disagreement.
    "controlled_vocabularies",
    # The concept search control, which the package's system checks require of any installing project.
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

# The {% crispy %} tag checks the pack at template-compile time against this allowlist, whose
# default omits "tailwind", so every template carrying the tag would fail to compile.
CRISPY_ALLOWED_TEMPLATE_PACKS = ["tailwind"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Between SessionMiddleware and CommonMiddleware, as Django requires. Without it every request
    # reads in LANGUAGE_CODE, so a concept page could not show the language fallback (FS-015).
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

# Must match where demo/urls.py mounts the ui routes ("/browse/"), or a local vocabulary's
# identifier does not lead back to its page, which controlled_vocabularies.ui.W001 reports (FS-014).
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
