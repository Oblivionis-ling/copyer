"""Read image capture dates without decoding pixels."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import struct
from typing import BinaryIO


TIFF_RAW = frozenset({
    ".cr2", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".orf", ".rw2", ".raw",
    ".pef", ".srw", ".3fr", ".fff", ".rwl", ".iiq", ".mos", ".dcr", ".kdc",
    ".k25", ".dng",
})
JPEG = frozenset({".jpg", ".jpeg"})
HEIF = frozenset({".heic", ".heif", ".hif"})
NATIVE_EXTENSIONS = TIFF_RAW | JPEG | HEIF | {".cr3", ".crw", ".raf", ".mrw", ".x3f"}
TIFF_MAGICS = {
    ".orf": (42, 0x4F52, 0x5352),
    ".rw2": (42, 0x55), ".raw": (42, 0x55), ".rwl": (42, 0x55),
}
HEIF_BRANDS = {b"mif1", b"msf1", b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis"}
CANON_METADATA = bytes.fromhex("85c0b687820f11e08111f4ce462b6a48")
EXIF_POINTER = 0x8769
ORIGINAL, SUBSECOND, OFFSET = 0x9003, 0x9291, 0x9011
DATE_TAGS = {ORIGINAL, SUBSECOND, OFFSET}


def _read(stream: BinaryIO, position: int, length: int, end: int) -> bytes:
    if position < 0 or length < 0 or position + length > end:
        raise ValueError("Metadata outside its container")
    stream.seek(position)
    data = stream.read(length)
    if len(data) != length:
        raise ValueError("Truncated metadata")
    return data


def _ifd(stream: BinaryIO, start: int, end: int, offset: int, order: str,
         wanted: set[int]) -> dict[int, tuple[int, int, bytes]]:
    if offset < 8:
        raise ValueError("Invalid TIFF directory offset")
    position = start + offset
    count = struct.unpack(order + "H", _read(stream, position, 2, end))[0]
    if count > 1024:
        raise ValueError("Too many TIFF entries")
    entries = _read(stream, position + 2, 12 * count, end)
    found = {}
    for tag, kind, quantity, value in struct.iter_unpack(order + "HHI4s", entries):
        if tag in wanted:
            if tag in found:
                raise ValueError("Duplicate EXIF field")
            found[tag] = (kind, quantity, value)
    return found


def _ascii_tag(stream: BinaryIO, start: int, end: int, order: str,
               entry: tuple[int, int, bytes] | None) -> str:
    if entry is None:
        return ""
    kind, count, value = entry
    if kind != 2 or not 1 <= count <= 64:
        raise ValueError("Invalid EXIF date field")
    if count > 4:
        offset = struct.unpack(order + "I", value)[0]
        if offset < 8:
            raise ValueError("Invalid EXIF date offset")
        value = _read(stream, start + offset, count, end)
    return value[:count].rstrip(b"\0 ").decode("ascii")


def _tiff_exif(stream: BinaryIO, start: int, end: int, *,
               magics: tuple[int, ...] = (42,), exif_at_root: bool = False) -> tuple[str, str, str, str] | None:
    header = _read(stream, start, 8, end)
    order = {b"II": "<", b"MM": ">"}.get(header[:2])
    if order is None:
        return None
    magic, offset = struct.unpack(order + "HI", header[2:])
    if magic not in magics:
        return None
    entries = _ifd(stream, start, end, offset, order, DATE_TAGS | {EXIF_POINTER})
    group = "ExifIFD" if exif_at_root else "IFD0"
    if not exif_at_root and EXIF_POINTER in entries:
        kind, count, value = entries[EXIF_POINTER]
        if kind not in (4, 13) or count != 1:
            return None
        exif_offset = struct.unpack(order + "I", value)[0]
        if exif_offset == offset:
            return None
        exif = _ifd(stream, start, end, exif_offset, order, DATE_TAGS)
        if ORIGINAL in exif:
            # Split or conflicting tags are uncommon and are safer left to ExifTool.
            for tag in DATE_TAGS & entries.keys():
                if _ascii_tag(stream, start, end, order, entries[tag]) != _ascii_tag(
                        stream, start, end, order, exif.get(tag)):
                    return None
            entries, group = exif, "ExifIFD"
        elif exif:
            return None
    if ORIGINAL not in entries:
        return None

    original = _ascii_tag(stream, start, end, order, entries[ORIGINAL])
    subsecond = _ascii_tag(stream, start, end, order, entries.get(SUBSECOND))
    timezone = _ascii_tag(stream, start, end, order, entries.get(OFFSET))
    return group, original, subsecond, timezone


def _jpeg_exif(stream: BinaryIO, start: int, end: int):
    if _read(stream, start, 2, end) != b"\xff\xd8":
        return None
    position = start + 2
    exif = None
    for _ in range(128):
        if position - start > 1024 * 1024:
            return None
        marker = _read(stream, position, 2, end)
        if marker[0] != 0xFF:
            return None
        code = marker[1]
        if code == 0xFF:
            position += 1
            continue
        if code in (0xDA, 0xD9):  # Start of scan or end of image.
            return exif
        if code < 0xC0 or 0xD0 <= code <= 0xD8:
            return None
        length = int.from_bytes(_read(stream, position + 2, 2, end), "big")
        next_marker = position + 2 + length
        if length < 2 or next_marker > end:
            return None
        if code == 0xE1 and length >= 8 and _read(stream, position + 4, 6, end) == b"Exif\0\0":
            if exif is not None:
                return None
            exif = _tiff_exif(stream, position + 10, next_marker)
            if exif is None:
                return None
        position = next_marker
    return None


def _raf_exif(stream: BinaryIO, end: int):
    header = _read(stream, 0, 92, end)
    if header[:16] != b"FUJIFILMCCD-RAW ":
        return None
    start, length = struct.unpack_from(">II", header, 84)
    if start < len(header) or start + length > end:
        return None
    return _jpeg_exif(stream, start, start + length)


def _mrw_exif(stream: BinaryIO, end: int):
    marker, length = struct.unpack(">4sI", _read(stream, 0, 8, end))
    if marker != b"\0MRM" or length + 8 > end:
        return None
    boundary, position = length + 8, 8
    for _ in range(32):
        if position == boundary:
            break
        kind, length = struct.unpack(">4sI", _read(stream, position, 8, boundary))
        start, position = position + 8, position + 8 + length
        if position > boundary:
            return None
        if kind == b"\0TTW":
            return _tiff_exif(stream, start, position)
    return None


def _camera_timestamp(group: str, seconds: int) -> tuple[str, str, str, str] | None:
    if not 0 < seconds <= 0xFFFFFFFF:
        return None
    # These older formats store a seconds counter. Match the existing
    # reader's calendar value without applying the computer's local timezone.
    date = datetime.fromtimestamp(seconds, timezone.utc)
    return group, date.strftime("%Y:%m:%d %H:%M:%S"), "", ""


def _crw_date(stream: BinaryIO, end: int):
    header = _read(stream, 0, 14, end)
    order = {b"II": "<", b"MM": ">"}.get(header[:2])
    if order is None or header[6:] != b"HEAPCCDR":
        return None
    start = struct.unpack_from(order + "I", header, 2)[0]
    if not len(header) <= start <= end - 6:
        return None

    # CIFF child heaps contain their own directory pointer at the end.
    heaps = [(start, end, 0)]
    visited = set()
    timestamps = set()
    while heaps:
        start, end, depth = heaps.pop()
        if start + 6 > end or depth > 8 or len(visited) >= 128 or (start, end) in visited:
            return None
        visited.add((start, end))
        directory = start + struct.unpack(order + "I", _read(stream, end - 4, 4, end))[0]
        count = struct.unpack(order + "H", _read(stream, directory, 2, end - 4))[0]
        if count > 512:
            return None
        records = _read(stream, directory + 2, count * 10, end - 4)
        for tag, length, offset in struct.iter_unpack(order + "HII", records):
            if tag & 0x8000:
                return None
            number, storage = tag & 0x3FFF, tag & 0x4000
            if number == 0x180E:
                if storage:
                    timestamps.add(length)  # First four bytes of the inline value.
                elif length >= 4 and start + offset + length <= directory:
                    data = _read(stream, start + offset, 4, directory)
                    timestamps.add(struct.unpack(order + "I", data)[0])
                else:
                    return None
            elif not storage and (number & 0x3800) in (0x2800, 0x3000):
                if start + offset + length > directory:
                    return None
                heaps.append((start + offset, start + offset + length, depth + 1))
    if len(timestamps) != 1:
        return None
    return _camera_timestamp("CanonRaw", timestamps.pop())


def _x3f_property_time(data: bytes) -> int | None:
    marker, version, count, encoding, _, units = struct.unpack_from("<4s5I", data)
    if marker != b"SECp" or version != 0x00020000 or encoding != 0 or count > 512:
        return None
    strings_at = 24 + count * 8
    if strings_at + units * 2 > len(data):
        return None
    strings = data[strings_at:strings_at + units * 2]
    times = []
    for key, value in struct.iter_unpack("<II", data[24:strings_at]):
        if key >= units or value >= units:
            return None
        if strings[key * 2:key * 2 + 10] != b"T\0I\0M\0E\0\0\0":
            continue
        # A decimal 32-bit counter takes at most 10 UTF-16 code units.
        text = strings[value * 2:value * 2 + 22].decode("utf-16le")
        digits, separator, _ = text.partition("\0")
        if not separator or not digits.isascii() or not digits.isdecimal():
            return None
        times.append(int(digits))
    return times[0] if len(times) == 1 else None


def _x3f_date(stream: BinaryIO, end: int):
    marker, version = struct.unpack("<4sI", _read(stream, 0, 8, end))
    if marker != b"FOVb" or not 2 <= version >> 16 <= 5:
        return None
    directory = struct.unpack("<I", _read(stream, end - 4, 4, end))[0]
    if directory < 40:
        return None
    marker, _, count = struct.unpack("<4sII", _read(stream, directory, 12, end - 4))
    if marker != b"SECd" or count > 128:
        return None
    records = _read(stream, directory + 12, count * 12, end - 4)
    properties = []
    photo_exif = []
    for offset, length, kind in struct.iter_unpack("<II4s", records):
        if not 40 <= offset < offset + length <= directory:
            return None
        if kind == b"PROP":
            if not 24 <= length <= 128 * 1024 or properties:
                return None
            properties.append((offset, length))
        elif kind == b"IMA2" and length >= 32:
            header = _read(stream, offset, 16, offset + length)
            if header == struct.pack("<4sIII", b"SECi", 0x00020000, 2, 18):
                jpeg = offset + 28
                if _read(stream, jpeg, 4, offset + length) == b"\xff\xd8\xff\xe1":
                    photo_exif.append(_jpeg_exif(stream, jpeg, offset + length))
    if photo_exif:
        # Embedded EXIF has priority over the camera's TIME property.
        return photo_exif[0] if len(photo_exif) == 1 else None
    if properties:
        offset, length = properties[0]
        seconds = _x3f_property_time(_read(stream, offset, length, directory))
        if seconds is not None:
            return _camera_timestamp("SigmaRaw", seconds)
    return None


def _boxes(stream: BinaryIO, position: int, end: int):
    """Yield atom type and payload bounds, skipping large unrelated payloads."""
    for _ in range(512):
        if position == end:
            return
        size, kind = struct.unpack(">I4s", _read(stream, position, 8, end))
        header = 8
        if size == 1:
            size = int.from_bytes(_read(stream, position + 8, 8, end), "big")
            header = 16
        elif size == 0:
            size = end - position
        if not header <= size <= end - position:
            raise ValueError("Invalid media box size")
        yield kind, position + header, position + size
        position += size
    raise ValueError("Too many media boxes")


def _one_box(stream: BinaryIO, begin: int, end: int, name: bytes) -> tuple[int, int]:
    matches = [(start, stop) for kind, start, stop in _boxes(stream, begin, end) if kind == name]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous media box")
    return matches[0]


def _brands(stream: BinaryIO, end: int) -> set[bytes]:
    start, stop = _one_box(stream, 0, end, b"ftyp")
    length = stop - start
    if not 8 <= length <= 256 or length % 4:
        raise ValueError("Invalid media brands")
    data = _read(stream, start, length, stop)
    return {data[:4], *(data[index:index + 4] for index in range(8, length, 4))}


def _cr3_exif(stream: BinaryIO, end: int):
    if b"crx " not in _brands(stream, end):
        return None
    movie = _one_box(stream, 0, end, b"moov")
    canon = [
        (begin + 16, stop) for kind, begin, stop in _boxes(stream, *movie)
        if kind == b"uuid" and _read(stream, begin, 16, stop) == CANON_METADATA
    ]
    if len(canon) != 1:
        return None
    start, stop = _one_box(stream, *canon[0], b"CMT2")
    return _tiff_exif(stream, start, stop, exif_at_root=True)


def _heif_exif_item(stream: BinaryIO, meta: tuple[int, int]) -> int:
    start, end = _one_box(stream, *meta, b"iinf")
    version = _read(stream, start, 1, end)[0]
    if version not in (0, 1, 2):
        raise ValueError("Unsupported HEIF item information")
    count_width = 2 if version == 0 else 4
    count = int.from_bytes(_read(stream, start + 4, count_width, end), "big")
    items = {}
    for kind, begin, stop in _boxes(stream, start + 4 + count_width, end):
        version = _read(stream, begin, 1, stop)[0]
        if kind != b"infe" or version not in (2, 3):
            raise ValueError("Unsupported HEIF item info")
        width = 2 if version == 2 else 4
        data = _read(stream, begin + 4, width + 6, stop)
        item_id = int.from_bytes(data[:width], "big")
        if item_id in items:
            raise ValueError("Duplicate HEIF item")
        item_type = data[width + 2:]
        if item_type == b"Exif" and data[width:width + 2] != b"\0\0":
            raise ValueError("Protected HEIF EXIF item")
        items[item_id] = item_type
    exif = [item_id for item_id, kind in items.items() if kind == b"Exif"]
    if len(items) != count or len(exif) != 1:
        raise ValueError("Missing or ambiguous HEIF EXIF item")

    start, end = _one_box(stream, *meta, b"pitm")
    version = _read(stream, start, 1, end)[0]
    if version not in (0, 1):
        raise ValueError("Unsupported HEIF primary item")
    primary = int.from_bytes(_read(stream, start + 4, 2 if version == 0 else 4, end), "big")
    if primary not in items or primary == exif[0]:
        raise ValueError("Invalid HEIF primary item")
    start, end = _one_box(stream, *meta, b"iref")
    version = _read(stream, start, 1, end)[0]
    if version not in (0, 1):
        raise ValueError("Unsupported HEIF item reference")
    width = 2 if version == 0 else 4
    descriptions = []
    for kind, begin, stop in _boxes(stream, start + 4, end):
        if kind != b"cdsc":
            continue
        source = int.from_bytes(_read(stream, begin, width, stop), "big")
        if source == exif[0]:
            data = _read(stream, begin + width, 2 + width, stop)
            if data[:2] != b"\0\1" or begin + 2 * width + 2 != stop:
                raise ValueError("Ambiguous HEIF EXIF reference")
            descriptions.append(int.from_bytes(data[2:], "big"))
    if descriptions != [primary]:
        raise ValueError("HEIF EXIF does not describe the primary image")
    return exif[0]


def _heif_exif(stream: BinaryIO, end: int):
    if not _brands(stream, end) & HEIF_BRANDS:
        return None
    begin, stop = _one_box(stream, 0, end, b"meta")
    if _read(stream, begin, 4, stop) != b"\0" * 4:
        return None
    meta = (begin + 4, stop)
    exif_id = _heif_exif_item(stream, meta)
    start, stop = _one_box(stream, *meta, b"iloc")
    if stop - start > 64 * 1024:
        return None
    data = _read(stream, start, stop - start, stop)
    if len(data) < 8 or data[0] not in (0, 1, 2):
        return None
    version, position = data[0], 6
    offset_width, length_width = data[4] >> 4, data[4] & 15
    base_width, index_width = data[5] >> 4, (data[5] & 15 if version else 0)
    if any(width not in (0, 4, 8) for width in (offset_width, length_width, base_width, index_width)):
        return None

    def integer(width: int) -> int:
        nonlocal position
        stop = position + width
        if stop > len(data):
            raise ValueError("Truncated HEIF extent")
        value = int.from_bytes(data[position:stop], "big")
        position = stop
        return value

    id_width = 4 if version == 2 else 2
    count = integer(id_width)
    if count > 512:
        return None
    extent = None
    for _ in range(count):
        item_id = integer(id_width)
        method = integer(2) if version else 0
        reference = integer(2)
        base = integer(base_width)
        num_extents = integer(2)
        if item_id != exif_id:
            position += num_extents * (index_width + offset_width + length_width)
            continue
        if num_extents != 1 or extent is not None:
            return None
        integer(index_width)
        offset, length = integer(offset_width), integer(length_width)
        extent = (method, reference, base + offset, length)
    if position != len(data) or extent is None:
        return None
    method, reference, offset, length = extent
    if reference or method not in (0, 1) or not 12 <= length <= 1024 * 1024:
        return None
    if method == 1:
        begin, end = _one_box(stream, *meta, b"idat")
        offset += begin
    exif_end = offset + length
    displacement = int.from_bytes(_read(stream, offset, 4, end), "big")
    if exif_end > end:
        return None
    return _tiff_exif(stream, offset + 4 + displacement, exif_end)


def read_original_date_fields(path: Path) -> tuple[str, str, str, str] | None:
    extension = path.suffix.lower()
    if extension not in NATIVE_EXTENSIONS:
        return None
    try:
        with path.open("rb") as stream:
            end = stream.seek(0, 2)
            if extension in JPEG:
                return _jpeg_exif(stream, 0, end)
            if extension == ".cr3":
                return _cr3_exif(stream, end)
            if extension == ".crw":
                return _crw_date(stream, end)
            if extension == ".raf":
                return _raf_exif(stream, end)
            if extension == ".mrw":
                return _mrw_exif(stream, end)
            if extension == ".x3f":
                return _x3f_date(stream, end)
            if extension in HEIF:
                return _heif_exif(stream, end)
            return _tiff_exif(stream, 0, end, magics=TIFF_MAGICS.get(extension, (42,)))
    except (OSError, ValueError):
        return None
