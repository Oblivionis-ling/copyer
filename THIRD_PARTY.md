# Third-party components

Copyer v1.5.1 bundles **ExifTool 13.60** and its Windows 64-bit Perl runtime for
read-only metadata extraction. ExifTool is Copyright Phil Harvey and is
available under the same terms as Perl. Component notices are retained in
`_internal/exiftool/exiftool_files/LICENSE`, `Licenses_Strawberry_Perl.zip` and
the included Windows documentation. Python/Qt dependency notices are in
`_internal/licenses/`.

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

The upstream metadata test fixtures are documented separately in
[`tests/fixtures/exiftool/README.md`](tests/fixtures/exiftool/README.md).
