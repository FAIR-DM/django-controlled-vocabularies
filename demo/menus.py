"""The demo's sidebar: the documentation's contents, then the demo's own pages."""

from flex_menu import MenuItem
from mvp.menus import MenuGroup

from demo.mounted import docs

# The documentation is the demo's main app, so its menu is the sidebar on every page, the
# browsing pages included. Appended, the group follows the contents and keeps its place when the
# docs are rebuilt.
docs.menu.append(
    MenuGroup(
        name="demo",
        extra_context={"label": "Demo"},
        children=[
            MenuItem(
                name="vocabularies",
                view_name="controlled_vocabularies_ui:vocabulary-list",
                extra_context={"label": "Vocabularies"},
            ),
        ],
    )
)
