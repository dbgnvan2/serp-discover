"""
tests/test_tk_probe.py
~~~~~~~~~~~~~~~~~~~~~~
The GUI skip condition must mean what its name says.

Before this, both GUI test modules set TKINTER_AVAILABLE from whether tkinter
*imports*. On a headless machine with tkinter installed the import succeeds and
`Tk()` then raises `TclError: no display name and no $DISPLAY` — so 26 tests
that read as "skipped, fine" locally failed the first time they met such a
machine. The flag now reflects whether a window can actually be built.
"""

import unittest
from unittest.mock import patch

from tk_probe import tkinter_usable


class TestTkProbe(unittest.TestCase):

    def setUp(self):
        import tk_probe
        tk_probe._USABLE = None          # the probe caches; start clean
        self.addCleanup(setattr, tk_probe, "_USABLE", None)

    def test_reports_false_when_no_display_is_available(self):
        """The case the import check could not see."""
        import tkinter
        with patch.object(tkinter, "Tk", side_effect=tkinter.TclError(
                "no display name and no $DISPLAY environment variable")):
            self.assertFalse(tkinter_usable())

    def test_reports_false_when_tkinter_is_absent(self):
        import builtins
        real_import = builtins.__import__

        def no_tkinter(name, *a, **kw):
            if name == "tkinter":
                raise ImportError("No module named 'tkinter'")
            return real_import(name, *a, **kw)

        with patch.object(builtins, "__import__", no_tkinter):
            self.assertFalse(tkinter_usable())

    def test_reports_true_when_a_window_can_be_built(self):
        import tkinter
        try:
            tkinter.Tk().destroy()
        except Exception:
            self.skipTest("no usable display here — covered by the CI run")
        self.assertTrue(tkinter_usable())

    def test_the_result_is_cached(self):
        """Callers use it as a module-level skip condition, and each probe
        costs a real window."""
        import tk_probe
        tk_probe._USABLE = True
        import tkinter
        with patch.object(tkinter, "Tk", side_effect=AssertionError("re-probed")):
            self.assertTrue(tkinter_usable())


if __name__ == "__main__":
    unittest.main()
