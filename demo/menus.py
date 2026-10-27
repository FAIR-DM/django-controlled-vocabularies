"""The demo's sidebar: the documentation's contents, led by the vocabulary list."""

from django.utils.translation import gettext_lazy as _
from flex_menu import MenuItem

from demo.mounted import docs

# The documentation is the demo's main app, so its menu is the sidebar on every page, the
# browsing pages included. Inserted ahead of the front page's entry, the list stays first when
# the docs are rebuilt.
docs.menu.insert(
    MenuItem(
        name="vocabularies",
        view_name="controlled_vocabularies_ui:vocabulary-list",
        extra_context={"label": _("Vocabularies")},
    ),
    position=0,
)
