"""Tests for assistant.brain_callbacks module."""

from unittest.mock import MagicMock

import pytest

from assistant.brain_callbacks import BrainCallbacksMixin


class TestBrainCallbacksMixin:
    """Tests for the BrainCallbacksMixin base class."""

    def test_can_instantiate(self):
        """BrainCallbacksMixin can be instantiated directly."""
        mixin = BrainCallbacksMixin()
        assert mixin is not None

    def test_is_class(self):
        """BrainCallbacksMixin is a proper class."""
        assert isinstance(BrainCallbacksMixin, type)

    def test_has_no_methods(self):
        """BrainCallbacksMixin has no user-defined methods (intentionally empty)."""
        own_methods = [
            m
            for m in dir(BrainCallbacksMixin)
            if not m.startswith("_") and callable(getattr(BrainCallbacksMixin, m))
        ]
        assert own_methods == []

    def test_can_be_used_as_mixin(self):
        """BrainCallbacksMixin works in a multi-inheritance chain."""

        class FakeBase:
            def some_method(self):
                return "base"

        class Combined(BrainCallbacksMixin, FakeBase):
            pass

        obj = Combined()
        assert obj.some_method() == "base"

    def test_mixin_in_mro(self):
        """BrainCallbacksMixin appears in MRO when used as base class."""

        class Child(BrainCallbacksMixin):
            pass

        assert BrainCallbacksMixin in Child.__mro__

    def test_subclass_can_override(self):
        """Subclasses can add callback methods that get called."""

        class Extended(BrainCallbacksMixin):
            def on_event(self, event):
                return f"handled: {event}"

        ext = Extended()
        assert ext.on_event("test") == "handled: test"

    def test_pass_body_does_nothing(self):
        """The pass body means no attributes are set."""
        mixin = BrainCallbacksMixin()
        own_attrs = [a for a in vars(mixin)]
        assert own_attrs == []
