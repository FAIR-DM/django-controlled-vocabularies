"""Django settings for a project whose database is not configured yet."""

from tests.settings import *  # noqa: F403

# A project can run ``manage.py check`` before it has a database, in a build step or in
# CI. With no NAME, opening a connection raises ImproperlyConfigured.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3"}}
