"""Sphinx settings for the package's documentation, which the demo project serves as its pages."""

project = "django-controlled-vocabularies"
extensions = [
    # Writes the contents the demo's sidebar shows (django-mvp-sphinx).
    "mvp_sphinx.navigation",
    # The pages are Markdown, readable on GitHub as they are.
    "myst_parser",
]
source_suffix = {".md": "markdown"}
# agents/ holds the instructions coding agents read, which are not part of the manual.
exclude_patterns = ["_build", "agents"]
# A link written as `page.md#a-heading` reaches the heading, as it does on GitHub.
myst_heading_anchors = 3
