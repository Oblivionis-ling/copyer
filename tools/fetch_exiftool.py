"""Install the pinned, checksum-verified Windows metadata runtime for builds."""
from __future__ import annotations

import argparse
import hashlib
import html
from pathlib import Path
import re
import shutil
import tempfile
from urllib.request import urlopen
from urllib.parse import urlparse
import zipfile

VERSION = "13.60"
SHA256 = "548b1f4e0b713cd2a26824b34080c35db4e2d2edd166468eb38b1d55ada90c2e"
URL = f"https://downloads.sourceforge.net/project/exiftool/exiftool-{VERSION}_64.zip"
ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "vendor" / "exiftool"


def install(archive: Path | None = None) -> None:
    marker = DESTINATION / "distribution.sha256"
    if (marker.is_file() and marker.read_text().strip() == SHA256
            and (DESTINATION / "exiftool_files/perl.exe").is_file()
            and (DESTINATION / "exiftool_files/exiftool.pl").is_file()):
        print(f"ExifTool {VERSION} is ready.")
        return
    with tempfile.TemporaryDirectory(prefix="copyer-exiftool-") as temporary:
        downloaded = Path(temporary) / "exiftool.zip"
        if archive is not None:
            shutil.copyfile(archive, downloaded)
        else:
            url = URL
            for attempt in range(3):
                with urlopen(url, timeout=90) as response, downloaded.open("wb") as output:
                    shutil.copyfileobj(response, output)
                if zipfile.is_zipfile(downloaded):
                    break
                # SourceForge may return an HTML download page with a refresh URL.
                page = downloaded.read_text(encoding="utf-8", errors="replace")
                redirect = re.search(r'url=(https://downloads\.sourceforge\.net/[^"<>]+)', page)
                if not redirect:
                    raise RuntimeError("ExifTool download did not return a ZIP archive.")
                url = html.unescape(redirect[1])
                if urlparse(url).hostname != "downloads.sourceforge.net":
                    raise RuntimeError("Unexpected ExifTool download host.")
        if hashlib.sha256(downloaded.read_bytes()).hexdigest() != SHA256:
            raise RuntimeError("ExifTool SHA-256 mismatch; runtime was not installed.")
        with zipfile.ZipFile(downloaded) as bundle:
            for entry in bundle.infolist():
                parts = Path(entry.filename).parts
                if not parts or parts[0] != f"exiftool-{VERSION}_64":
                    raise RuntimeError("Unexpected ExifTool archive layout.")
                target = DESTINATION.joinpath(*parts[1:]).resolve()
                if not target.is_relative_to(DESTINATION.resolve()):
                    raise RuntimeError("Unsafe ExifTool archive path.")
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(entry) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
        marker.write_text(SHA256 + "\n", encoding="ascii")
    print(f"Installed ExifTool {VERSION}; official SHA-256 verified.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use an already downloaded official ZIP")
    install(parser.parse_args().archive)
