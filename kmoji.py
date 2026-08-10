import os
import sys
import subprocess
import threading
import time
import unicodedata
import ctypes
import tkinter as tk
import winreg

from pynput import keyboard as pynput_keyboard
import pyperclip
from openai import OpenAI

ENV_VAR_NAME = "DEEPSEEK_API_KEY"
MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"
DOUBLE_PRESS_INTERVAL = 0.5
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE_NAME = "kmoji"

SYSTEM_PROMPT = """你是可爱颜文字设计师。只输出根据用户文字情感定制的全新颜文字，不含任何其他内容，只能使用在iOS、安卓、Windows三端都能正常显示的符号，不输出解释、空格、换行。"""

api_key = None
client = None
hotkey_lock = threading.Lock()
DEBUG = False

shift_press_times = []
last_key_was_shift = False
listener = None

def log(msg):
    if DEBUG:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def hide_console():
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                user32.ShowWindow(hwnd, 0)
        except:
            pass

def add_to_startup():
    try:
        exe_path = os.path.abspath(sys.executable)
        if not os.path.isfile(exe_path):
            log("无法获取可执行文件路径，跳过自启动注册")
            return
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ) as key:
            try:
                existing, _ = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
                if os.path.normcase(existing) == os.path.normcase(exe_path):
                    log("自启动项已存在，无需重复添加")
                    return
            except FileNotFoundError:
                pass
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, exe_path)
            log("已添加至开机自启动")
    except Exception as e:
        log(f"添加自启动失败: {e}")

def get_api_key_from_user():
    root = tk.Tk()
    root.withdraw()
    dialog = tk.Toplevel(root)
    dialog.title("API Key 配置")
    dialog.attributes('-topmost', True)
    dialog.resizable(False, False)
    dialog.update_idletasks()
    width, height = 400, 120
    screen_w = dialog.winfo_screenwidth()
    screen_h = dialog.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 2
    dialog.geometry(f"{width}x{height}+{x}+{y}")
    dialog.grab_set()

    tk.Label(dialog, text="请输入您的 DeepSeek API Key:", font=("微软雅黑", 10)).pack(pady=(12, 5))
    entry_var = tk.StringVar()
    entry = tk.Entry(dialog, textvariable=entry_var, show="*", width=40, font=("Consolas", 10))
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
    tk.Button(btn_frame, text="确定", width=10, command=on_ok).pack(side=tk.LEFT, padx=10)
    tk.Button(btn_frame, text="取消", width=10, command=on_cancel).pack(side=tk.LEFT, padx=10)
    dialog.bind('<Return>', lambda e: on_ok())
    dialog.bind('<Escape>', lambda e: on_cancel())

    root.wait_window(dialog)
    root.destroy()
    return result[0]

def ensure_api_key():
    global api_key, client
    api_key = os.environ.get(ENV_VAR_NAME)
    if api_key:
        return
    api_key = get_api_key_from_user()
    if not api_key:
        sys.exit(0)
    os.environ[ENV_VAR_NAME] = api_key
    if sys.platform == "win32":
        try:
            subprocess.run(["setx", ENV_VAR_NAME, api_key], capture_output=True, check=True)
        except:
            pass

def init_client():
    global client, api_key
    client = OpenAI(api_key=api_key, base_url=BASE_URL)

def get_kaomoji(user_text: str) -> str:
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text}
            ],
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
            timeout=10
        )
        return response.choices[0].message.content.strip()
    except:
        return ""

def is_punctuation(char):
    return unicodedata.category(char).startswith('P')

def extract_from_cursor_prefix(prefix):
    for i in range(len(prefix) - 1, -1, -1):
        if is_punctuation(prefix[i]):
            return prefix[i + 1:]
    return prefix

def safe_get_prefix():
    try:
        old = pyperclip.paste()
    except:
        old = ''
    kb_ctrl = pynput_keyboard.Controller()
    kb_ctrl.press(pynput_keyboard.Key.ctrl_l)
    kb_ctrl.press(pynput_keyboard.Key.shift_l)
    kb_ctrl.press(pynput_keyboard.Key.home)
    kb_ctrl.release(pynput_keyboard.Key.home)
    kb_ctrl.release(pynput_keyboard.Key.shift_l)
    kb_ctrl.release(pynput_keyboard.Key.ctrl_l)
    time.sleep(0.05)
    kb_ctrl.press(pynput_keyboard.Key.ctrl_l)
    kb_ctrl.press('c')
    kb_ctrl.release('c')
    kb_ctrl.release(pynput_keyboard.Key.ctrl_l)
    time.sleep(0.05)
    try:
        prefix = pyperclip.paste()
    except:
        prefix = ''
    kb_ctrl.press(pynput_keyboard.Key.right)
    kb_ctrl.release(pynput_keyboard.Key.right)
    time.sleep(0.02)
    try:
        pyperclip.copy(old)
    except:
        pass
    return prefix

def handle_hotkey():
    if not hotkey_lock.acquire(blocking=False):
        return
    try:
        prefix = safe_get_prefix()
        text = extract_from_cursor_prefix(prefix)
        if not text:
            return
        kaomoji = get_kaomoji(text)
        if not kaomoji:
            return
        try:
            old = pyperclip.paste()
        except:
            old = ''
        try:
            pyperclip.copy(kaomoji)
            time.sleep(0.02)
            kb_ctrl = pynput_keyboard.Controller()
            kb_ctrl.press(pynput_keyboard.Key.ctrl_l)
            kb_ctrl.press('v')
            kb_ctrl.release('v')
            kb_ctrl.release(pynput_keyboard.Key.ctrl_l)
            time.sleep(0.02)
        finally:
            try:
                pyperclip.copy(old)
            except:
                pass
    except:
        pass
    finally:
        hotkey_lock.release()

def on_press(key):
    global shift_press_times, last_key_was_shift
    if key in (pynput_keyboard.Key.shift, pynput_keyboard.Key.shift_l, pynput_keyboard.Key.shift_r):
        now = time.time()
        shift_press_times.append(now)
        if len(shift_press_times) > 2:
            shift_press_times = shift_press_times[-2:]
        last_key_was_shift = True
    else:
        shift_press_times.clear()
        last_key_was_shift = False

def on_release(key):
    global shift_press_times, last_key_was_shift
    if key in (pynput_keyboard.Key.shift, pynput_keyboard.Key.shift_l, pynput_keyboard.Key.shift_r):
        if (len(shift_press_times) == 2 and 
            last_key_was_shift and
            (shift_press_times[1] - shift_press_times[0]) <= DOUBLE_PRESS_INTERVAL):
            log("双击 Shift 触发")
            threading.Thread(target=handle_hotkey, daemon=True).start()
        last_key_was_shift = False

def main():
    global DEBUG, listener
    if "-t" in sys.argv or "--test" in sys.argv:
        DEBUG = True
        print("调试模式已开启，日志将输出到控制台。")

    if not DEBUG:
        hide_console()

    add_to_startup()

    ensure_api_key()
    if not api_key:
        return

    init_client()

    log("启动双击 Shift 监听...")
    listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    log("服务已启动，等待双击 Shift...")
    listener.join()

if __name__ == "__main__":
    main()