# Kmoji — Kaomoji（颜文字）输入工具

一个 Windows 平台的智能颜文字输入工具：通过快捷键触发，取光标前文本，调用 DeepSeek API 生成匹配的颜文字，并自动粘贴到光标位置。

## 功能特性

- **智能颜文字生成**：读取光标前文字，调用 DeepSeek API 生成情感匹配的原创颜文字
- **可配置快捷键**：支持双击 Shift（默认）、双击 Ctrl、或自定义组合键（如 Alt+J、Ctrl+Shift+K）
- **系统托盘**：后台运行，托盘图标显示运行状态。左键→设置，右键→菜单
- **图形化设置界面**（tkinter）：配置快捷键、日志、开机自启、API Key 管理
- **日志系统**：RotatingFileHandler（1 MB × 3 份），DEBUG/INFO/WARNING/ERROR 四级
- **开机自启动**：通过注册表 Run 键管理，设置界面一键开关
- **安全存储**：API Key 优先使用 Windows 凭据管理器（keyring），降级到注册表直写

## 依赖

- Python 3.8+
- openai ≥1.0.0, <2（DeepSeek API）
- pynput ≥1.7, <2（键盘监听）
- pystray ≥0.19, <1（系统托盘）
- pillow ≥9.0, <12（托盘图标绘制）
- keyring ≥23.0, <26（安全凭据存储）
- pyperclip ≥1.8, <2（剪贴板操作）

## 安装

```bash
git clone https://gitee.com/wyz0101/kmoji.git
cd kmoji
pip install -r requirements.txt
```

## 使用方法

### 运行

```bash
# 正常模式（后台 + 托盘）
python kmoji.py

# 调试模式（日志输出到控制台，不隐藏窗口）
python kmoji.py --test
# 或
python kmoji.py -t

# 仅打开设置窗口
python kmoji.py --settings
```

### 快捷键

| 触发方式 | 说明 |
|---------|------|
| 双击 Shift | 默认，连续快速按两次 Shift |
| 双击 Ctrl | 可在设置中切换 |
| 自定义组合 | 如 Alt+J、Ctrl+Shift+K，在设置界面捕获 |

触发后自动执行：取光标前文本 → API 生成颜文字 → Ctrl+V 粘贴。

### 设置界面

通过托盘菜单「设置」打开，包含四个标签页：

- **启动**：开机自启动开关，实时显示当前状态
- **快捷键**：启用/禁用开关、触发方式选择、自定义组合键捕获、双击间隔
- **日志**：日志开关、级别（DEBUG/INFO/WARNING/ERROR）、文件路径、打开目录/查看
- **API Key**：显示当前 Key（脱敏：`sk-***abc`）、重新输入、清除

### API Key 管理

首次运行时弹出输入对话框。Key 存储优先级：

1. **Windows 凭据管理器**（keyring，安全存储）
2. **环境变量** `DEEPSEEK_API_KEY`
3. **注册表** `HKCU\Environment`（明文降级，但不经命令行暴露）
4. **GUI 弹窗输入**

## 项目结构

```
kmoji/
├── kmoji.py         # 主入口 — 启动逻辑、API 调用、事件编排
├── config.py        # 配置管理 — JSON 文件读写
├── security.py      # API Key 安全存储 — keyring / 注册表 / 弹窗
├── hotkey.py        # 键盘监听 — 可配置触发方式
├── clipboard.py     # 剪贴板操作 — TOCTOU 防护、窗口校验
├── gui.py           # 设置界面 — tkinter 四标签页窗口
├── tray.py          # 系统托盘 — pystray 图标和菜单
├── logger.py        # 日志子系统 — RotatingFileHandler
├── requirements.txt # 依赖列表（含版本上限约束）
├── README.md        # 本文件
└── LICENSE          # MIT 许可证
```

## 安全设计

| 问题 | 修复方案 |
|-----|---------|
| API Key 通过 `setx` 命令行暴露 | 改用 keyring（Windows 凭据管理器）；降级时直写注册表而非 setx |
| API 调用期间用户切换窗口导致粘贴错位 | 触发时记录前台窗口句柄，粘贴前校验同一窗口，否则放弃并记日志 |
| 剪贴板 TOCTOU 竞态（Ctrl+C 后被篡改） | 复制后读回校验一致性；不一致则放弃本次操作 |
| 剪贴板恢复失败被裸 `except` 吞掉 | 所有 except 改为 `except Exception as e:`，恢复失败时写日志警告 |

## 许可证

MIT
