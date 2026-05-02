import os
import sys
import traceback
import warnings
from importlib.metadata import PackageNotFoundError, version
from time import perf_counter

import transformers
from loguru import logger
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication, QMessageBox

from taggui.utils.logging_setup import configure_logging
from taggui.utils.settings import get_settings
from taggui.widgets.main_window import MainWindow


def suppress_warnings():
    """Quiet down noisy third-party loggers when not in development.

    The actual logging stream is configured by `configure_logging()`; this
    function only adjusts the verbosity of upstream libraries so their
    messages don't drown out our own.
    """
    if os.getenv('TAGGUI_ENVIRONMENT') == 'development':
        logger.info('Running in development environment.')
        return
    warnings.simplefilter('ignore')
    transformers.logging.set_verbosity_error()
    try:
        import auto_gptq
        import logging
        logging.getLogger(auto_gptq.modeling._base.__name__).setLevel(
            logging.ERROR)
    except ImportError:
        pass


def _get_version() -> str:
    try:
        return version('taggui')
    except PackageNotFoundError:
        return 'unknown'


def run_gui():
    t0 = perf_counter()
    logger.info('taggui {} starting', _get_version())
    app = QApplication([])
    # The application name is shown in the taskbar.
    app.setApplicationName('TagGUI')
    # The application display name is shown in the title bar.
    app.setApplicationDisplayName('TagGUI')
    app.setStyle('Fusion')
    # Disable the allocation limit to allow loading large images.
    QImageReader.setAllocationLimit(0)
    logger.debug('QApplication created in {:.2f}s', perf_counter() - t0)
    logger.debug('Constructing main window…')
    main_window = MainWindow(app)
    main_window.show()
    logger.info('Window shown in {:.2f}s total', perf_counter() - t0)
    sys.exit(app.exec())


def main():
    logger.debug('Entering main() now')
    # Prevent PyTorch from opening multiple windows when running inside a
    # PyInstaller bundle.
    if len(sys.argv) > 1 and 'compile_worker' in sys.argv[1]:
        import runpy

        sys.argv = sys.argv[1:]
        runpy.run_path(sys.argv[0], run_name='__main__')
        sys.exit(0)
    log_file_path = configure_logging()
    suppress_warnings()
    if log_file_path is not None:
        logger.debug('Log file: {}', log_file_path)
    try:
        run_gui()
    except Exception as exception:
        logger.exception('Fatal error during startup')
        settings = get_settings()
        settings.clear()
        error_message_box = QMessageBox()
        error_message_box.setWindowTitle('Error')
        error_message_box.setIcon(QMessageBox.Icon.Critical)
        error_message_box.setText(str(exception))
        error_message_box.setDetailedText(traceback.format_exc())
        error_message_box.exec()
        raise exception


if __name__ == '__main__':
    logger.debug('Starting up!')
    main()
