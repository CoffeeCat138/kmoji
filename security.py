"""API Key storage: keyring → environment → registry → GUI prompt.

Keyring uses Windows Credential Manager when available (no command-line
exposure).  Falls back to writing HKCU\\Environment directly (no setx),
which is still plaintext-in-registry but avoids leaking the key through
process command lines visible via WMI / Process Explorer.
"""
import os
import sys
import tkinter as tk


SERVICE_NAME = "kmoji"
ACCOUNT_NAME = "deepseek_api_key"
ENV_VAR_NAME = "DEEPSEEK_API_KEY"


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def _keyring_get():
    """Return key from OS-level credential store, or None."""
    try:
        import keyring  # noqa: F811
        return keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
    except Exception:
        return None


def _registry_get():
    """Read DEEPSEEK_API_KEY from HKCU\\Environment (fallback storage)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, ENV_VAR_NAME)
            return value
    except FileNotFoundError:
        return None
    except Exception:
        return None


def load_api_key():
    """Return the stored API key (or None).

    Priority:  keyring  →  environment variable  →  registry  →  None.
    """
    # 1. keyring
    val = _keyring_get()
    if val:
        return val

    # 2. environment variable
    val = os.environ.get(ENV_VAR_NAME)
    if val:
        return val

    # 3. Windows registry (HKCU\Environment)
    val = _registry_get()
    if val:
        return val

    return None


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def _keyring_set(api_key: str):
    """Persist via keyring.  Returns True on success."""
    try:
        import keyring
        keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, api_key)
        return True
    except Exception:
        return False


def _registry_set(api_key: str):
    """Write DEEPSEEK_API_KEY to HKCU\\Environment directly.

    This is a plaintext fallback but avoids exposing the key through
    ``setx`` (which places it on the process command line, visible to
    WMI / Process Explorer / ProcMon).  The registry value is also
    readable by any process running as the same user, so it is still a
    plaintext downgrade.
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, ENV_VAR_NAME, 0, winreg.REG_SZ, api_key)
        # Broadcast WM_SETTINGCHANGE so new env-var-aware processes see it.
        import ctypes
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF,   # HWND_BROADCAST
            0x001A,   # WM_SETTINGCHANGE
            0,
            "Environment",
            0x0002,   # SMTO_ABORTIFHUNG
            5000,
            None,
        )
        return True
    except Exception:
        return False


def _registry_delete():
    """Remove the DEEPSEEK_API_KEY value from HKCU\\Environment."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, ENV_VAR_NAME)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def save_api_key(api_key: str, logger=None):
    """Persist *api_key* and also set it in the current process env.

    Tries keyring first; falls back to registry write.
    Returns True on success, False if nothing could be stored.
    """
    os.environ[ENV_VAR_NAME] = api_key
    if not api_key:
        if logger:
            logger.warning("拒绝保存空的 API Key")
        return False

    if _keyring_set(api_key):
        if logger:
            logger.info("API Key 已保存到 Credential Manager（keyring）")
        return True

    if _registry_set(api_key):
        if logger:
            logger.info("API Key 已保存到注册表 HKCU\\Environment（明文降级方案）")
        return True

    if logger:
        logger.error("API Key 保存失败：keyring 与注册表均不可用")
    return False


def clear_api_key(logger=None):
    """Remove the persisted API key from all storage backends."""
    os.environ.pop(ENV_VAR_NAME, None)

    # keyring
    try:
        import keyring
        keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
    except Exception:
        pass

    # registry
    _registry_delete()

    if logger:
        logger.info("API Key 已从所有存储后端清除")


# ---------------------------------------------------------------------------
# GUI prompt
# ---------------------------------------------------------------------------

def prompt_api_key_gui():
    """Show a tkinter dialog asking for the DeepSeek API key.

    Returns the entered key (stripped) or None if cancelled.
    """
    root = tk.Tk()
    root.withdraw()
    dialog = tk.Toplevel(root)
    dialog.title("API Key 配置")
    dialog.attributes("-topmost", True)
    dialog.resizable(False, False)
    dialog.update_idletasks()
    width, height = 420, 130
    screen_w = dialog.winfo_screenwidth()
    screen_h = dialog.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 2
    dialog.geometry(f"{width}x{height}+{x}+{y}")
    dialog.grab_set()

    tk.Label(
        dialog, text="请输入您的 DeepSeek API Key:", font=("微软雅黑", 10)
    ).pack(pady=(12, 5))

    entry_var = tk.StringVar()
    entry = tk.Entry(
        dialog, textvariable=entry_var, show="*", width=44, font=("Consolas", 10)
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

    root.wait_window(dialog)
    root.destroy()
    return result[0]


def mask_key(key: str) -> str:
    """Return a masked representation for display, e.g. 'sk-***abc'."""
    if not key:
        return "未配置"
    if len(key) <= 8:
        return key[:2] + "***" + key[-2:]
    return key[:4] + "***" + key[-4:]
