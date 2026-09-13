"""Temporary forwarding facades for legacy imports and monkeypatch consumers.

Remove after roadmap stages 5â€“8 migrate all legacy consumers. Forwarding writes
are intentional: old test patches must affect the single implementation owner.
"""
from types import ModuleType
import sys


class ForwardingModule(ModuleType):
    def __getattr__(self, name):
        owner, attribute = self.__dict__["_owners"].get(name, (None, None))
        if owner is None:
            raise AttributeError(name)
        return getattr(owner, attribute)

    def __setattr__(self, name, value):
        owner, attribute = self.__dict__.get("_owners", {}).get(name, (None, None))
        if owner is None:
            return super().__setattr__(name, value)
        setattr(owner, attribute, value)

    def __delattr__(self, name):
        owner, attribute = self.__dict__.get("_owners", {}).get(name, (None, None))
        if owner is None:
            return super().__delattr__(name)
        delattr(owner, attribute)


def install_facade(name, owners):
    module = sys.modules[name]
    module.__dict__["_owners"] = owners
    module.__class__ = ForwardingModule
