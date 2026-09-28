"""Minimal Django settings for the core-only test configuration."""

# Stays free of controlled_vocabularies.ui and every ui dependency: the core-only boot
# test boots against it to prove the core starts with nothing ui installed (FS-013).

SECRET_KEY = "test-key-not-for-production"

ROOT_URLCONF = "tests.urls_core"

# django_tomselect builds the control's full context only when its middleware stores
# the request. The admin's system checks (admin.E4xx) need the session, auth and
# message middleware.
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django_tomselect.middleware.TomSelectMiddleware",
]

USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# A fixed default plus two more languages, so per-language behaviour does not depend on
# Django's full built-in LANGUAGES list.
USE_I18N = True
LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", "English"),
    ("de", "German"),
    ("fr", "French"),
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "django_tomselect",
    "controlled_vocabularies",
    "tests.testapp",
]

# The admin's system checks require these three context processors.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

STATIC_URL = "static/"

# Fixed base so URI-composition assertions are deterministic across the test suite.
CONTROLLED_VOCABULARIES_BASE_URI = "https://example.org/vocabularies"
