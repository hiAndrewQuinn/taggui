"""Centralized loguru configuration for the taggui application.

`configure_logging()` should be called exactly once, as early as possible in
`main()`. It:

- Removes loguru's default sink and installs a colored stderr sink plus a
  rotating file sink under the platform-appropriate app data directory.
- Forwards stdlib `logging` records (transformers, huggingface_hub, etc.) to
  loguru via an `InterceptHandler`.
- Routes Python `warnings.warn(...)` through the same path.
- Installs a Qt message handler so messages from PySide6 (e.g. the
  `endResetModel called ... without calling beginResetModel first` warning)
  appear as proper log lines instead of bare stderr blurts.

Level: `DEBUG` if `TAGGUI_ENVIRONMENT=development`, otherwise `INFO`. Override
the stderr level explicitly with `TAGGUI_LOG_LEVEL` (`DEBUG`, `INFO`,
`WARNING`, `ERROR`, `CRITICAL`). The file sink stays at `INFO` regardless.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from loguru import logger

_configured = False

_STDERR_FORMAT = (
    '<green>{time:HH:mm:ss.SSS}</green> | '
    '<level>{level: <8}</level> | '
    '<cyan>{name}</cyan> - <level>{message}</level>'
)
_FILE_FORMAT = (
    '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | '
    '{name}:{function}:{line} - {message}'
)


class _InterceptHandler(logging.Handler):
    """Forward stdlib logging records to loguru, preserving level and frame."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # Walk the stack so the file/line shown by loguru is the original
        # caller, not this handler.
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage())


def _resolve_log_dir() -> Path:
    """Return the directory where the rotating log file should live.

    Resolves to `<GenericDataLocation>/taggui/logs/` (e.g.
    `~/.local/share/taggui/logs/` on Linux). We use `GenericDataLocation`
    rather than `AppDataLocation` because this function runs before the
    `QApplication` is created with its application name, and
    `AppDataLocation` would otherwise omit the `taggui/` component. Falls
    back to a dotfolder under the home directory if Qt is unavailable.
    """
    try:
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.GenericDataLocation)
        if base:
            return Path(base) / 'taggui' / 'logs'
    except Exception:
        pass
    return Path.home() / '.taggui' / 'logs'


def _install_qt_message_handler() -> None:
    """Route Qt's own log stream through loguru."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return

    level_for_type = {
        QtMsgType.QtDebugMsg: 'DEBUG',
        QtMsgType.QtInfoMsg: 'INFO',
        QtMsgType.QtWarningMsg: 'WARNING',
        QtMsgType.QtCriticalMsg: 'ERROR',
        QtMsgType.QtSystemMsg: 'ERROR',
        QtMsgType.QtFatalMsg: 'CRITICAL',
    }

    def handler(msg_type, context, message):
        level = level_for_type.get(msg_type, 'INFO')
        logger.opt(depth=1).log(level, '[Qt] {}', message)

    qInstallMessageHandler(handler)


def configure_logging() -> Path | None:
    """Configure loguru sinks and bridges. Idempotent.

    Returns the resolved log file path (or None if the file sink could not be
    created), so callers can surface it to the user.
    """
    global _configured
    if _configured:
        return None
    _configured = True

    if os.getenv('TAGGUI_ENVIRONMENT') == 'development':
        default_level = 'DEBUG'
    else:
        default_level = 'INFO'
    stderr_level = os.getenv('TAGGUI_LOG_LEVEL', default_level).upper()

    logger.remove()
    logger.add(
        sys.stderr,
        level=stderr_level,
        format=_STDERR_FORMAT,
        colorize=True,
        backtrace=False,
        diagnose=False,
    )

    log_file_path: Path | None = None
    log_dir = _resolve_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file_path = log_dir / 'taggui.log'
        logger.add(
            log_file_path,
            level='INFO',
            format=_FILE_FORMAT,
            rotation='5 MB',
            retention=5,
            encoding='utf-8',
            enqueue=True,  # Required: CaptioningThread writes from a worker.
            backtrace=True,
            diagnose=False,
        )
    except OSError as exception:
        logger.warning('Could not set up file logging at {}: {}',
                       log_dir, exception)
        log_file_path = None

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    logging.captureWarnings(True)

    _install_qt_message_handler()

    return log_file_path
