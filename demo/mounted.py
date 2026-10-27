"""The demo project's documentation app: the package's own docs/, served inside the shell."""

import os

from django.conf import settings
from mvp_sphinx.mounted import DocumentationApp

# source_dir lets `manage.py build_docs` build the pages this app serves. DEMO_DOCS_BUILD_DIR
# lets a test run build into a scratch folder instead of the developer's own build, as
# DEMO_DB_PATH does for the database.
docs = DocumentationApp(
    build_dir=os.environ.get(
        "DEMO_DOCS_BUILD_DIR", settings.BASE_DIR / "docs" / "_build" / "json"
    ),
    source_dir=settings.BASE_DIR / "docs",
)
