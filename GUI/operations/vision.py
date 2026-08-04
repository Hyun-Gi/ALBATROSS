"""
Vision inspection bridge — reuses the existing albatross_step_check (trained CNN) as-is.

- camera() is a PLC trigger (ProdTracker.Capture.bStart), already handled by plc.camera().
- step_check calls albatross_step_check.step_check through this module.
- If the module/CNN is missing (or in simulation) or the import fails -> inspection is SKIPPED
  (it never blocks assembly).
- The original blocks on input('Enter') at the console when a mismatch occurs. The GUI has no
  stdin, so we call it with block=False and invoke the on_fail callback (= pause the GUI) instead.

config(vision):
  enabled: true/false
  module_dir: folder containing albatross_step_check.py (added to sys.path)
"""
import os
import sys
import importlib

_MODULE = None
_TRIED = False


def load(cfg=None):
    """Load the albatross_step_check module (once). True on success / False on failure."""
    global _MODULE, _TRIED
    _TRIED = True
    cfg = cfg or {}
    mod_dir = cfg.get("module_dir")
    if mod_dir and os.path.isdir(mod_dir) and mod_dir not in sys.path:
        sys.path.insert(0, mod_dir)
    try:
        _MODULE = importlib.import_module("albatross_step_check")
        return True
    except Exception:
        _MODULE = None
        return False


def make_step_check(cfg=None, on_fail=None, log=print, enabled=True):
    """Build the step_check(part, comp_id, cell_id) callback handed to the assembly loop.

    The returned callback:
      - pass: True
      - mismatch: calls on_fail(part, comp_id, cell_id) (pauses the GUI), then returns the result
      - module/CNN missing or simulation: always True (SKIP)
    """
    cfg = cfg or {}
    if not enabled or not cfg.get("enabled", True):
        return lambda *a, **k: True

    if not _TRIED:
        ok = load(cfg)
        if not ok:
            log("[vision] failed to load albatross_step_check -> skipping vision inspection "
                "(check the module path / syntax errors)")

    mod = _MODULE
    if mod is None:
        return lambda *a, **k: True

    def _check(part, comp_id=None, cell_id=None):
        try:
            # block=False: hand off to the GUI instead of waiting on a console input()
            ok = mod.step_check(part, comp_id=comp_id, cell_id=cell_id, block=False)
        except Exception as e:
            log(f"[vision] step_check error: {e} -> treated as pass")
            return True
        if not ok and on_fail is not None:
            on_fail(part, comp_id, cell_id)     # pause the GUI (wait for user confirmation)
        return ok

    return _check


def notify_done(cfg=None, message="✅ [ALBATROSS] All cells assembled", log=print):
    """Assembly-complete notification — uses the module's notify_done (Slack) if available,
    otherwise just logs."""
    mod = _MODULE
    if mod is None and not _TRIED:
        load(cfg or {})
        mod = _MODULE
    if mod is not None and hasattr(mod, "notify_done"):
        try:
            mod.notify_done(message=message)
            return
        except Exception as e:
            log(f"[vision] notify_done error: {e}")
    log(message)
