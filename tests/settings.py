"""Django settings for the full test suite: the core settings plus the ui front end."""

from tests.settings_core import *

INSTALLED_APPS = [
    *INSTALLED_APPS,
    "django_cotton",
    "easy_icons",
    "flex_menu",
    # ``mvp`` before ``crispy_tailwind``: mvp overrides crispy-tailwind's help-text
    # template, and the first app to declare a template path wins.
    "mvp",
    "crispy_forms",
    "crispy_tailwind",
    "controlled_vocabularies.ui",
]

# crispy-forms reads this with no default, so leaving it unset is an AttributeError on
# the first form render.
CRISPY_TEMPLATE_PACK = "tailwind"

# The {% crispy %} tag checks the pack at template-compile time against this allowlist,
# whose default omits tailwind, so every template carrying the tag would fail to
# compile.
CRISPY_ALLOWED_TEMPLATE_PACKS = ["tailwind"]

TEMPLATES[0]["OPTIONS"]["context_processors"] = [
    *TEMPLATES[0]["OPTIONS"]["context_processors"],
    "mvp.context_processors.mvp_config",
]

ROOT_URLCONF = "tests.urls"

# Without a "default" renderer, any page using <c-icon> (mvp's base template does)
# raises ImproperlyConfigured.
EASY_ICONS = {
    "default": {
        "renderer": "easy_icons.renderers.ProviderRenderer",
        "config": {"tag": "i"},
        "packs": ["mvp.utils.BS5_ICONS"],
    },
}

# django-flex-menus raises ValueError at render time without these renderers.
FLEX_MENUS = {
    "renderers": {
        "sidebar": "mvp.renderers.SidebarRenderer",
        "dock": "mvp.renderers.MobileFooterNavRenderer",
    },
}
