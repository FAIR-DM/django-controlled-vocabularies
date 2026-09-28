"""Fixtures shared by the exchange test modules."""

import re

import pytest

# A bare `%` left after stripping every named placeholder is a positional or stray one,
# which Article XII forbids.
_NAMED_PLACEHOLDER = re.compile(r"%\([a-zA-Z_][a-zA-Z0-9_]*\)s")


@pytest.fixture
def uses_only_named_placeholders():

    def _predicate(message: str) -> bool:
        return "%" not in _NAMED_PLACEHOLDER.sub("", message)

    return _predicate
