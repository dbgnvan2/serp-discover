"""tk_probe.py — can this environment actually create a Tk window?

Importing tkinter is not the question. On a headless machine the import
succeeds and `Tk()` then raises `TclError: no display name and no $DISPLAY`,
which is how 26 GUI tests passed locally as "skipped" and failed the moment
they met a machine that had tkinter installed (CI, and any Mac with a full
Python). The probe builds a root window and tears it down, so the flag means
what its name says.

Tests: tests/test_tk_probe.py
"""

_USABLE = None


def tkinter_usable() -> bool:
    """True when a Tk root can actually be created and destroyed here.

    Cached: the probe costs a real window, and callers use it as a module-level
    skip condition evaluated at import.
    """
    global _USABLE
    if _USABLE is not None:
        return _USABLE
    try:
        import tkinter
        root = tkinter.Tk()
    except Exception:            # ImportError, TclError, and anything the
        _USABLE = False          # platform raises when there is no display
    else:
        try:
            root.destroy()
        except Exception:
            pass
        _USABLE = True
    return _USABLE
