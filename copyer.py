"""Copyer desktop entry point."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_API", "pyside6")

from PySide6 import QtCore, QtWidgets

from copyer_core import (JPEG_EXTENSIONS, RAW_EXTENSIONS, VIDEO_EXTENSIONS,
                         build_destination_folder_name, ensure_unique_path,
                         get_file_date, scan_media_files)
from copyer_ui import APP_NAME, APP_ORGANIZATION, MediaImporterWindow
from copyer_version import APP_VERSION
from copyer_update import acknowledge_update, update_failure


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Copyer")
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationVersion(APP_VERSION)
    window = MediaImporterWindow()
    window.show()
    QtCore.QTimer.singleShot(500, acknowledge_update)
    failure = update_failure()
    if failure:
        QtCore.QTimer.singleShot(0, lambda: window.notify('更新未完成', failure))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
