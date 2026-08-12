"""Kmoji — Kaomoji (颜文字) input tool for Windows.

Double-tap Shift or Ctrl → select text behind cursor →
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

_shutting_down = False
_shutdown_lock = threading.Lock()
# _shutting_down is protected by _shutdown_lock because _shutdown() may be
# called from tray menu callback (on pystray loop thread) or from
# KeyboardInterrupt in main()'s finally (on main thread).

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

def _refresh_tray_from_config(cfg):
    """根据 config 刷新托盘 tooltip 和菜单。

    cfg 为 None 时直接返回（尚未初始化）。
    """
    if cfg is None:
        return
    _tray.update_tray_tooltip(cfg)
    _tray.update_tray_menu(cfg, _toggle_enabled, _show_settings, _do_quit)


def _toggle_enabled():
    """Toggle hotkey enabled flag and update tray + GUI."""
    cfg = _config._config_instance
    current = cfg.get("hotkey_enabled", True)
    cfg.set("hotkey_enabled", not current)
    _hotkey.update_config(cfg)
    _refresh_tray_from_config(cfg)
    L = _logger.get_logger()
    L.info(f"已{'禁用' if current else '启用'}")


def _sync_tray_from_hotkey():
    """读取当前 config 并刷新托盘 tooltip 和菜单。

    此函数作为回调注入到 SettingsWindow._on_hotkey_state_change，
    当用户在设置窗口切换「启用」复选框时触发，保证托盘图标状态
    与设置界面实时同步。
    """
    _refresh_tray_from_config(_config._config_instance)


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
            # 注入托盘同步回调：设置窗口切换启用状态后自动刷新托盘图标
            gui_obj._on_hotkey_state_change = _sync_tray_from_hotkey
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
    """Clean shutdown sequence (idempotent, thread-safe).

    This function may be called from multiple threads (tray menu callback
    on pystray loop thread, or main()'s finally after Ctrl+C on main
    thread).  The re-entrancy guard ensures the real shutdown work happens
    at most once.

    IMPORTANT: pystray's icon.stop() must be called from a thread OTHER than
    the one currently running the pystray message loop (which is the main
    thread when run_tray() is blocking).  If stop() is called from within a
    pystray menu callback (which runs on the same loop thread), it deadlocks
    because stop() posts WM_QUIT and then waits for the loop to exit, but the
    loop can't exit while it's still processing the callback.

    We therefore spawn a short-lived daemon thread to call stop_tray() so
    that the main thread's run_tray() can return cleanly.
    """
    global _shutting_down
    with _shutdown_lock:
        if _shutting_down:
            return
        _shutting_down = True

    L = _logger.get_logger()
    L.info("正在关闭…")

    _hotkey.stop()

    # _settings_win lives on its own daemon thread.  Calling destroy() from
    # here is a cross-thread tkinter operation.  We mitigate the risk by:
    #  - using root.after_idle(0, root.destroy) to schedule destruction on
    #    the correct thread (if the window object is still alive), and
    #  - wrapping the whole thing in try/except as a safety net.
    if _settings_win:
        try:
            _settings_win.root.after_idle(_settings_win.root.destroy)
            _settings_win.root.update_idletasks()
        except Exception:
            pass
    _logger.log_shutdown()

    # Call stop_tray() from a different thread to avoid deadlocking with
    # pystray's own message loop (see docstring above).
    _tray.stop_tray_from_thread()


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
