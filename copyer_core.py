"""Filesystem operations for Copyer; independent of the GUI and its lifetime."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from threading import Event

from copyer_metadata import (Cancelled, MetadataReader, RAW_EXTENSIONS, JPEG_EXTENSIONS,
                             PHOTO_EXTENSIONS, VIDEO_EXTENSIONS)
CHUNK_SIZE = 1024 * 1024


def check_cancel(cancel: Event) -> None:
    if cancel.is_set():
        raise Cancelled()


def is_link(path: Path) -> bool:
    return is_link_info(path.lstat())


def is_link_info(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def directory_path(text: str, *, must_exist: bool = False) -> Path:
    if not str(text).strip():
        raise ValueError("请选择文件夹，路径不能为空。")
    path = Path(text).expanduser().resolve()
    if must_exist and not path.is_dir():
        raise ValueError("来源文件夹不存在或无法访问。")
    if path.exists() and not path.is_dir():
        raise ValueError("所选路径不是文件夹。")
    return path


def validate_component(name: str) -> str:
    if (not name or name in {".", ".."} or name[-1:] in {".", " "}
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)):
        raise ValueError("名称不能包含路径分隔符、非法字符或末尾的点和空格。")
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ValueError("名称不能使用 Windows 保留名。")
    if len(name) > 180:
        raise ValueError("文件夹名称过长，请缩短后缀。")
    return name


def build_destination_folder_name(date_text: str, suffix: str) -> str:
    date.fromisoformat(date_text)
    suffix = suffix.strip()
    return validate_component(f"{date_text}-{suffix}" if suffix else date_text)


def read_exif_datetime(path: Path) -> datetime | None:
    # Compatibility entry point; scanning reuses a reader for the whole task.
    with MetadataReader() as reader:
        return reader.read(path).value


def get_file_date(path: Path) -> date:
    captured = read_exif_datetime(path)
    return (captured or datetime.fromtimestamp(path.stat().st_mtime)).date()


def identity(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_dev, info.st_ino


@dataclass(frozen=True)
class MediaFile:
    path: Path
    date_text: str
    size: int
    mtime_ns: int
    date_source: str = "文件修改时间"
    date_detail: str = ""

    @classmethod
    def inspect(cls, path: Path, reader: MetadataReader | None = None,
                info: os.stat_result | None = None) -> "MediaFile":
        if info is None:
            info = path.lstat()
        if is_link_info(info):
            raise ValueError("跳过链接或重解析文件。")
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("不是普通文件。")
        if reader is None:
            with MetadataReader() as single:
                captured = single.read(path, info)
        else:
            captured = reader.read(path, info)
        day = (captured.value or datetime.fromtimestamp(info.st_mtime)).date().isoformat()
        return cls(path.absolute(), day, info.st_size, info.st_mtime_ns, captured.source, captured.detail)

    def matches(self, info: os.stat_result) -> bool:
        return (info.st_size, info.st_mtime_ns) == (self.size, self.mtime_ns)


@dataclass(frozen=True)
class FileIssue:
    path: Path
    message: str


@dataclass
class ScanResult:
    source: Path
    source_identity: tuple[int, int]
    groups: dict[str, list[MediaFile]] = field(default_factory=dict)
    issues: list[FileIssue] = field(default_factory=list)
    cancelled: bool = False

    @property
    def files(self) -> list[MediaFile]:
        return [item for group in self.groups.values() for item in group]


def scan(source_text: str, extensions: Iterable[str], cancel: Event | None = None,
         progress: Callable[[int, str, dict[str, int]], None] | None = None,
         *, quicktime_utc: bool = True, metadata_cache: dict | None = None) -> ScanResult:
    cancel = cancel or Event()
    source = directory_path(source_text, must_exist=True)
    allowed = {ext.lower() for ext in extensions}
    if not allowed:
        raise ValueError("至少选择一种文件类型。")
    result = ScanResult(source, identity(source))
    groups: dict[str, list[MediaFile]] = defaultdict(list)
    pending = [source]
    found = 0
    last_update = 0.0
    reader = MetadataReader(cancel, quicktime_utc=quicktime_utc, cache=metadata_cache,
                            source_identity=result.source_identity)
    batch: dict[Path, os.stat_result] = {}

    def inspect_batch():
        nonlocal found, last_update
        reader.prefetch(list(batch), batch)
        for path, info in batch.items():
            check_cancel(cancel)
            try:
                media = MediaFile.inspect(path, reader, info)
                groups[media.date_text].append(media)
                found += 1
            except (OSError, ValueError) as exc:
                result.issues.append(FileIssue(path, str(exc)))
            now = time.monotonic()
            if progress and now - last_update >= 0.1:
                progress(found, str(path.parent), {key: len(value) for key, value in groups.items()})
                last_update = now
        batch.clear()

    try:
        while pending:
            check_cancel(cancel)
            current = pending.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        check_cancel(cancel)
                        path = Path(entry.path)
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if is_link_info(info):
                                result.issues.append(FileIssue(path, "已跳过链接或重解析点。"))
                            elif stat.S_ISDIR(info.st_mode):
                                pending.append(path)
                            elif stat.S_ISREG(info.st_mode) and path.suffix.lower() in allowed:
                                batch[path] = info
                                if len(batch) >= 32:
                                    inspect_batch()
                            now = time.monotonic()
                            if progress and now - last_update >= 0.1:
                                progress(found, str(current), {key: len(value) for key, value in groups.items()})
                                last_update = now
                        except (OSError, ValueError) as exc:
                            result.issues.append(FileIssue(path, str(exc)))
            except OSError as exc:
                result.issues.append(FileIssue(current, str(exc)))
        if batch:
            inspect_batch()
    except Cancelled:
        result.cancelled = True
    finally:
        reader.close()
    if reader.fatal_error:
        result.issues.append(FileIssue(source, reader.fatal_error))
    if identity(source) != result.source_identity:
        raise ValueError("来源设备已变化，请重新扫描。")
    result.groups = {key: sorted(value, key=lambda item: str(item.path).casefold())
                     for key, value in sorted(groups.items(), reverse=True)}
    if progress:
        progress(found, str(source), {key: len(value) for key, value in result.groups.items()})
    return result


def scan_media_files(source_directory: Path, extensions: Iterable[str]) -> dict[str, list[Path]]:
    result = scan(str(source_directory), extensions)
    return {key: [media.path for media in value] for key, value in sorted(result.groups.items())}


def ensure_unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    index = 0
    while os.path.lexists(candidate):
        index += 1
        candidate = directory / f"{Path(filename).stem}_{index}{Path(filename).suffix}"
    return candidate


@dataclass(frozen=True)
class PlannedFile:
    media: MediaFile
    folder: str


@dataclass(frozen=True)
class ImportJob:
    source: Path
    source_identity: tuple[int, int]
    target: Path
    items: tuple[PlannedFile, ...]
    skip_identical: bool = True


@dataclass(frozen=True)
class FileStamp:
    identity: tuple[int, int]
    size: int
    mtime_ns: int
    change_time: int


@dataclass(frozen=True)
class FileResult:
    item: PlannedFile
    status: str
    destination: Path | None = None
    error: str = ""
    verified_sha256: str = ""
    source_stamp: FileStamp | None = None
    target_stamp: FileStamp | None = None


@dataclass(frozen=True)
class Progress:
    phase: str
    path: str
    done: int
    total: int
    completed: int
    files: int
    elapsed: float


@dataclass
class ImportResult:
    job: ImportJob
    files: list[FileResult] = field(default_factory=list)
    cancelled: bool = False


def validate_roots(source: Path, target: Path) -> None:
    if target == source or target.is_relative_to(source):
        raise ValueError("目标不能是来源本身或来源内的文件夹。")


def build_job(result: ScanResult, target_text: str, selected: set[Path],
              suffixes: dict[str, str], skip_identical: bool = True) -> ImportJob:
    target = directory_path(target_text)
    validate_roots(result.source, target)
    if result.cancelled:
        raise ValueError("扫描尚未完成，请重新扫描。")
    items = tuple(PlannedFile(media, build_destination_folder_name(day, suffixes.get(day, "")))
                  for day, group in result.groups.items() for media in group if media.path in selected)
    if not items:
        raise ValueError("请选择需要导入的文件。")
    return ImportJob(result.source, result.source_identity, target, items, skip_identical)


def _assert_source(media: MediaFile, root: Path) -> None:
    _plain_path(media.path, root)
    info = media.path.stat()
    if not stat.S_ISREG(info.st_mode) or not media.matches(info):
        raise ValueError("源文件在扫描后发生变化，请重新扫描。")


def _destination_directory(job: ImportJob, folder: str) -> Path:
    validate_component(folder)
    target = job.target.resolve()
    if target != job.target:
        raise ValueError("目标路径已变化，请重新选择目标。")
    destination = (target / folder).resolve()
    if not destination.is_relative_to(target):
        raise ValueError("目标子文件夹指向所选目录之外。")
    validate_roots(job.source, destination)
    destination.mkdir(parents=True, exist_ok=True)
    if destination.resolve() != destination:
        raise ValueError("目标子文件夹已变化。")
    return destination


def _hash_stream(stream, cancel: Event) -> str:
    digest = hashlib.sha256()
    while True:
        check_cancel(cancel)
        block = stream.read(CHUNK_SIZE)
        if not block:
            break
        digest.update(block)
    return digest.hexdigest()


def _publish_without_overwrite(temporary: Path, destination: Path) -> None:
    # Windows rename refuses an existing destination. POSIX rename would replace it.
    if os.name == "nt":
        os.rename(temporary, destination)
    else:
        os.link(temporary, destination)
        temporary.unlink()


def run_import(job: ImportJob, cancel: Event | None = None,
               progress: Callable[[Progress], None] | None = None) -> ImportResult:
    cancel = cancel or Event()
    result = ImportResult(job)
    total = sum(max(item.media.size, 1) * 2 for item in job.items)
    done = 0
    completed = 0
    started = time.monotonic()
    last_emit = 0.0

    def emit(phase: str, path: Path, current: int = 0, *, force: bool = False) -> None:
        nonlocal last_emit
        now = time.monotonic()
        if progress and (force or now - last_emit >= 0.05):
            progress(Progress(phase, str(path), min(done + current, total), total,
                              completed, len(job.items), now - started))
            last_emit = now

    try:
        check_cancel(cancel)
        if identity(job.source) != job.source_identity:
            raise ValueError("来源设备已变化，请重新扫描。")
        validate_roots(job.source, job.target.resolve())
        if job.target.resolve() != job.target:
            raise ValueError("目标路径已变化。")
        job.target.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=job.target) as probe:
            probe.write(b"copyer")
    except Cancelled:
        result.cancelled = True
        result.files = [FileResult(item, "pending", error="已取消") for item in job.items]
        return result
    except (OSError, ValueError) as exc:
        result.files = [FileResult(item, "failed", error=str(exc)) for item in job.items]
        return result

    for index, item in enumerate(job.items):
        temporary: Path | None = None
        media = item.media
        work = max(media.size, 1)
        try:
            check_cancel(cancel)
            if identity(job.source) != job.source_identity:
                raise ValueError("来源设备已变化，请重新扫描。")
            _assert_source(media, job.source)
            directory = _destination_directory(job, item.folder)
            with _protected_reader(media.path) as source:
                source_stamp = _file_stamp(source)
                if (source_stamp.size, source_stamp.mtime_ns) != (media.size, media.mtime_ns):
                    raise ValueError("源文件已变化，请重新扫描。")
                candidate = directory / media.path.name
                source_digest: str | None = None
                suffix_index = 0
                while os.path.lexists(candidate):
                    check_cancel(cancel)
                    if job.skip_identical and not is_link(candidate) and candidate.is_file() and candidate.stat().st_size == media.size:
                        emit("compare", media.path, force=True)
                        if source_digest is None:
                            source_digest = _hash_stream(source, cancel)
                            source.seek(0)
                        with _protected_reader(candidate) as target:
                            target_stamp = _file_stamp(target)
                            if (_hash_stream(target, cancel) == source_digest
                                    and _file_stamp(target) == target_stamp
                                    and identity(candidate) == target_stamp.identity):
                                _check_import_source(media, job.source, source, source_stamp)
                                result.files.append(FileResult(item, "skipped", candidate,
                                    verified_sha256=source_digest, source_stamp=source_stamp, target_stamp=target_stamp))
                                break
                    suffix_index += 1
                    candidate = directory / f"{media.path.stem}_{suffix_index}{media.path.suffix}"
                else:
                    if shutil.disk_usage(directory).free < media.size:
                        raise ValueError("目标可用空间不足，请更换目标或释放空间。")
                    descriptor, name = tempfile.mkstemp(prefix=".copyer-", suffix=".part", dir=directory)
                    temporary = Path(name)
                    copied = 0
                    source_hash = hashlib.sha256()
                    with os.fdopen(descriptor, "wb") as output:
                        emit("copy", media.path, force=True)
                        while True:
                            check_cancel(cancel)
                            block = source.read(CHUNK_SIZE)
                            if not block:
                                break
                            output.write(block)
                            source_hash.update(block)
                            copied += len(block)
                            emit("copy", media.path, copied)
                        output.flush()
                        os.fsync(output.fileno())
                    if copied != media.size:
                        raise ValueError("复制期间源文件发生变化，请重新扫描。")
                    emit("verify", media.path, work, force=True)
                    shutil.copystat(media.path, temporary, follow_symlinks=False)
                    destination_hash = hashlib.sha256()
                    verified = 0
                    with _protected_reader(temporary, allow_rename=True) as target:
                        before = _file_stamp(target)
                        while True:
                            check_cancel(cancel)
                            block = target.read(CHUNK_SIZE)
                            if not block:
                                break
                            destination_hash.update(block)
                            verified += len(block)
                            emit("verify", media.path, work + verified)
                        if (verified != media.size or destination_hash.digest() != source_hash.digest()
                                or _file_stamp(target) != before):
                            raise ValueError("目标文件校验失败，未提交正式文件。")
                        _check_import_source(media, job.source, source, source_stamp)
                        if _destination_directory(job, item.folder) != directory:
                            raise ValueError("目标子文件夹已变化。")
                        while True:
                            check_cancel(cancel)
                            if identity(temporary) != before.identity:
                                raise ValueError("临时文件已变化，未提交正式文件。")
                            try:
                                _publish_without_overwrite(temporary, candidate)
                                temporary = None
                                break
                            except FileExistsError:
                                candidate = ensure_unique_path(directory, media.path.name)
                        target_stamp = _file_stamp(target)
                        if identity(candidate) != target_stamp.identity:
                            raise ValueError("校验后的目标文件已被替换。")
                    result.files.append(FileResult(item, "copied", candidate, verified_sha256=source_hash.hexdigest(),
                                                    source_stamp=source_stamp, target_stamp=target_stamp))
            completed += 1
            done += work * 2
            emit("compare" if result.files[-1].status == "skipped" else "verified", media.path, force=True)
        except Cancelled:
            result.cancelled = True
            result.files.extend(FileResult(rest, "pending", error="已取消") for rest in job.items[index:])
            break
        except (OSError, ValueError) as exc:
            result.files.append(FileResult(item, "failed", error=str(exc)))
            emit("failed", media.path, force=True)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    # A .part file must never masquerade as a verified final file.
                    for result_index, previous in enumerate(result.files):
                        if previous.item == item:
                            result.files[result_index] = FileResult(item, previous.status, previous.destination,
                                f"{previous.error}；临时文件未能移除：{temporary}（{exc}）")
                            break
    return result


@dataclass
class CleanupResult:
    deleted: list[Path] = field(default_factory=list)
    issues: list[FileIssue] = field(default_factory=list)
    cancelled: bool = False


def cleanup_candidates(files: Iterable[FileResult]) -> tuple[FileResult, ...]:
    return tuple(entry for entry in files if entry.status in {"copied", "skipped"}
                 and entry.destination is not None and entry.verified_sha256
                 and entry.source_stamp is not None and entry.target_stamp is not None)


def _plain_path(path: Path, root: Path) -> None:
    """Reject replaced roots, directory junctions and file links before opening."""
    if not path.is_relative_to(root) or path == root:
        raise ValueError("文件不在本次任务目录内。")
    for part in (path, *path.parents):
        if is_link(part):
            raise ValueError("文件路径包含链接或重解析点，已保留来源。")
    if path.resolve() != path or root.resolve() != root:
        raise ValueError("文件路径已变化，已保留来源。")


@contextmanager
def _protected_reader(path: Path, *, delete_access: bool = False, allow_rename: bool = False):
    """On Windows hold the exact file against writes/renames through deletion."""
    if os.name != "nt":
        with path.open("rb") as stream:
            yield stream
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = _windows_file_api()
    share = 1 | (4 if allow_rename else 0)  # FILE_SHARE_READ | optional FILE_SHARE_DELETE
    handle = kernel.CreateFileW(str(path), 0x80000000 | (0x10000 if delete_access else 0),
                                share, None, 3, 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, "rb") as stream:
        yield stream


@lru_cache(maxsize=1)
def _windows_file_api():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    for function in (kernel.GetFileInformationByHandleEx, kernel.SetFileInformationByHandle):
        function.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        function.restype = wintypes.BOOL
    return kernel


def _file_stamp(stream) -> FileStamp:
    info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode) or is_link_info(info):
        raise ValueError("不是普通文件。")
    change_time = info.st_ctime_ns
    if os.name == "nt":
        import ctypes
        import msvcrt

        # FILE_BASIC_INFO has four 64-bit timestamps followed by file attributes.
        # Python 3.11's Windows st_ctime is creation time, not change time.
        basic = (ctypes.c_longlong * 5)()
        if not _windows_file_api().GetFileInformationByHandleEx(
                msvcrt.get_osfhandle(stream.fileno()), 0, ctypes.byref(basic), ctypes.sizeof(basic)):
            raise ctypes.WinError(ctypes.get_last_error())
        if basic[4] & 0x400:
            raise ValueError("文件路径包含重解析点。")
        change_time = basic[3]
    return FileStamp((info.st_dev, info.st_ino), info.st_size, info.st_mtime_ns, change_time)


def _check_import_source(media: MediaFile, root: Path, stream, stamp: FileStamp) -> None:
    _plain_path(media.path, root)
    if _file_stamp(stream) != stamp or identity(media.path) != stamp.identity:
        raise ValueError("导入期间源文件发生变化，请重新扫描。")


def _delete_open_source(stream, path: Path) -> None:
    if os.name != "nt":
        if identity(path) != (os.fstat(stream.fileno()).st_dev, os.fstat(stream.fileno()).st_ino):
            raise ValueError("源文件已被替换。")
        path.unlink()
        return
    import ctypes
    import msvcrt
    dispose = _windows_file_api().SetFileInformationByHandle
    # FILE_DISPOSITION_INFO.DeleteFile is a one-byte BOOLEAN.
    flag = ctypes.c_ubyte(1)
    if not dispose(msvcrt.get_osfhandle(stream.fileno()), 4, ctypes.byref(flag), ctypes.sizeof(flag)):
        raise ctypes.WinError(ctypes.get_last_error())


def run_cleanup(job: ImportJob, files: Iterable[FileResult], cancel: Event | None = None,
                progress: Callable[[Progress], None] | None = None) -> CleanupResult:
    """Delete files whose current attributes match their verified import receipts."""
    cancel = cancel or Event()
    result = CleanupResult()
    candidates = cleanup_candidates(files)
    allowed_items = set(job.items)
    total = len(candidates)
    started = time.monotonic()
    last_emit = 0.0
    for processed, entry in enumerate(candidates):
        media, destination = entry.item.media, entry.destination
        try:
            check_cancel(cancel)
            now = time.monotonic()
            if progress and now - last_emit >= 0.05:
                progress(Progress("cleanup", str(media.path), processed, total,
                                  processed, total, now - started))
                last_emit = now
                check_cancel(cancel)
            if entry.item not in allowed_items or identity(job.source) != job.source_identity:
                raise ValueError("来源设备或任务已变化，已保留来源。")
            validate_roots(job.source, job.target)
            _plain_path(media.path, job.source)
            _plain_path(destination, job.target)
            with _protected_reader(destination) as target, _protected_reader(media.path, delete_access=True) as source:
                source_stamp, target_stamp = _file_stamp(source), _file_stamp(target)
                if source_stamp != entry.source_stamp or target_stamp != entry.target_stamp:
                    raise ValueError("源文件或目标文件与导入时的校验记录不一致，已保留来源。")
                if source_stamp.identity == target_stamp.identity:
                    raise ValueError("目标与来源是同一文件，已保留来源。")
                _plain_path(media.path, job.source)
                _plain_path(destination, job.target)
                if identity(media.path) != source_stamp.identity or identity(destination) != target_stamp.identity:
                    raise ValueError("源文件或目标文件已被替换，已保留来源。")
                check_cancel(cancel)
                _delete_open_source(source, media.path)
            result.deleted.append(media.path)
        except Cancelled:
            result.cancelled = True
            break
        except (OSError, ValueError) as exc:
            result.issues.append(FileIssue(media.path, str(exc)))
    if progress and not result.cancelled and total:
        progress(Progress("cleanup", str(candidates[-1].item.media.path), total, total,
                          total, total, time.monotonic() - started))
    return result
