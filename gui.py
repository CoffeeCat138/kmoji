"""Settings GUI (tkinter).

Provides:
- Startup toggle (read/write HKCU Run key)
- Hotkey enable/disable switch
- Trigger type selection (double-Shift / double-Ctrl)
- Logging settings (enabled, level, path, open-dir, recent-logs)
- API base URL and model configuration
- API Key management (masked display, re-enter, clear)
"""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

import config as _cfg_module
import hotkey as _hotkey_module
import logger as _logger_module
import security as _security_module


_STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_VALUE = "kmoji"


# ── helpers ────────────────────────────────────────────────────────────────

def _startup_status():
    """Return (enabled: bool, path: str)."""
    if sys.platform != "win32":
        return False, ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0,
                            winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, _STARTUP_VALUE)
            return True, value
    except FileNotFoundError:
        return False, ""
    except Exception:
        return False, ""


def _startup_set(enable: bool):
    """Add or remove the kmoji value in HKCU Run."""
    if sys.platform != "win32":
        return
    import winreg
    try:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0,
                                 winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        except FileNotFoundError:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _STARTUP_KEY)

        if enable:
            exe_path = os.path.abspath(sys.executable)
            winreg.SetValueEx(key, _STARTUP_VALUE, 0, winreg.REG_SZ, exe_path)
        else:
            try:
                winreg.DeleteValue(key, _STARTUP_VALUE)
            except FileNotFoundError:
                pass
        key.Close()
    except Exception as e:
        print(f"[Kmoji] 开机自启动设置失败: {e}")
        messagebox.showerror("开机自启动", f"设置开机自启动失败:\n{e}")


# ── Main window ────────────────────────────────────────────────────────────

class SettingsWindow:
    """Modal or semi-modal settings window for Kmoji."""

    def __init__(self, cfg: _cfg_module.Config, on_close=None):
        self.cfg = cfg
        self._on_close = on_close
        self._on_key_change = None  # set externally by caller

        self.root = tk.Tk()
        self.root.title("Kmoji 设置")
        self.root.resizable(False, False)

        # Don't destroy root when window is closed; just withdraw so we can
        # re-show the same window from the tray.
        self.root.protocol("WM_DELETE_WINDOW", self._hide)

        self._build()
        self._center()

    # ── layout ────────────────────────────────────────────────────────

    def _build(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self._page_startup = ttk.Frame(nb)
        self._page_hotkey = ttk.Frame(nb)
        self._page_model = ttk.Frame(nb)
        self._page_log = ttk.Frame(nb)

        nb.add(self._page_startup, text="启动")
        nb.add(self._page_hotkey, text="快捷键")
        nb.add(self._page_model, text="模型")
        nb.add(self._page_log, text="日志")

        self._build_startup()
        self._build_hotkey()
        self._build_model()
        self._build_log()

    def _build_startup(self):
        f = ttk.Labelframe(self._page_startup, text="开机自启动", padding=10)
        f.pack(fill=tk.X, padx=10, pady=10)

        self._startup_var = tk.BooleanVar()
        enabled, exe_path = _startup_status()
        self._startup_var.set(enabled)

        cb = ttk.Checkbutton(
            f, text="开机时自动启动 Kmoji",
            variable=self._startup_var,
            command=self._toggle_startup,
        )
        cb.pack(anchor=tk.W)

        self._startup_label = ttk.Label(
            f, text=f"当前: {'已启用' if enabled else '未启用'}"
            + (f"  ({exe_path})" if exe_path else ""),
            foreground="gray",
        )
        self._startup_label.pack(anchor=tk.W, pady=(4, 0))

    def _build_hotkey(self):
        f = ttk.Labelframe(self._page_hotkey, text="快捷键设置", padding=10)
        f.pack(fill=tk.X, padx=10, pady=10)

        # -- enable/disable --
        self._hotkey_enabled_var = tk.BooleanVar(
            value=self.cfg.get("hotkey_enabled", True)
        )
        cb = ttk.Checkbutton(
            f, text="启用",
            variable=self._hotkey_enabled_var,
            command=self._save_hotkey,
        )
        cb.pack(anchor=tk.W)

        # -- trigger type --
        trigger_frame = ttk.Frame(f)
        trigger_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(trigger_frame, text="触发方式:").pack(side=tk.LEFT)

        self._trigger_var = tk.StringVar(value=self.cfg.get("trigger_type"))
        opts = ttk.Combobox(
            trigger_frame,
            textvariable=self._trigger_var,
            values=["double_shift", "double_ctrl"],
            state="readonly",
            width=15,
        )
        opts.pack(side=tk.LEFT, padx=6)
        opts.bind("<<ComboboxSelected>>", lambda e: self._save_hotkey())

        # -- interval --
        intv_frame = ttk.Frame(f)
        intv_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(intv_frame, text="双击间隔 (秒):").pack(side=tk.LEFT)
        self._interval_var = tk.DoubleVar(
            value=self.cfg.get("double_press_interval", 0.5)
        )
        spin = ttk.Spinbox(
            intv_frame,
            textvariable=self._interval_var,
            from_=0.1, to=2.0, increment=0.1, width=6,
        )
        spin.pack(side=tk.LEFT, padx=6)
        spin.bind("<FocusOut>", lambda e: self._save_hotkey())
        self._interval_spin = spin

    def _build_model(self):
        f = ttk.Labelframe(self._page_model, text="模型设置", padding=10)
        f.pack(fill=tk.X, padx=10, pady=10)

        # -- API base URL --
        url_frame = ttk.Frame(f)
        url_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(url_frame, text="API 地址 (Base URL):").pack(side=tk.LEFT)
        self._model_url_var = tk.StringVar(
            value=self.cfg.get("base_url") or "https://api.deepseek.com"
        )
        url_entry = ttk.Entry(url_frame, textvariable=self._model_url_var, width=48)
        url_entry.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        url_entry.bind("<FocusOut>", lambda e: self._save_model())

        # -- model name --
        model_frame = ttk.Frame(f)
        model_frame.pack(fill=tk.X)
        ttk.Label(model_frame, text="模型名称:").pack(side=tk.LEFT)
        self._model_var = tk.StringVar(
            value=self.cfg.get("model") or "deepseek-v4-flash"
        )
        model_entry = ttk.Entry(model_frame, textvariable=self._model_var, width=48)
        model_entry.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        model_entry.bind("<FocusOut>", lambda e: self._save_model())

        ttk.Label(
            f,
            text="支持任意 OpenAI 兼容接口（如 DeepSeek、本地 Ollama 等）。"
            "修改后会自动重建客户端。",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(8, 0))

        # -- API Key management (moved from dedicated tab) --
        key_frame = ttk.Labelframe(
            self._page_model, text="API Key 管理", padding=10
        )
        key_frame.pack(fill=tk.X, padx=10, pady=(6, 10))

        current_key = _security_module.load_api_key()
        masked = _security_module.mask_key(current_key)
        self._apikey_label = ttk.Label(key_frame, text=f"当前 Key: {masked}")
        self._apikey_label.pack(anchor=tk.W)

        btn_frame = ttk.Frame(key_frame)
        btn_frame.pack(pady=(8, 0))
        ttk.Button(
            btn_frame, text="重新输入", command=self._re_enter_key
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            btn_frame, text="清除 Key", command=self._clear_key
        ).pack(side=tk.LEFT)

    def _build_log(self):
        f = ttk.Labelframe(self._page_log, text="日志设置", padding=10)
        f.pack(fill=tk.X, padx=10, pady=10)

        # -- enable --
        self._log_enabled_var = tk.BooleanVar(
            value=self.cfg.get("logging_enabled", True)
        )
        cb = ttk.Checkbutton(
            f, text="启用日志文件",
            variable=self._log_enabled_var,
            command=self._save_log,
        )
        cb.pack(anchor=tk.W)

        # -- level --
        level_frame = ttk.Frame(f)
        level_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(level_frame, text="日志级别:").pack(side=tk.LEFT)
        self._log_level_var = tk.StringVar(value=self.cfg.get("log_level", "INFO"))
        lvl = ttk.Combobox(
            level_frame,
            textvariable=self._log_level_var,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            state="readonly",
            width=10,
        )
        lvl.pack(side=tk.LEFT, padx=6)
        lvl.bind("<<ComboboxSelected>>", lambda e: self._save_log())

        # -- path --
        path_frame = ttk.Frame(f)
        path_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(path_frame, text="日志路径:").pack(side=tk.LEFT)
        default_path = _logger_module._get_default_log_path()
        self._log_path_var = tk.StringVar(
            value=self.cfg.get("log_path") or default_path
        )
        path_entry = ttk.Entry(path_frame, textvariable=self._log_path_var, width=40)
        path_entry.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        path_entry.bind("<FocusOut>", lambda e: self._save_log())

        # -- buttons --
        btn_frame = ttk.Frame(f)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(
            btn_frame, text="打开日志目录", command=self._open_log_dir
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            btn_frame, text="查看最近日志", command=self._view_recent_log
        ).pack(side=tk.LEFT)

    # ── actions ───────────────────────────────────────────────────────

    def _toggle_startup(self):
        enable = self._startup_var.get()
        _startup_set(enable)
        status, path = _startup_status()
        self._startup_label.configure(
            text=f"当前: {'已启用' if enable else '未启用'}"
            + (f"  ({path})" if path else "")
        )

    def _save_hotkey(self, *_):
        self.cfg.set("hotkey_enabled", self._hotkey_enabled_var.get())
        self.cfg.set("trigger_type", self._trigger_var.get())
        self.cfg.set("double_press_interval", self._interval_var.get())
        # Push to hotkey module for live update
        _hotkey_module.update_config(self.cfg)

    # ── model actions ─────────────────────────────────────────────────

    def _save_model(self, *_):
        """Persist base_url and model, then rebuild the OpenAI client."""
        url = (self._model_url_var.get() or "").strip()
        model = (self._model_var.get() or "").strip()
        self.cfg.set("base_url", url)
        self.cfg.set("model", model)
        if hasattr(self, "_on_api_config_change") and self._on_api_config_change:
            self._on_api_config_change()

    def _save_log(self, *_):
        self.cfg.set("logging_enabled", self._log_enabled_var.get())
        self.cfg.set("log_level", self._log_level_var.get())
        path_val = self._log_path_var.get()
        if path_val:
            self.cfg.set("log_path", path_val)
        _logger_module.reconfigure(self.cfg)

    def _open_log_dir(self):
        log_path = self._log_path_var.get()
        log_dir = os.path.dirname(log_path)
        if os.path.isdir(log_dir):
            if sys.platform == "win32":
                os.startfile(log_dir)
            elif sys.platform == "darwin":
                subprocess.run(["open", log_dir])
            else:
                subprocess.run(["xdg-open", log_dir])

    def _view_recent_log(self):
        log_path = self._log_path_var.get()
        if os.path.isfile(log_path):
            if sys.platform == "win32":
                os.startfile(log_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-t", log_path])
            else:
                subprocess.run(["xdg-open", log_path])
        else:
            messagebox.showinfo("日志", "日志文件尚未生成。")

    # ── API Key actions ───────────────────────────────────────────────

    def _prompt_key_dialog(self):
        """Show an inline API-key input dialog as a child Toplevel.

        Uses self.root as parent so we avoid creating a second Tk()
        instance, which would conflict with the existing mainloop.
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("API Key 配置")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.update_idletasks()
        width, height = 420, 130
        screen_w = dialog.winfo_screenwidth()
        screen_h = dialog.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        tk.Label(
            dialog, text="请输入您的 DeepSeek API Key:", font=("微软雅黑", 10)
        ).pack(pady=(12, 5))

        entry_var = tk.StringVar()
        entry = tk.Entry(
            dialog, textvariable=entry_var, show="*", width=44,
            font=("Consolas", 10)
        )
        entry.pack(pady=5)
        entry.focus_set()

        result = [None]

        def on_ok():
            result[0] = entry_var.get().strip()
            dialog.destroy()

        def on_cancel():
            result[0] = None
            dialog.destroy()

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="确定", width=10, command=on_ok).pack(
            side=tk.LEFT, padx=10
        )
        tk.Button(btn_frame, text="取消", width=10, command=on_cancel).pack(
            side=tk.LEFT, padx=10
        )

        dialog.bind("<Return>", lambda e: on_ok())
        dialog.bind("<Escape>", lambda e: on_cancel())

        self.root.wait_window(dialog)
        return result[0]

    def _re_enter_key(self):
        new_key = self._prompt_key_dialog()
        if new_key:
            _security_module.save_api_key(new_key, logger=_logger_module.get_logger())
            masked = _security_module.mask_key(new_key)
            self._apikey_label.configure(text=f"当前 Key: {masked}")
            # Re-init the OpenAI client (delegated to main module)
            if hasattr(self, "_on_key_change") and self._on_key_change:
                self._on_key_change(new_key)

    def _clear_key(self):
        if not messagebox.askyesno("确认", "确定要清除已保存的 API Key 吗？"):
            return
        _security_module.clear_api_key(logger=_logger_module.get_logger())
        self._apikey_label.configure(text="当前 Key: 未配置")

    # ── window management ─────────────────────────────────────────────

    def _center(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"+{x}+{y}")

    def _hide(self):
        """Hide instead of destroy — the window stays alive for re-show."""
        self.root.withdraw()

    def show(self):
        """Bring the hidden window back to front and refresh all pages."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        # Refresh startup status
        enabled, path = _startup_status()
        self._startup_var.set(enabled)
        self._startup_label.configure(
            text=f"当前: {'已启用' if enabled else '未启用'}"
            + (f"  ({path})" if path else "")
        )
        # Refresh hotkey page (may have changed via tray menu)
        self._hotkey_enabled_var.set(self.cfg.get("hotkey_enabled", True))
        self._trigger_var.set(self.cfg.get("trigger_type", "double_shift"))
        self._interval_var.set(self.cfg.get("double_press_interval", 0.5))
        # Refresh log page (may have changed via tray menu / other windows)
        self._log_enabled_var.set(self.cfg.get("logging_enabled", True))
        self._log_level_var.set(self.cfg.get("log_level", "INFO"))
        default_path = _logger_module._get_default_log_path()
        self._log_path_var.set(self.cfg.get("log_path") or default_path)
        # Refresh model page
        self._model_url_var.set(self.cfg.get("base_url"))
        self._model_var.set(self.cfg.get("model"))
        # Refresh API key
        current_key = _security_module.load_api_key()
        self._apikey_label.configure(
            text=f"当前 Key: {_security_module.mask_key(current_key)}"
        )

    def run(self):
        """Enter the tkinter main loop (blocking)."""
        self.root.mainloop()

    def destroy(self):
        """Explicitly destroy the tkinter root."""
        try:
            self.root.destroy()
        except Exception:
            pass
