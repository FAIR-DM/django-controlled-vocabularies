"""Django settings for a project that never installs django.contrib.admin."""

from django.core.management.utils import get_random_secret_key

# Loaded in a fresh interpreter: an app registry is built once per process, so proving
# the admin absent cannot use override_settings
# (docs/adr/0013-the-django-admin-stays-an-optional-dependency.md).

# Generated per run: only a throwaway subprocess loads this, and a key literal is one
# more credential-shaped string for a scanner to find.
SECRET_KEY = get_random_secret_key()

ROOT_URLCONF = "tests.urls_no_admin"

# django_tomselect builds the control's full context only when this middleware stores
# the request.
MIDDLEWARE = [
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
    "django_tomselect",
    "controlled_vocabularies",
    "tests.testapp",
]

# Fixed base so URI-composition assertions are deterministic across the test suite.
CONTROLLED_VOCABULARIES_BASE_URI = "https://example.org/vocabularies"
