"""Copyer desktop entry point."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_API", "pyside6")

from PySide6 import QtWidgets

from copyer_core import (JPEG_EXTENSIONS, RAW_EXTENSIONS, VIDEO_EXTENSIONS,
                         build_destination_folder_name, ensure_unique_path,
                         get_file_date, scan_media_files)
from copyer_ui import APP_NAME, APP_ORGANIZATION, MediaImporterWindow
from copyer_version import APP_VERSION


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Copyer")
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationVersion(APP_VERSION)
    window = MediaImporterWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
