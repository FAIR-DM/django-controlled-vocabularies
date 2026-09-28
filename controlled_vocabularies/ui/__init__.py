"""The opt-in front end for browsing the vocabularies a site holds."""

# No re-exports: this module is imported before the models are ready, so a re-export reaching
# views.py would raise AppRegistryNotReady from django.setup().
