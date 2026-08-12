"""Hotkey listener with configurable trigger types.

Supports:
- ``double_shift``  – double-tap Shift (default)
- ``double_ctrl``   – double-tap Ctrl

The listener fires ``callback()`` on a daemon thread.
"""
import threading
import time
import unicodedata

from pynput import keyboard as pynput_keyboard


# ── callback registry ──────────────────────────────────────────────────────
_on_trigger = None


def set_callback(fn):
    """Register the function to call when the hotkey triggers."""
    global _on_trigger
    _on_trigger = fn


# ── listener state ─────────────────────────────────────────────────────────

_listener = None
_press_times: list[float] = []
_last_key_was_target = False

_enabled = True
_trigger_type = "double_shift"
_double_interval = 0.5

_WAKE_KEY = None   # a set of pynput Key objects (Shift or Ctrl variants)


def _key_matches_wake(key) -> bool:
    """True if *key* matches the current wake-key set."""
    return _WAKE_KEY and key in _WAKE_KEY


def _press_window() -> float:
    """How long (seconds) a recorded press is kept before it is dropped.

    Must be at least as large as the configured double-tap interval, otherwise
    a second press within the configured interval would find the first press
    already evicted and the double-tap would never fire.
    """
    return max(0.5, _double_interval * 2.0)


def _update_runtime_config(config):
    """Pull hotkey settings from the Config instance."""
    global _enabled, _trigger_type, _double_interval
    global _WAKE_KEY

    _enabled = config.get("hotkey_enabled", True)
    _trigger_type = config.get("trigger_type", "double_shift")
    _double_interval = config.get("double_press_interval", 0.5)

    _WAKE_KEY = None

    if _trigger_type == "double_shift":
        _WAKE_KEY = {pynput_keyboard.Key.shift, pynput_keyboard.Key.shift_l,
                     pynput_keyboard.Key.shift_r}
    elif _trigger_type == "double_ctrl":
        _WAKE_KEY = {pynput_keyboard.Key.ctrl, pynput_keyboard.Key.ctrl_l,
                     pynput_keyboard.Key.ctrl_r}

    _press_times[:] = []


def update_config(config):
    """Call when configuration changes at runtime (e.g. from GUI)."""
    _update_runtime_config(config)


# ── pynput callbacks ──────────────────────────────────────────────────────

def _on_press(key):
    global _press_times, _last_key_was_target

    if not _enabled:
        return

    # ── double-tap mode (shift / ctrl) ──
    if _WAKE_KEY and key in _WAKE_KEY:
        now = time.time()
        # Keep only presses within the configured interval window
        _press_times = [
            t for t in _press_times
            if now - t < _press_window()
        ]
        _press_times.append(now)
        _last_key_was_target = True
    else:
        # Any non-trigger key resets
        _press_times.clear()
        _last_key_was_target = False


def _on_release(key):
    global _press_times, _last_key_was_target

    if not _enabled:
        return

    # ── double-tap mode ──
    if _WAKE_KEY and key in _WAKE_KEY:
        if (_last_key_was_target
                and len(_press_times) >= 2
                and (_press_times[-1] - _press_times[-2]) <= _double_interval):
            # Clear press history so triple-tap doesn't double-fire
            _press_times.clear()
            _last_key_was_target = False
            _fire()
        else:
            _last_key_was_target = False


def _fire():
    """Dispatch trigger callback on a daemon thread.

    Note: This always spawns a new thread even if the previous trigger
    handler is still running.  Callers should implement their own lock
    / throttle to guard against re-entrancy (kmoji.py uses
    ``_hotkey_lock`` which is checked inside the callback itself).
    We intentionally do NOT gate on the caller's lock here because
    hotkey.py has no knowledge of the callback's locking strategy.
    """
    if _on_trigger is None:
        return
    threading.Thread(target=_on_trigger, daemon=True).start()


# ── lifecycle ─────────────────────────────────────────────────────────────

def start(config):
    """Create and start the keyboard listener."""
    global _listener
    _update_runtime_config(config)
    _listener = pynput_keyboard.Listener(on_press=_on_press, on_release=_on_release)
    _listener.start()


def stop():
    """Stop the keyboard listener."""
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None


def is_running():
    return _listener is not None and _listener.is_alive()


def is_punctuation(char):
    """Utility used by the main flow (here to avoid extra module)."""
    return unicodedata.category(char).startswith("P")


def extract_from_cursor_prefix(prefix: str) -> str:
    """Given selected text, return the word after the last punctuation."""
    for i in range(len(prefix) - 1, -1, -1):
        if is_punctuation(prefix[i]):
            return prefix[i + 1:]
    return prefix
