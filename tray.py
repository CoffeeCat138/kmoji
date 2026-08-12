"""System tray module (pystray + Pillow).

Architecture note for Windows:
-  pystray.run() must run on the main thread because it owns the Windows
   message loop.  We therefore start the keyboard listener on a daemon
   background thread, then call tray.run() which blocks.
-  The tkinter settings window runs on the main thread too, but pystray
   and tkinter vying for the same message loop can deadlock.  We work
   around this by calling root.update() in a periodic timer rather than
   root.mainloop().  When the settings window is shown, we pump its
   events from the tray's main-loop via pystray's .after() or from a
   dedicated thread.
-  Alternative approach (used here): show the tkinter window in a
   SEPARATE thread.  On Windows, tkinter can work from a non-main
   thread as long as we are careful about COM initialisation (which
   pystray already does).  This has proved the most stable arrangement.
"""
import threading


_ICON_HEIGHT = 64
_ICON_WIDTH = 64

_tray_icon = None


# ── icon drawing ───────────────────────────────────────────────────────────

def _make_icon_image():
    """Create a simple 64×64 icon with Pillow (coloured circle + '颜' char)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (_ICON_WIDTH, _ICON_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle
    margin = 4
    draw.ellipse(
        [margin, margin, _ICON_WIDTH - margin, _ICON_HEIGHT - margin],
        fill=(255, 107, 157),  # warm pink
    )

    # Character "颜"
    try:
        font = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", 36)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 30)
        except (OSError, IOError):
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "颜", font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        ((_ICON_WIDTH - tw) / 2, (_ICON_HEIGHT - th) / 2 - 2),
        "颜",
        fill=(255, 255, 255),
        font=font,
    )

    return img


# ── tray setup ─────────────────────────────────────────────────────────────

def _build_tooltip(config, enabled):
    """Create dynamic tooltip text."""
    trigger = config.get("trigger_type", "double_shift")
    trigger_names = {
        "double_shift": "双击Shift",
        "double_ctrl": "双击Ctrl",
    }
    tr_name = trigger_names.get(trigger, trigger)
    state = "已启用" if enabled else "已禁用"
    return f"Kmoji 运行中 · 快捷键:{tr_name} · {state}"


def _build_menu(config, toggle_enabled_cb, show_settings_cb, quit_cb):
    """Return a pystray Menu."""
    from pystray import Menu, MenuItem

    def _toggle(icon=None, item=None):
        toggle_enabled_cb()

    def _settings(icon=None, item=None):
        show_settings_cb()

    def _quit(icon=None, item=None):
        quit_cb()

    return Menu(
        MenuItem("设置", _settings, default=True),
        MenuItem(
            lambda _: "✓ 已启用" if config.get("hotkey_enabled")
            else "   已禁用",
            _toggle,
        ),
        Menu.SEPARATOR,
        MenuItem("退出", _quit),
    )


# ── public API ─────────────────────────────────────────────────────────────

def create_tray(config, toggle_enabled_cb, show_settings_cb, quit_cb):
    """Create the pystray Icon (does NOT start the loop yet)."""
    import pystray
    global _tray_icon

    img = _make_icon_image()
    menu = _build_menu(config, toggle_enabled_cb, show_settings_cb, quit_cb)

    _tray_icon = pystray.Icon(
        "kmoji", img,
        menu=menu,
        title=_build_tooltip(config, config.get("hotkey_enabled", True)),
    )


def update_tray_tooltip(config):
    """Update the tray tooltip text (call after config changes)."""
    if _tray_icon:
        _tray_icon.title = _build_tooltip(
            config, config.get("hotkey_enabled", True)
        )


def update_tray_menu(config, toggle_enabled_cb, show_settings_cb, quit_cb):
    """Rebuild the tray menu (e.g. after toggling enabled)."""
    if _tray_icon:
        _tray_icon.menu = _build_menu(
            config, toggle_enabled_cb, show_settings_cb, quit_cb,
        )


def run_tray():
    """Enter the pystray main loop (BLOCKING). Must be called from main thread."""
    if _tray_icon:
        _tray_icon.run()


def stop_tray():
    """Stop the tray loop from another thread.

    IMPORTANT: Never call this from inside a pystray menu callback or from
    the same thread that is running run_tray() — that will deadlock.
    Prefer stop_tray_from_thread() for production use; this function is
    kept for backwards compatibility.
    """
    if _tray_icon:
        _tray_icon.stop()


def stop_tray_from_thread():
    """Safe wrapper: always stop the tray loop from a separate daemon thread.

    This prevents the deadlock that occurs when icon.stop() is called from
    within a pystray callback (which runs on the same thread as the message
    loop).  The separate thread can safely post WM_QUIT to the main thread's
    message loop.
    """
    global _tray_icon
    if _tray_icon is None:
        return

    def _stop_target():
        try:
            _tray_icon.stop()
        except Exception:
            pass  # icon may already be stopped, suppress noise

    t = threading.Thread(target=_stop_target, daemon=True)
    t.start()
    # Give the daemon thread a moment to post WM_QUIT so run_tray() returns.
    t.join(timeout=2.0)
    _tray_icon = None
