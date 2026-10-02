"""Keep Tk tests independent of each other."""

import gc
import tkinter

import pytest


@pytest.fixture(autouse=True)
def _tk_cleanup():
    """Tk hates multiple Tk() instances per process — clear the leaked
    default root and collect between tests so widgets from a destroyed
    interpreter don't trip the next one."""
    yield
    root = getattr(tkinter, "_default_root", None)
    if root is not None:
        try:
            root.destroy()
        except Exception:
            pass
    tkinter._default_root = None
    gc.collect()
