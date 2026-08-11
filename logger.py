"""Kmoji logging subsystem.

RotatingFileHandler (1 MB × 3 backups) with hot-reload support.
"""
import logging
import logging.handlers
import os
import sys

# Module-level references so other modules can obtain the same logger easily.
_logger = None
_handler = None
_log_path = None


def _make_formatter():
    return logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def init_logger(config):
    """Create and initialise the global logger.

    Called once at startup.  Returns the configured logger.
    """
    global _logger, _handler, _log_path

    _logger = logging.getLogger("kmoji")
    _logger.setLevel(logging.DEBUG)  # handler level gates actual output

    # --- console fallback (debug mode / no file logging) ---
    if "-t" in sys.argv or "--test" in sys.argv:
        config.set("logging_enabled", False)
        ch = logging.StreamHandler()
        ch.setFormatter(_make_formatter())
        ch.setLevel(logging.DEBUG)
        _logger.addHandler(ch)
        _logger.info("调试模式：日志输出到控制台")
        return _logger

    # --- file handler ---
    _log_path = config.get("log_path") or _get_default_log_path()
    _apply_file_handler(config)
    return _logger


def _get_default_log_path():
    """Return the default log file path (shared with config module logic)."""
    import config as _cfg_module
    return _cfg_module.get_default_log_path()


def _apply_file_handler(config):
    """Remove any existing file handler and create a fresh one.

    Accepts ``config`` (Config instance) explicitly so that the
    function works both during initialisation and on hot-reload.
    """
    global _handler, _log_path

    if _handler is not None:
        _logger.removeHandler(_handler)
        try:
            _handler.close()
        except Exception:
            pass
        _handler = None

    if not config.get("logging_enabled"):
        return

    os.makedirs(os.path.dirname(_log_path), exist_ok=True)
    _handler = logging.handlers.RotatingFileHandler(
        _log_path, maxBytes=1_048_576, backupCount=3, encoding="utf-8"
    )
    _handler.setFormatter(_make_formatter())

    level_str = config.get("log_level", "INFO").upper()
    _handler.setLevel(getattr(logging, level_str, logging.INFO))
    _logger.addHandler(_handler)


def get_logger():
    """Return the module-level logger (must have called init_logger first)."""
    return _logger


def reconfigure(config):
    """Hot-reload: re-read log-level + enabled + path from Config."""
    global _log_path

    level_str = config.get("log_level", "INFO").upper()
    if _handler:
        _handler.setLevel(getattr(logging, level_str, logging.INFO))
        _logger.setLevel(logging.DEBUG)

    new_path = config.get("log_path") or _get_default_log_path()
    if new_path != _log_path or config.get("logging_enabled") != (
        _handler is not None
    ):
        _log_path = new_path
        _apply_file_handler(config)


def log_startup():
    """Log a startup banner."""
    L = get_logger()
    L.info("-" * 40)
    L.info("Kmoji 启动")


def log_shutdown():
    """Log clean shutdown."""
    if _logger:
        _logger.info("Kmoji 正常退出")
    if _handler:
        _handler.close()
