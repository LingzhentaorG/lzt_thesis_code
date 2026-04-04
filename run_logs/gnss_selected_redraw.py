"""并行补绘指定 GNSS 类别的缺失图片。"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(r"D:\Desktop\lzt_thesis_code")
sys.path.insert(0, str(ROOT / "GNSSdraw"))

from GNSS_draw.batch_export import build_output_path, render_slice  # noqa: E402
from GNSS_draw.config import load_config  # noqa: E402
from GNSS_draw.reader import iter_time_slices, scan_nc_files  # noqa: E402


CATEGORY_CONFIGS = {
    "VTEC": ROOT / "GNSSdraw" / "GNSS_draw" / "config_vtec.toml",
    "dTEC": ROOT / "GNSSdraw" / "GNSS_draw" / "config_dtec.toml",
    "ROTI": ROOT / "GNSSdraw" / "GNSS_draw" / "config_roti.toml",
}

SOURCE_DIRS = {
    "VTEC": "VTEC_data",
    "dTEC": "dTEC_data",
    "ROTI": "ROTI_data",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Redraw missing GNSS figures for selected categories.")
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=tuple(CATEGORY_CONFIGS),
        default=["VTEC", "ROTI"],
        help="Categories to process. Defaults to VTEC ROTI.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=min(10, os.cpu_count() or 8),
        help="Maximum worker processes.",
    )
    return parser.parse_args()


def build_tasks(categories: list[str]) -> list[tuple[str, str, str, str]]:
    tasks: list[tuple[str, str, str, str]] = []
    for category in categories:
        config_path = CATEGORY_CONFIGS[category]
        config = load_config(config_path, "batch")
        source_root = config.data.root / SOURCE_DIRS[category]
        years = set(config.data.years or ([config.data.year] if config.data.year else []))
        for year_dir in sorted(path for path in source_root.iterdir() if path.is_dir() and path.name in years):
            for doy_dir in sorted(path for path in year_dir.iterdir() if path.is_dir()):
                tasks.append((str(config_path), category, year_dir.name, doy_dir.name))
    return tasks


def render_task(task: tuple[str, str, str, str]) -> tuple[str, str, str, int, int, int]:
    config_path, category, year, doy = task
    config = load_config(Path(config_path), "batch")
    files = scan_nc_files(config.data.root, category, year, doys=(doy,))

    rendered = 0
    skipped_empty = 0
    skipped_existing = 0
    for file_path in files:
        for slice_data in iter_time_slices(file_path, category):
            output_path = build_output_path(config, slice_data)
            if output_path.exists():
                skipped_existing += 1
                continue
            result = render_slice(slice_data, config, allow_skip=True)
            if result is not None:
                rendered += 1
            else:
                skipped_empty += 1

    return category, year, doy, rendered, skipped_empty, skipped_existing


def main() -> int:
    args = parse_args()
    tasks = build_tasks(args.categories)
    max_workers = min(args.workers, len(tasks)) if tasks else 0
    print(
        f"[INFO] Starting GNSS selected redraw with {len(tasks)} tasks, "
        f"{max_workers} workers, categories={','.join(args.categories)}.",
        flush=True,
    )

    summary = {
        category: {"rendered": 0, "skipped_empty": 0, "skipped_existing": 0}
        for category in args.categories
    }
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(render_task, task): task for task in tasks}
        for future in as_completed(futures):
            category, year, doy, rendered, skipped_empty, skipped_existing = future.result()
            summary[category]["rendered"] += rendered
            summary[category]["skipped_empty"] += skipped_empty
            summary[category]["skipped_existing"] += skipped_existing
            print(
                f"[DONE] {category} {year}-{doy}: "
                f"rendered={rendered} skipped_empty={skipped_empty} skipped_existing={skipped_existing}",
                flush=True,
            )

    for category in args.categories:
        stats = summary[category]
        print(
            f"[SUMMARY] {category}: rendered={stats['rendered']} "
            f"skipped_empty={stats['skipped_empty']} skipped_existing={stats['skipped_existing']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
