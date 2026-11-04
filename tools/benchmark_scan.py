"""Repeatable local scan benchmark using metadata fixtures, never user media."""
from pathlib import Path
import argparse
import json
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import copyer_core as core


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=300)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cache', action='store_true', help='Keep the same-session metadata cache between scans')
    args = parser.parse_args()
    fixtures = ['CanonRaw.cr3', 'DNG.dng', 'Nikon.nef', 'QuickTime.mov', 'QuickTime.heic']
    with tempfile.TemporaryDirectory(prefix='copyer-benchmark-') as temporary:
        source = Path(temporary)
        for index in range(args.count):
            fixture = fixtures[index % len(fixtures)]
            shutil.copyfile(ROOT / 'tests/fixtures/exiftool' / fixture,
                            source / (str(index) + Path(fixture).suffix))
        timings = []
        signatures = []
        cache = {} if args.cache else None
        for _ in range(3):
            start = time.perf_counter()
            result = core.scan(str(source), core.RAW_EXTENSIONS | core.PHOTO_EXTENSIONS | core.VIDEO_EXTENSIONS,
                               metadata_cache=cache)
            timings.append(round(time.perf_counter()-start, 4))
            signatures.append(sorted((file.path.name, file.date_text, file.date_source, file.date_detail)
                                     for file in result.files if file.date_source != '文件修改时间（无拍摄日期）'))
            assert len(result.files) == args.count and not result.issues
        assert signatures[0] == signatures[1] == signatures[2]
        report = {'files': args.count, 'seconds': timings, 'median': sorted(timings)[1],
                  'metadata': signatures[0]}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key != 'metadata'}))


if __name__ == '__main__':
    main()
