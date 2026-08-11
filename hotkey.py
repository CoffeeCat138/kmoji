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


# ── callback registry ──────────────────────────────────────────────────────
_on_trigger = None


def set_callback(fn):
    """Register the function to call when the hotkey triggers."""
    global _on_trigger
    _on_trigger = fn


# ── custom combo parsing ───────────────────────────────────────────────────

# Base-name → set of pynput key objects that count as that modifier.
# (Some keyboards report Key.ctrl instead of Key.ctrl_l/ctrl_r, etc.)
_MODIFIER_KEYS: dict[str, set] = {
    "ctrl": {pynput_keyboard.Key.ctrl, pynput_keyboard.Key.ctrl_l,
             pynput_keyboard.Key.ctrl_r},
    "shift": {pynput_keyboard.Key.shift, pynput_keyboard.Key.shift_l,
              pynput_keyboard.Key.shift_r},
    "alt": {pynput_keyboard.Key.alt, pynput_keyboard.Key.alt_l,
            pynput_keyboard.Key.alt_r},
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
            base = low.replace("_l", "").replace("_r", "")
            if base in _MODIFIER_KEYS:
                # Store the base name; matching uses the full key-set per base.
                modifiers.add(base)
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
_custom_combo_fired = False  # debounce: combo already fired this hold

_enabled = True
_trigger_type = "double_shift"
_custom_combo = ""
_double_interval = 0.5

# Non-modifier keys we've seen pressed (for custom combo detection)
_custom_pressed_normal: set = set()

_WAKE_KEY = None    # for double-tap: a set of pynput Key; for custom: lowercase str
_MOD_KEYS = set()   # for custom combo: the modifier key base names to track


def _normalize_key(key):
    """Return a lowercase string for a pynput key, matching _WAKE_KEY.

    - Char keys (a-z, 0-9, symbols): return lowercase char.
    - Named keys (Key.f5 → "f5", Key.home → "home"): return name.lower().
    - Returns None if the key cannot be normalised.
    """
    if hasattr(key, "char") and key.char is not None:
        return key.char.lower()
    if hasattr(key, "name") and key.name:
        return key.name.lower()
    return None


def _key_matches_wake(key) -> bool:
    """True if *key* matches the current _WAKE_KEY (custom or double-tap mode)."""
    if _trigger_type in ("double_shift", "double_ctrl"):
        # _WAKE_KEY is a set of pynput Key objects
        return _WAKE_KEY and key in _WAKE_KEY
    # custom mode: _WAKE_KEY is a lowercase string; compare normalised forms
    norm = _normalize_key(key)
    return _WAKE_KEY and norm == _WAKE_KEY


def _press_window() -> float:
    """How long (seconds) a recorded press is kept before it is dropped.

    Must be at least as large as the configured double-tap interval, otherwise
    a second press within the configured interval would find the first press
    already evicted and the double-tap would never fire.
    """
    return max(0.5, _double_interval * 2.0)


def _update_runtime_config(config):
    """Pull hotkey settings from the Config instance."""
    global _enabled, _trigger_type, _custom_combo, _double_interval
    global _WAKE_KEY, _MOD_KEYS, _custom_pressed_normal, _custom_combo_fired

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
            _MOD_KEYS = parsed[0]  # set of base modifier names ("ctrl"...)
            _WAKE_KEY = parsed[1].lower()  # normalized: "k", "f5", "home"

    _custom_pressed_normal = set()
    _press_times[:] = []
    _custom_press_cache.clear()
    _custom_combo_fired = False


def update_config(config):
    """Call when configuration changes at runtime (e.g. from GUI)."""
    _update_runtime_config(config)


# ── pynput callbacks ──────────────────────────────────────────────────────

def _on_press(key):
    global _press_times, _last_key_was_target, _custom_press_cache
    global _custom_pressed_normal, _custom_combo_fired

    if not _enabled:
        return

    is_mod = hasattr(key, "name") and key.name in _MODIFIER_NAMES

    # ── custom combo mode ──
    if _trigger_type == "custom" and _MOD_KEYS:
        if is_mod:
            base = key.name.replace("_l", "").replace("_r", "")
            if base in _MOD_KEYS:
                _custom_press_cache.add(base)
                # Modifier arrived — if the normal key is already tracked
                # (user pressed K first, then Ctrl), fire now.
                if (_custom_press_cache == _MOD_KEYS
                        and _WAKE_KEY in _custom_pressed_normal
                        and not _custom_combo_fired):
                    _last_key_was_target = True
                    _custom_combo_fired = True
                    _fire()
        elif _key_matches_wake(key):
            # Always track the normal key, even before modifiers arrive.
            # This lets modifiers arrive after the normal key (e.g. user
            # presses K first then Ctrl).  Plain K without modifiers
            # never fires because the condition gates on all modifiers.
            _custom_pressed_normal.add(_normalize_key(key))
            if (_custom_press_cache == _MOD_KEYS
                    and not _custom_combo_fired):
                _last_key_was_target = True
                _custom_combo_fired = True
                _fire()
        elif not is_mod:
            # Any other non-modifier key resets the normal-key set,
            # preventing a stale entry from earlier typing.
            _custom_pressed_normal.clear()
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
    global _press_times, _last_key_was_target, _custom_press_cache
    global _custom_pressed_normal, _custom_combo_fired

    if not _enabled:
        return

    # ── custom combo cleanup ──
    if _trigger_type == "custom" and _MOD_KEYS:
        is_mod = hasattr(key, "name") and key.name in _MODIFIER_NAMES
        if is_mod:
            base = key.name.replace("_l", "").replace("_r", "")
            _custom_press_cache.discard(base)
            if not _custom_press_cache:
                # All modifiers released — allow the combo to fire again.
                _custom_combo_fired = False
        elif _key_matches_wake(key):
            _custom_pressed_normal.discard(_normalize_key(key))
            if not _custom_pressed_normal:
                # Normal key released — allow re-fire.
                _custom_combo_fired = False
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
