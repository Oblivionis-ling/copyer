"""Read-only capture dates, using one cancellable ExifTool process per scan."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import sys
from threading import Event, Thread
import time

from PIL import Image

RAW_FORMATS = {
    "Canon": (".crw", ".cr2", ".cr3"),
    "Nikon": (".nef", ".nrw"),
    "Sony": (".arw", ".srf", ".sr2"),
    "Fujifilm": (".raf",),
    "OM SYSTEM / Olympus": (".orf",),
    "Panasonic": (".rw2", ".raw"),
    "Pentax": (".pef",),
    "Samsung": (".srw",),
    "Hasselblad": (".3fr", ".fff"),
    "Leica": (".rwl",),
    "Sigma": (".x3f",),
    "Minolta": (".mrw",),
    "Phase One / Leaf": (".iiq", ".mos"),
    "Kodak": (".dcr", ".kdc", ".k25"),
    "通用 DNG（含 DJI / Apple ProRAW）": (".dng",),
}
RAW_EXTENSIONS = frozenset(ext for group in RAW_FORMATS.values() for ext in group)
JPEG_EXTENSIONS = frozenset({".jpg", ".jpeg"})
PHOTO_EXTENSIONS = JPEG_EXTENSIONS | frozenset({".heic", ".heif", ".hif"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v"})


class Cancelled(Exception):
    pass


class MetadataError(Exception):
    pass


@dataclass(frozen=True)
class CaptureDate:
    value: datetime | None
    source: str
    detail: str = ""


def parse_datetime(value) -> datetime | None:
    if not isinstance(value, (str, bytes)):
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="replace")
    text = value.strip("\x00 \t\r\n")
    text = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", text)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?", text):
        return None
    try:
        result = datetime.fromisoformat(text)
        if result.year <= 1904 or result.replace(tzinfo=None) == datetime(1970, 1, 1):
            return None
        return result
    except ValueError:
        return None


def choose_capture_date(tags: dict, *, video: bool, quicktime_utc: bool = True) -> CaptureDate:
    """Prefer original shooting dates, then content creation; never filesystem tags."""
    candidates = [
        ("Composite:SubSecDateTimeOriginal", "EXIF 拍摄时间"),
        ("ExifIFD:DateTimeOriginal", "EXIF 拍摄时间"),
        ("IFD0:DateTimeOriginal", "EXIF 拍摄时间"),
        ("XMP-exif:DateTimeOriginal", "XMP 拍摄时间"),
        ("Keys:CreationDate", "视频拍摄时间" if video else "照片拍摄时间"),
        ("UserData:DateTimeOriginal", "视频拍摄时间"),
        ("QuickTime:DateTimeOriginal", "视频拍摄时间"),
        ("XMP-photoshop:DateCreated", "XMP 拍摄时间"),
        ("XMP-xmp:CreateDate", "XMP 创建时间"),
        ("Composite:SubSecCreateDate", "EXIF 数字化时间"),
        ("ExifIFD:CreateDate", "EXIF 数字化时间"),
        ("Canon:DateTimeOriginal", "相机拍摄时间"),
    ]
    # MakerNote formats such as X3F/MRW/IIQ can expose their own original date.
    for key in tags:
        if key.rsplit(":", 1)[-1] == "DateTimeOriginal" and key not in {item[0] for item in candidates}:
            candidates.insert(3, (key, "相机拍摄时间"))
    if video:
        candidates.append(("QuickTime:CreateDate", "视频创建时间"))
        for suffix in ("MediaCreateDate", "TrackCreateDate"):
            candidates.extend((key, "视频轨道创建时间") for key in sorted(tags) if key.endswith(":" + suffix))
    else:
        # Older RAWs can store capture date as IFD0/XMP creation information.
        candidates.extend((key, "相机创建时间") for key in tags
                          if key.endswith(":CreateDate") and not key.startswith(("File:", "System:", "QuickTime:")))
        candidates.append(("IFD0:ModifyDate", "EXIF 图像时间"))
    for key, label in candidates:
        parsed = parse_datetime(tags.get(key))
        if parsed is None:
            continue
        note = ""
        if video and (key == "QuickTime:CreateDate" or key.endswith((":TrackCreateDate", ":MediaCreateDate"))):
            if parsed.tzinfo is None and quicktime_utc:
                parsed = parsed.replace(tzinfo=timezone.utc).astimezone()
                note = "；按 UTC 转为本机时区"
            elif parsed.tzinfo is None:
                note = "；按设备原值（未标注时区）"
        return CaptureDate(parsed, label, f"{key} = {tags[key]}{note}\n归档时间：{parsed.isoformat(sep=' ')}")
    error = tags.get("ExifTool:Error") or tags.get("Error")
    return CaptureDate(None, "文件修改时间（读取失败）" if error else "文件修改时间（无拍摄日期）",
                       str(error) if error else "文件未提供有效的拍摄或内容创建日期。")


def read_jpeg_date(path: Path) -> CaptureDate:
    """Fallback when the optional development runtime is unavailable."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            details = exif.get_ifd(34665) if 34665 in exif else {}
            for tag, label in ((36867, "EXIF 拍摄时间"), (36868, "EXIF 数字化时间"), (306, "EXIF 图像时间")):
                value = details.get(tag) or exif.get(tag)
                parsed = parse_datetime(value)
                if parsed:
                    return CaptureDate(parsed, label, f"EXIF {tag} = {value}")
    except (OSError, ValueError, TypeError, KeyError, OverflowError, SyntaxError, Image.DecompressionBombError):
        pass
    return CaptureDate(None, "文件修改时间（无拍摄日期）")


def runtime_command() -> list[str]:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    folder = root / ("exiftool" if getattr(sys, "frozen", False) else "vendor/exiftool") / "exiftool_files"
    perl, script = folder / "perl.exe", folder / "exiftool.pl"
    if not perl.is_file() or not script.is_file():
        raise MetadataError("拍摄时间读取组件缺失，请重新完整解压 Copyer。")
    # Invoke Perl directly so cancellation terminates the actual reader, not a launcher.
    return [str(perl), "-I" + str(folder / "lib"), str(script)]


class MetadataReader:
    def __init__(self, cancel: Event | None = None, *, timeout: float = 15, quicktime_utc: bool = True,
                 command: list[str] | None = None):
        self.cancel = cancel or Event()
        self.timeout, self.quicktime_utc = timeout, quicktime_utc
        self.command = command
        self.process = None
        self.thread = None
        self.messages = Queue()
        self.sequence = 0
        self.fatal_error = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _check_cancel(self):
        if self.cancel.is_set():
            self.close()
            raise Cancelled()

    def _start(self):
        self._check_cancel()
        if self.fatal_error:
            raise MetadataError(self.fatal_error)
        if self.process is not None:
            return
        try:
            command = self.command if self.command is not None else runtime_command()
            environment = os.environ.copy()
            for key in ("PERL5OPT", "PERL5LIB", "PERLLIB"):
                environment.pop(key, None)
            environment["LC_ALL"] = "C"
            self.process = subprocess.Popen(command + ["-config", "", "-stay_open", "True", "-@", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, env=environment)
        except (OSError, MetadataError) as exc:
            self.fatal_error = str(exc)
            raise MetadataError(self.fatal_error) from exc
        self.messages = Queue()
        stream, messages = self.process.stdout, self.messages
        def receive():
            try:
                for line in iter(stream.readline, b""):
                    messages.put(line)
            finally:
                messages.put(None)
        self.thread = Thread(target=receive, daemon=True, name="Copyer metadata reader")
        self.thread.start()

    def tags(self, path: Path) -> dict:
        self._start()
        filename = str(path.resolve())
        if "\n" in filename or "\r" in filename:
            raise MetadataError("文件名含换行，无法读取元数据。")
        self.sequence += 1
        marker = f"{{ready{self.sequence}}}".encode("ascii")
        arguments = ["-j", "-G1", "-a", "-s", "-charset", "filename=UTF8", "-api", "QuickTimeUTC=0",
            "-api", "LargeFileSupport=1", "-DateTimeOriginal", "-CreateDate", "-CreationDate", "-DateCreated",
            "-SubSecDateTimeOriginal", "-SubSecCreateDate", "-OffsetTimeOriginal", "-OffsetTimeDigitized",
            "-TrackCreateDate", "-MediaCreateDate", "-IFD0:ModifyDate", "-FileType", "-Error", "-Warning",
            filename, f"-execute{self.sequence}"]
        try:
            self.process.stdin.write(("\n".join(arguments) + "\n").encode("utf-8"))
            self.process.stdin.flush()
            deadline = time.monotonic() + self.timeout
            chunks, length = [], 0
            while True:
                self._check_cancel()
                if time.monotonic() >= deadline:
                    raise MetadataError("拍摄时间读取超时；已使用文件修改时间。")
                try:
                    line = self.messages.get(timeout=.05)
                except Empty:
                    continue
                if line is None:
                    raise MetadataError("拍摄时间读取器异常退出。")
                if line.strip() == marker:
                    break
                length += len(line)
                if length > 2 * 1024 * 1024:
                    raise MetadataError("元数据输出过大。")
                chunks.append(line)
            result = json.loads(b"".join(chunks).decode("utf-8-sig"))
            if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
                raise MetadataError("拍摄时间读取器返回了无效结果。")
            return result[0]
        except (OSError, UnicodeError, ValueError, MetadataError) as exc:
            self.close()
            raise MetadataError(str(exc)) from exc

    def read(self, path: Path) -> CaptureDate:
        self._check_cancel()
        try:
            tags = self.tags(path)
            supported_types = {ext[1:].upper() for ext in RAW_EXTENSIONS | PHOTO_EXTENSIONS | VIDEO_EXTENSIONS} | {"TIFF"}
            detected = tags.get("File:FileType")
            if detected and detected not in supported_types:
                return CaptureDate(None, "文件修改时间（读取失败）", f"扩展名与文件内容不符：读取器识别为 {detected}。")
            return choose_capture_date(tags, video=path.suffix.lower() in VIDEO_EXTENSIONS,
                                       quicktime_utc=self.quicktime_utc)
        except MetadataError as exc:
            if path.suffix.lower() in JPEG_EXTENSIONS:
                fallback = read_jpeg_date(path)
                if fallback.value:
                    return fallback
            return CaptureDate(None, "文件修改时间（读取失败）", str(exc))

    def close(self):
        process, thread = self.process, self.thread
        self.process, self.thread = None, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            if thread is not None:
                thread.join(timeout=3)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
