# Metadata parser fixtures

These small metadata test files come unchanged from the upstream ExifTool test
suite, version 13.60, commit `980409314fddbd83d9092b5c160fafab7f67fd52`:

https://github.com/exiftool/exiftool/tree/13.60/t/images

They retain camera/container metadata but are not complete, decodable original
photographs or videos. Copyer tests use them to exercise the real metadata
parser, including Canon CR3, CR2/CRW, DNG, NEF, RAF, RW2, MRW, IIQ and X3F.

The HEIC and MOV fixtures are also copied to a temporary directory and given
controlled capture-date tags for Apple/DJI-style field and timezone regression
tests. These generated cases are not recordings made by those devices.

ExifTool is Copyright Phil Harvey and is available under the same terms as
Perl. The distribution's GPL license is included as `LICENSE`. See also:
https://exiftool.org/ and https://exiftool.org/TagNames/QuickTime.html
