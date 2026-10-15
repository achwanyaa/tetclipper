"""Small fixes for third-party bugs, applied lazily by the stages that need them."""
from __future__ import annotations

import os
import sys


def patch_speechbrain_lazy_imports() -> None:
    """speechbrain 1.1's LazyModule skips imports triggered by inspect.py
    (which walks sys.modules), but checks `filename.endswith("/inspect.py")`,
    which never matches a Windows path. After whisperX has run, an
    inspect-driven walk then forces optional integrations (k2_fsa) to import
    and the next stage dies with "Lazy import of LazyModule(...) failed".
    Treat that case as the AttributeError speechbrain intended. Idempotent;
    a no-op when speechbrain isn't installed."""
    try:
        from speechbrain.utils import importutils
    except Exception:  # noqa: BLE001
        return
    original = importutils.LazyModule.ensure_module
    if getattr(original, "_tetclipper_patched", False):
        return

    def ensure_module(self, stacklevel: int):
        try:
            # One frame deeper than speechbrain expects: this wrapper.
            return original(self, stacklevel + 1)
        except ImportError:
            caller = sys._getframe(stacklevel + 1)
            if os.path.basename(caller.f_code.co_filename) == "inspect.py":
                raise AttributeError(self.target) from None
            raise

    ensure_module._tetclipper_patched = True  # type: ignore[attr-defined]
    importutils.LazyModule.ensure_module = ensure_module
