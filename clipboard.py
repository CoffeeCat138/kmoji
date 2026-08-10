"""Clipboard helpers with TOCTOU protection and robust restore.

Implements:
- Saving/restoring clipboard with validation and try/finally.
- Window-foreground check so we never paste into the wrong window.
"""
import ctypes
import ctypes.wintypes
import os
import sys
import time

import pyperclip
from pynput import keyboard as pynput_keyboard

_LOGGER = None


def _get_logger():
    global _LOGGER
    if _LOGGER is None:
        import logger as _log
        _LOGGER = _log.get_logger()
    return _LOGGER


# ---------------------------------------------------------------------------
# Foreground window helpers (Windows only)
# ---------------------------------------------------------------------------

def _get_foreground_window():
    """Return the current foreground HWND (Windows) or 0."""
    if sys.platform != "win32":
        return 0
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return 0


def _get_window_title(hwnd: int) -> str:
    """Get the window title text for a given HWND."""
    if not hwnd or sys.platform != "win32":
        return ""
    try:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Clipboard save / restore with TOCTOU mitigation
# ---------------------------------------------------------------------------

def _paste_safe():
    """Read clipboard content safely, returning empty string on failure."""
    try:
        return pyperclip.paste()
    except Exception as e:
        _get_logger().warning(f"读取剪贴板失败: {e}")
        return ""


def _copy_safe(data: str):
    """Write to clipboard safely, logging failures."""
    try:
        pyperclip.copy(data)
        return True
    except Exception as e:
        _get_logger().error(f"写入剪贴板失败: {e}")
        return False


def select_text_from_cursor_to_home():
    """Send Shift+Home to select text from cursor to line-start.

    Returns the selected text (from clipboard) or empty string.
    Mitigates TOCTOU by performing the copy and immediately reading back.
    """
    L = _get_logger()
    old = _paste_safe()

    kb = pynput_keyboard.Controller()

    # Select from cursor to line start
    kb.press(pynput_keyboard.Key.ctrl_l)
    kb.press(pynput_keyboard.Key.shift_l)
    kb.press(pynput_keyboard.Key.home)
    kb.release(pynput_keyboard.Key.home)
    kb.release(pynput_keyboard.Key.shift_l)
    kb.release(pynput_keyboard.Key.ctrl_l)

    time.sleep(0.03)  # minimal wait for selection

    # Copy
    kb.press(pynput_keyboard.Key.ctrl_l)
    kb.press("c")
    kb.release("c")
    kb.release(pynput_keyboard.Key.ctrl_l)

    time.sleep(0.03)

    # Read what we copied
    selected = _paste_safe()

    # Move cursor back to end of selection (Right arrow)
    kb.press(pynput_keyboard.Key.right)
    kb.release(pynput_keyboard.Key.right)
    time.sleep(0.02)

    # --- TOCTOU mitigation: verify clipboard didn't change underneath us ---
    verify = _paste_safe()
    if verify != selected:
        L.warning(
            "剪贴板在读取期间被外部修改（TOCTOU）。"
            f" 期望长度={len(selected)}，实际长度={len(verify)}"
        )
        # We can't trust the content, but we still restore old content.
        _copy_safe(old)
        return ""

    # Restore original clipboard
    _copy_safe(old)
    return selected


def paste_kaomoji(kaomoji: str, expected_hwnd: int = 0):
    """Paste *kaomoji* via Ctrl+V ONLY if the foreground window hasn't changed.

    Args:
        kaomoji: The text to paste.
        expected_hwnd: HWND recorded at trigger time; paste is skipped if the
            foreground window no longer matches.

    Returns:
        True if the paste was performed, False if aborted.
    """
    L = _get_logger()

    # --- Window-check: don't paste into the wrong window ---
    if expected_hwnd and sys.platform == "win32":
        current_hwnd = _get_foreground_window()
        if current_hwnd != expected_hwnd:
            current_title = _get_window_title(current_hwnd)
            expected_title = _get_window_title(expected_hwnd)
            L.warning(
                f"粘贴取消：前台窗口已切换。"
                f" 原始='{expected_title}' 当前='{current_title}'"
            )
            return False

    # --- Save → paste → restore, with robust finally ---
    old = _paste_safe()

    try:
        if not _copy_safe(kaomoji):
            return False

        time.sleep(0.02)

        kb = pynput_keyboard.Controller()
        kb.press(pynput_keyboard.Key.ctrl_l)
        kb.press("v")
        kb.release("v")
        kb.release(pynput_keyboard.Key.ctrl_l)

        time.sleep(0.05)
        return True

    finally:
        if not _copy_safe(old):
            L.error(
                "⚠ 剪贴板恢复失败！原剪贴板内容已丢失。"
                f" 原内容长度={len(old)}，"
                f" 已写入日志文件。以下为原内容:\n{old}"
            )


# ---------------------------------------------------------------------------
# Convenience: snapshot foreground and extract prefix in one go
# ---------------------------------------------------------------------------

def extract_prefix():
    """Select text from cursor to line-start, return the text part after the
    last punctuation mark.  Records foreground HWND for later window-check.

    Returns:
        (prefix_text, foreground_hwnd)
    """
    hwnd = _get_foreground_window()
    full_text = select_text_from_cursor_to_home()
    return full_text, hwnd
