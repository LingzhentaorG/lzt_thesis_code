from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime
import html.parser
import os
import time
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


SOURCE_TEMPLATES = {
    "VTEC": "https://stdb2.isee.nagoya-u.ac.jp/GPS/shinbori/AGRID2/nc/{year}/",
    "dTEC": "https://stdb2.isee.nagoya-u.ac.jp/GPS/shinbori/GRID2/nc/{year}/",
    "ROTI": "https://stdb2.isee.nagoya-u.ac.jp/GPS/shinbori/RGRID2/nc/{year}/",
}

DEFAULT_YEAR = "2024"
DEFAULT_DOYS = ["130", "131", "132", "133", "283", "284", "285", "286"]
CHUNK_SIZE = 1024 * 1024
RETRY_COUNT = 3


class NcLinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        if href and href.lower().endswith(".nc"):
            self.links.append(href)


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8", errors="ignore")


def list_nc_files(base_url: str, doy: str) -> list[tuple[str, str]]:
    day_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", f"{doy}/")
    parser = NcLinkParser()
    parser.feed(fetch_text(day_url))
    files = sorted(set(parser.links))
    return [(urllib.parse.urljoin(day_url, name), name) for name in files]


def download_file(url: str, destination: Path, overwrite: bool = False) -> str:
    if destination.exists() and not overwrite and destination.stat().st_size > 0:
        return "skipped"

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")

    last_error: Exception | None = None
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temp_path.open("wb") as handle:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
            os.replace(temp_path, destination)
            return "downloaded"
        except Exception as exc:
            last_error = exc
            if temp_path.exists():
                temp_path.unlink()
            if attempt < RETRY_COUNT:
                time.sleep(2 * attempt)

    assert last_error is not None
    raise last_error


def build_tasks(root: Path, year_doys: list[tuple[str, str]]) -> list[tuple[str, str, str, str, Path]]:
    tasks: list[tuple[str, str, str, Path]] = []
    for source_name, base_template in SOURCE_TEMPLATES.items():
        for year, doy in year_doys:
            base_url = base_template.format(year=year)
            output_root = root / f"{source_name}_data" / year
            for file_url, file_name in list_nc_files(base_url, doy):
                destination = output_root / doy / file_name
                tasks.append((source_name, year, doy, file_url, destination))
    return tasks


def parse_dates(dates: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for value in dates:
        try:
            current = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Invalid date '{value}'. Expected YYYY-MM-DD.") from exc
        parsed.append((str(current.year), f"{current.timetuple().tm_yday:03d}"))
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Download .nc files for configured data sources.")
    parser.add_argument("--root", default=".", help="Project root directory.")
    parser.add_argument("--year", default=DEFAULT_YEAR, help="Year used with --doys when --dates is not set.")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent download workers.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    parser.add_argument("--doys", nargs="+", default=DEFAULT_DOYS, help="Day-of-year values to download.")
    parser.add_argument(
        "--dates",
        nargs="+",
        help="Explicit UTC dates in YYYY-MM-DD format. Overrides --year and --doys.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    try:
        if args.dates:
            year_doys = parse_dates(args.dates)
        else:
            year_doys = [(str(args.year), str(doy).zfill(3)) for doy in args.doys]
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        tasks = build_tasks(root, year_doys)
    except urllib.error.URLError as exc:
        print(f"Failed to list remote directories: {exc}", file=sys.stderr)
        return 1

    if not tasks:
        print("No .nc files found.")
        return 1

    counts: dict[str, int] = {}
    for source_name, _, _, _, _ in tasks:
        counts[source_name] = counts.get(source_name, 0) + 1

    print("Planned downloads:")
    for source_name in SOURCE_TEMPLATES:
        print(f"  {source_name}: {counts.get(source_name, 0)} files")

    lock = threading.Lock()
    downloaded = 0
    skipped = 0
    failed = 0

    def worker(task: tuple[str, str, str, str, Path]) -> None:
        nonlocal downloaded, skipped, failed
        source_name, year, doy, url, destination = task
        try:
            status = download_file(url, destination, overwrite=args.force)
            with lock:
                if status == "downloaded":
                    downloaded += 1
                else:
                    skipped += 1
                print(f"[{status.upper()}] {source_name} {year}/{doy} {destination.name}")
        except Exception as exc:
            with lock:
                failed += 1
                print(f"[FAILED] {source_name} {year}/{doy} {destination.name}: {exc}", file=sys.stderr)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(worker, task) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    print(
        f"Finished. downloaded={downloaded} skipped={skipped} failed={failed} total={len(tasks)}"
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
