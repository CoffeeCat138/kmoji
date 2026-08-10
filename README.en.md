# Kmoji - Kaomoji Input Tool

A simple Kaomoji input tool supporting hotkey invocation and API integration.

## Features

- **Hotkey Activation**: Quickly bring up the input interface via a hotkey.
- **API Support**: Call external APIs to fetch Kaomoji recommendations.
- **Auto-start on Boot**: Supports setting automatic startup on system boot.
- **Smart Cursor Recognition**: Automatically extracts text prefixes from the cursor position.

## Dependencies

- Python 3.7+
- pynput (for keyboard monitoring)
- requests (for API calls)

## Installation Steps

1. Clone the project:
```bash
git clone https://gitee.com/wyz0101/kmoji.git
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Running the Program

```bash
python kmoji.py
```

### Hotkeys

- **Activation Hotkey**: Press the preset hotkey to bring up the input box.
- **Confirm Selection**: Press Enter to confirm after selecting a Kaomoji.
- **Cancel Action**: Press Esc to cancel the current action.

### API Configuration

API key configuration is required on first run:
1. Enter the API key as prompted after running the program.
2. The API key will be saved in the configuration file and automatically loaded for subsequent runs.

## Project Structure

```
kmoji/
├── kmoji.py         # Main program entry
├── requirements.txt # Dependency list
└── LICENSE          # License file
```

## Main Modules

| Module | Description |
|------|---------|
| `init_client()` | Initialize client configuration |
| `get_kaomoji()` | Fetch Kaomoji recommendations based on input text |
| `handle_hotkey()` | Handle hotkey activation events |
| `on_press()` / `on_release()` | Keyboard event listeners |

## Auto-start on Boot

The program supports setting automatic startup; calling the `add_to_startup()` function enables this feature.

## License

This project is open-sourced under the MIT License.