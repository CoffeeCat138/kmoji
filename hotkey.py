"""Hotkey listener with configurable trigger types.

Supports:
- ``double_shift``  – double-tap Shift (default)
- ``double_ctrl``   – double-tap Ctrl
- ``custom``        – user-defined combo read from config

The listener fires ``callback()`` on a daemon thread.
"""
import threading
import time
import unicodedata

from pynput import keyboard as pynput_keyboard


_DOUBLE_PRESS_RECENT_MS = 200  # keep last press for this long max


# ── callback registry ──────────────────────────────────────────────────────
_on_trigger = None


def set_callback(fn):
    """Register the function to call when the hotkey triggers."""
    global _on_trigger
    _on_trigger = fn


# ── custom combo parsing ───────────────────────────────────────────────────

_MODIFIER_MAP: dict[str, pynput_keyboard.Key] = {
    "ctrl": pynput_keyboard.Key.ctrl_l,
    "shift": pynput_keyboard.Key.shift_l,
    "alt": pynput_keyboard.Key.alt_l,
}

_MODIFIER_NAMES = {"ctrl", "ctrl_l", "ctrl_r", "shift", "shift_l", "shift_r",
                   "alt", "alt_l", "alt_r"}


def _parse_custom_combo(combo_str: str):
    """Parse a string like "Ctrl+Shift+K" into (modifiers, main_key).

    Returns (set_of_vkey_strings, main_char_or_Key) or None on parse failure.
    """
    if not combo_str:
        return None
    parts = [p.strip() for p in combo_str.split("+")]
    if not parts:
        return None
    modifiers = set()
    main_key = None
    for p in parts:
        low = p.lower()
        if low in _MODIFIER_NAMES:
            modifiers.add(pynput_keyboard.Key[low] if hasattr(
                pynput_keyboard.Key, low
            ) else low)
        else:
            main_key = p
    if main_key is None:
        # Everything was a modifier – need at least one non-modifier key.
        return None
    return modifiers, main_key


# ── listener state ─────────────────────────────────────────────────────────

_listener = None
_press_times: list[float] = []
_custom_press_cache: set = set()
_last_key_was_target = False

_enabled = True
_trigger_type = "double_shift"
_custom_combo = ""
_double_interval = 0.5

# Non-modifier keys we've seen pressed (for custom combo detection)
_custom_pressed_normal: set = set()

_WAKE_KEY = None    # for double-tap: the pynput key to track
_MOD_KEYS = set()   # for custom combo: the modifier keys to track


def _update_runtime_config(config):
    """Pull hotkey settings from the Config instance."""
    global _enabled, _trigger_type, _custom_combo, _double_interval
    global _WAKE_KEY, _MOD_KEYS, _custom_pressed_normal

    _enabled = config.get("hotkey_enabled", True)
    _trigger_type = config.get("trigger_type", "double_shift")
    _custom_combo = config.get("custom_trigger", "")
    _double_interval = config.get("double_press_interval", 0.5)

    _MOD_KEYS = set()
    _WAKE_KEY = None

    if _trigger_type == "double_shift":
        _WAKE_KEY = {pynput_keyboard.Key.shift, pynput_keyboard.Key.shift_l,
                     pynput_keyboard.Key.shift_r}
    elif _trigger_type == "double_ctrl":
        _WAKE_KEY = {pynput_keyboard.Key.ctrl, pynput_keyboard.Key.ctrl_l,
                     pynput_keyboard.Key.ctrl_r}
    elif _trigger_type == "custom" and _custom_combo:
        parsed = _parse_custom_combo(_custom_combo)
        if parsed:
            _MOD_KEYS = parsed[0]
            _WAKE_KEY = parsed[1]  # the non-modifier key char

    _custom_pressed_normal = set()
    _press_times[:] = []
    _custom_press_cache.clear()


def update_config(config):
    """Call when configuration changes at runtime (e.g. from GUI)."""
    _update_runtime_config(config)


# ── pynput callbacks ──────────────────────────────────────────────────────

def _on_press(key):
    global _press_times, _last_key_was_target, _custom_press_cache
    global _custom_pressed_normal

    if not _enabled:
        return

    is_mod = hasattr(key, "name") and key.name in _MODIFIER_NAMES

    # ── custom combo mode ──
    if _trigger_type == "custom" and _MOD_KEYS:
        if is_mod and key in _MOD_KEYS:
            _custom_press_cache.add(key)
        elif not is_mod and hasattr(key, "char") and key.char == _WAKE_KEY:
            _custom_pressed_normal.add(key.char)
        # Fire when all modifiers + the main key are held together
        if (_custom_press_cache == _MOD_KEYS
                and _WAKE_KEY in _custom_pressed_normal):
            _last_key_was_target = True
            _fire()
            _custom_pressed_normal.discard(_WAKE_KEY)
        return

    # ── double-tap mode (shift / ctrl) ──
    if _WAKE_KEY and key in _WAKE_KEY:
        now = time.time()
        # Keep only presses within a generous recent window
        _press_times = [t for t in _press_times if now - t < _DOUBLE_PRESS_RECENT_MS]
        _press_times.append(now)
        _last_key_was_target = True
    else:
        # Any non-trigger key resets
        _press_times.clear()
        _last_key_was_target = False


def _on_release(key):
    global _press_times, _last_key_was_target, _custom_press_cache
    global _custom_pressed_normal

    if not _enabled:
        return

    # ── custom combo cleanup ──
    if _trigger_type == "custom" and _MOD_KEYS:
        is_mod = hasattr(key, "name") and key.name in _MODIFIER_NAMES
        if is_mod:
            _custom_press_cache.discard(key)
        elif hasattr(key, "char") and key.char == _WAKE_KEY:
            _custom_pressed_normal.discard(key.char)
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
    """Dispatch trigger callback on a daemon thread."""
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
