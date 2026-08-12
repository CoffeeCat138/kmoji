"""Kmoji configuration management.

Reads/writes config.json from %APPDATA%\\kmoji (Windows) or ~/.kmoji/ (fallback).
"""
import json
import os
import sys

# Injected by kmoji.main() at startup so tray/GUI callbacks can reach the
# live Config instance without circular imports.  Declared here (None) so
# early access before injection fails gracefully instead of AttributeError.
_config_instance = None


DEFAULT_CONFIG = {
    "hotkey_enabled": True,
    "trigger_type": "double_shift",       # double_shift | double_ctrl
    "double_press_interval": 0.5,
    "base_url": "https://api.deepseek.com",  # custom OpenAI-compatible API URL
    "model": "deepseek-v4-flash",             # model name to use
    "logging_enabled": True,
    "log_level": "INFO",
    "log_path": "",                       # empty = use default
}


def get_config_dir():
    """Return the kmoji config directory, creating parents if needed on save."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, "kmoji")
    return os.path.expanduser("~/.kmoji")


def get_config_path():
    return os.path.join(get_config_dir(), "config.json")


def get_default_log_path():
    return os.path.join(get_config_dir(), "kmoji.log")


class Config:
    """Persistent JSON configuration.

    Threading note: all reads/writes touch a shared dict.  The only file I/O
    happens in save().  For an interactive desktop tool, simple dict access is
    enough; we do NOT add locks here to keep things straightforward.
    """

    def __init__(self, path=None):
        self._path = path or get_config_path()
        self._data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        """(Re)load configuration from disk, merging with defaults."""
        self._data = dict(DEFAULT_CONFIG)
        if os.path.isfile(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                # Only accept known keys (prevents injection of junk)
                for k in DEFAULT_CONFIG:
                    if k in loaded:
                        self._data[k] = loaded[k]
            except (json.JSONDecodeError, OSError, TypeError) as exc:
                # Corrupted config – silently keep defaults; logger may not be ready yet
                pass

    def save(self):
        """Persist current configuration to disk."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        """Update a key in-memory and persist immediately."""
        self._data[key] = value
        self.save()

    def all(self):
        """Return a shallow copy of the in-memory dict (read-only view)."""
        return dict(self._data)
