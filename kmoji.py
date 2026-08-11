"""Kmoji — Kaomoji (颜文字) input tool for Windows.

Double-tap Shift (or customisable hotkey) → select text behind cursor →
call DeepSeek API for kaomoji → paste via Ctrl+V.

Usage:
    python kmoji.py               # normal (background, tray icon)
    python kmoji.py --test | -t   # debug mode (console output)
    python kmoji.py --settings    # open settings window and exit
"""
import sys
import threading
import time

from openai import OpenAI

import clipboard as _clipboard
import config as _config
import hotkey as _hotkey
import logger as _logger
import security as _security
import gui as _gui
import tray as _tray

# ── constants ──────────────────────────────────────────────────────────────

# Backwards-compatible defaults; overridable via config (base_url / model).
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
SYSTEM_PROMPT = (
    "你是可爱颜文字设计师。只输出根据用户文字情感定制的全新颜文字，"
    "不含任何其他内容，只能使用在iOS、安卓、Windows三端都能正常显示的符号，"
    "不输出解释、空格、换行。"
)


def _effective_base_url() -> str:
    """Return configured base URL (falling back to the DeepSeek default)."""
    cfg = _config._config_instance
    if cfg is not None:
        url = cfg.get("base_url") or DEFAULT_BASE_URL
        if url.strip():
            return url.strip()
    return DEFAULT_BASE_URL


def _effective_model() -> str:
    """Return configured model name (falling back to the DeepSeek default)."""
    cfg = _config._config_instance
    if cfg is not None:
        model = cfg.get("model") or DEFAULT_MODEL
        if model.strip():
            return model.strip()
    return DEFAULT_MODEL

# ── module-level state ─────────────────────────────────────────────────────
# Plain globals (NOT thread-local): hotkey handler runs on daemon threads
# but needs access to the same client and settings window references.

_client = None
_settings_win = None
_settings_win_lock = threading.Lock()
_client_lock = threading.Lock()

# Snapshot of the API key/URL/model used to build *_client* — lets us rebuild
# the client if any of them change between hotkey invocations.
_client_key = None
_client_base_url = None
_client_model = None


# ── hide console window (Windows) ──────────────────────────────────────────

def _hide_console():
    """Hide the terminal window when not in debug mode."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)
    except Exception:
        pass  # best-effort


# ── client management ──────────────────────────────────────────────────────

def _get_client():
    """Return the OpenAI client, creating it lazily if needed.

    Safe to call from any thread; uses a lock so concurrent hotkey triggers
    don't create two clients.  If no API key is configured we do NOT pop a
    tkinter dialog from a background thread — we just return None and let
    the caller log/abort.  The GUI prompt only ever happens on the main
    thread at startup.

    Also detects when the stored API key has changed (e.g. via GUI), in
    which case the client is transparently rebuilt.
    """
    global _client, _client_key, _client_base_url, _client_model
    with _client_lock:
        api_key = _security.load_api_key()
        if not api_key:
            _client = None
            _client_key = None
            return None
        # Track URL+model too, so a config change also rebuilds the client.
        base_url = _effective_base_url()
        model = _effective_model()
        if (_client is not None and api_key == _client_key
                and _client_base_url == base_url and _client_model == model):
            return _client
        # Key, URL or model changed / client didn't exist — build fresh.
        _client = OpenAI(api_key=api_key, base_url=base_url)
        _client_key = api_key
        _client_base_url = base_url
        _client_model = model
        return _client


def _reinit_client(new_key: str):
    """Called from settings GUI after user changes the API key."""
    global _client, _client_key, _client_base_url, _client_model
    with _client_lock:
        _client = OpenAI(
            api_key=new_key,
            base_url=_effective_base_url(),
        )
        _client_key = new_key
        _client_base_url = _effective_base_url()
        _client_model = _effective_model()


def _reinit_client_from_config():
    """Called from settings GUI after URL/model config changes.

    Re-reads the API key from storage and rebuilds the client with the
    updated base_url / model from config.
    """
    api_key = _security.load_api_key()
    if api_key:
        _reinit_client(api_key)


# ── API call ───────────────────────────────────────────────────────────────

def _get_kaomoji(user_text: str) -> str:
    """Call DeepSeek to generate a kaomoji for *user_text*."""
    L = _logger.get_logger()
    L.info(f"API 调用: 输入文本长度={len(user_text)}")
    try:
        client = _get_client()
        if client is None:
            L.error("API 调用失败: 未配置 API Key")
            return ""
        response = client.chat.completions.create(
            model=_effective_model(),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
            timeout=10,
        )
        result = response.choices[0].message.content.strip()
        L.info(f"API 返回: 长度={len(result)}")
        return result
    except Exception as exc:
        L.error(f"API 调用失败: {exc}")
        return ""


# ── hotkey handler ─────────────────────────────────────────────────────────

# Lock to prevent re-entrant hotkey triggers while an API call is in-flight.
_hotkey_lock = threading.Lock()


def _handle_hotkey():
    """Called when the configured hotkey is triggered."""
    L = _logger.get_logger()
    L.info("快捷键触发")

    if not _hotkey_lock.acquire(blocking=False):
        L.info("上一次快捷键尚未完成，忽略本次触发")
        return

    try:
        # Step 1: extract text from cursor position
        full_text, trigger_hwnd = _clipboard.extract_prefix()
        text = _hotkey.extract_from_cursor_prefix(full_text)
        if not text:
            L.info("光标前无有效文字，跳过")
            return
        L.info(f"提取文字: 长度={len(text)}")
        # Step 2: get kaomoji from API
        kaomoji = _get_kaomoji(text)
        if not kaomoji:
            L.info("API 未返回有效颜文字，跳过")
            return

        # Step 3: paste, but only if foreground window hasn't changed
        ok = _clipboard.paste_kaomoji(kaomoji, expected_hwnd=trigger_hwnd)
        if ok:
            L.info("颜文字已粘贴")
    except Exception as exc:
        L.error(f"处理快捷键时发生异常: {type(exc).__name__}: {exc}")
    finally:
        _hotkey_lock.release()


# ── tray callbacks ─────────────────────────────────────────────────────────

def _toggle_enabled():
    """Toggle hotkey enabled flag and update tray + GUI."""
    cfg = _config._config_instance
    current = cfg.get("hotkey_enabled", True)
    cfg.set("hotkey_enabled", not current)
    _hotkey.update_config(cfg)
    _tray.update_tray_tooltip(cfg)
    _tray.update_tray_menu(
        cfg, _toggle_enabled, _show_settings, _do_quit
    )
    L = _logger.get_logger()
    L.info(f"快捷键已{'禁用' if current else '启用'}")


def _show_settings():
    """Show (or create) the settings window.

    We launch tkinter from a dedicated daemon thread so it doesn't
    block the pystray message loop running on the main thread.  On
    Windows tkinter works fine from a non-main thread.  A lock prevents
    double-creation when the tray icon is double-clicked quickly.
    """
    global _settings_win

    with _settings_win_lock:
        if _settings_win is not None:
            try:
                _settings_win.show()
                return
            except Exception:
                _settings_win = None

        def _run_gui():
            global _settings_win
            cfg = _config._config_instance
            gui_obj = _gui.SettingsWindow(cfg)
            gui_obj._on_key_change = _reinit_client
            gui_obj._on_api_config_change = _reinit_client_from_config
            with _settings_win_lock:
                _settings_win = gui_obj
            gui_obj.run()
            # After mainloop exits (window destroyed), clear the reference.
            with _settings_win_lock:
                if _settings_win is gui_obj:
                    _settings_win = None

        t = threading.Thread(target=_run_gui, daemon=True)
        t.start()


def _do_quit():
    """Quit immediately — no double-click confirmation needed."""
    _logger.get_logger().info("用户选择退出")
    _shutdown()


def _shutdown():
    """Clean shutdown sequence."""
    L = _logger.get_logger()
    L.info("正在关闭…")

    _hotkey.stop()
    if _settings_win:
        try:
            _settings_win.destroy()
        except Exception:
            pass
    _logger.log_shutdown()
    _tray.stop_tray()


# ── main ───────────────────────────────────────────────────────────────────

def main():
    """Application entry point."""
    global _client

    # Parse flags
    debug_mode = "-t" in sys.argv or "--test" in sys.argv

    if "--settings" in sys.argv:
        # Just open settings and exit (useful for shortcuts)
        cfg = _config.Config()
        _logger.init_logger(cfg)
        gui_obj = _gui.SettingsWindow(cfg)
        gui_obj.run()
        return

    # 1. Config
    cfg = _config.Config()
    # Expose globally so tray callbacks can reach it without circular imports
    _config._config_instance = cfg

    # 2. Logger
    _logger.init_logger(cfg)
    _logger.log_startup()
    L = _logger.get_logger()

    # 3. Hide console (non-debug)
    if not debug_mode:
        _hide_console()

    # 4. API Key
    api_key = _security.load_api_key()
    if not api_key:
        L.info("未找到 API Key，弹出输入窗口…")
        api_key = _security.prompt_api_key_gui()
        if not api_key:
            L.warning("未提供 API Key，退出")
            _logger.log_shutdown()
            sys.exit(0)
        _security.save_api_key(api_key, logger=L)

    # Initialise client eagerly so connection issues surface early
    _client = OpenAI(api_key=api_key, base_url=_effective_base_url())
    _client_key = api_key
    _client_base_url = _effective_base_url()
    _client_model = _effective_model()

    # 5. Start hotkey listener
    _hotkey.set_callback(_handle_hotkey)
    _hotkey.start(cfg)
    L.info(
        f"键盘监听已启动 (触发方式={cfg.get('trigger_type')},启用="
        f"{cfg.get('hotkey_enabled')})"
    )

    # 6. Tray icon
    _tray.create_tray(
        cfg,
        toggle_enabled_cb=_toggle_enabled,
        show_settings_cb=_show_settings,
        quit_cb=_do_quit,
    )

    # 7. Enter tray loop (blocking — main thread)
    L.info("系统托盘已就绪")
    try:
        _tray.run_tray()
    except KeyboardInterrupt:
        L.info("捕获到 KeyboardInterrupt")
    finally:
        _shutdown()


if __name__ == "__main__":
    main()
