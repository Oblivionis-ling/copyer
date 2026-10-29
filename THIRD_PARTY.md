# Third-party components

Copyer bundles **ExifTool 13.60** and its Windows 64-bit Perl runtime for
read-only metadata extraction. ExifTool is Copyright Phil Harvey and is
available under the same terms as Perl. Component notices are retained in
`_internal/exiftool/exiftool_files/LICENSE` and `Licenses_Strawberry_Perl.zip`.
The unmodified parser modules and runtime remain bundled; standalone manuals,
the unused launcher and reverse-geocoding database are omitted in v1.5.2.

- Project and documentation: https://exiftool.org/
- Source: https://github.com/exiftool/exiftool/tree/13.60
- Source archive: https://sourceforge.net/projects/exiftool/files/Image-ExifTool-13.60.tar.gz/download
- Windows distribution: https://sourceforge.net/projects/exiftool/files/exiftool-13.60_64.zip/download
- Official checksums: https://exiftool.org/checksums-13.60.txt
- QuickTime date/time semantics: https://exiftool.org/TagNames/QuickTime.html

The pinned Windows archive SHA-256 is:

```text
548b1f4e0b713cd2a26824b34080c35db4e2d2edd166468eb38b1d55ada90c2e
```

Python, PySide6 / Qt and Pillow notices are in `_internal/licenses/`. Qt's
shared libraries remain separate and replaceable. Sources:

- Python: https://www.python.org/downloads/source/
- Qt: https://download.qt.io/archive/qt/
- PySide6: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Pillow: https://github.com/python-pillow/Pillow

The 12 interface icons retain their existing Phosphor / Remix / Material
Design outlines. Attribution and license texts are in
`_internal/licenses/icons/` (source: `assets/licenses/`). QtAwesome, QtPy and
the full icon fonts are no longer distributed.

Test fixture sources are documented in `tests/fixtures/exiftool/README.md`
in the source repository; test fixtures are not included in the application.
