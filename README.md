

# Kmoji - Kaomoji 输入工具

一个简单的 Kaomoji（颜文字）输入工具，支持快捷键调用和 API 集成。

## 功能特性

- **快捷键激活**：通过热键快速呼出输入界面
- **API 支持**：调用外部 API 获取颜文字推荐
- **开机自启**：支持设置开机自动运行
- **光标智能识别**：自动从光标位置提取文本前缀

## 依赖要求

- Python 3.7+
- pynput（用于键盘监听）
- requests（用于 API 调用）

## 安装步骤

1. 克隆项目：
```bash
git clone https://gitee.com/wyz0101/kmoji.git
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

## 使用方法

### 运行程序

```bash
python kmoji.py
```

### 快捷键

- **激活快捷键**：按下预设热键呼出输入框
- **确认选择**：选择颜文字后按回车键确认
- **取消操作**：按 Esc 键取消当前操作

### API 配置

首次运行需要配置 API 密钥：
1. 运行程序后按提示输入 API 密钥
2. API 密钥将保存在配置文件中，后续运行自动加载

## 项目结构

```
kmoji/
├── kmoji.py         # 主程序入口
├── requirements.txt # 依赖列表
└── LICENSE          # 许可证文件
```

## 主要模块

| 模块 | 功能说明 |
|------|---------|
| `init_client()` | 初始化客户端配置 |
| `get_kaomoji()` | 根据输入文本获取颜文字推荐 |
| `handle_hotkey()` | 处理热键激活事件 |
| `on_press()` / `on_release()` | 键盘事件监听 |

## 开机自启

程序支持设置开机自动运行，调用 `add_to_startup()` 函数即可启用。

## 许可证

本项目采用 MIT 许可证开源。