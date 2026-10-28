"""Django settings for a project whose database is not configured yet."""

from tests.settings import *  # noqa: F403

# A project can run ``manage.py check`` before it has a database, in a build step or in
# CI. With none configured, Django's placeholder backend raises ImproperlyConfigured on
# any query.
DATABASES = {}
