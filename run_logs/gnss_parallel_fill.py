"""GNSS 并行补绘脚本。

和全量重绘不同，这个脚本会检查现有输出文件的修改时间：

- 文件不存在：重新绘制
- 文件存在但时间早于阈值：重新绘制
- 文件存在且时间不早于阈值：跳过
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import logging
from pathlib import Path
import sys

ROOT = Path(r"D:\Desktop\lzt_thesis_code")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "GNSSdraw"))

from GNSS_draw.batch_export import build_output_path, render_slice
from GNSS_draw.config import load_config
from GNSS_draw.reader import iter_time_slices, scan_nc_files

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")

CFG_ROOT = ROOT / "GNSSdraw" / "GNSS_draw"
CATEGORY_CONFIGS = {
    "VTEC": CFG_ROOT / "config_vtec.toml",
    "dTEC": CFG_ROOT / "config_dtec.toml",
    "ROTI": CFG_ROOT / "config_roti.toml",
}

# 这些阈值用于判断“旧图”是否需要补绘。
THRESHOLDS = {
    "VTEC": datetime(2026, 4, 2, 2, 38, 22).timestamp(),
    "dTEC": datetime(2026, 4, 2, 2, 49, 48).timestamp(),
    "ROTI": datetime(2026, 4, 2, 2, 49, 48).timestamp(),
}

SOURCE_DIRS = {"VTEC": "VTEC_data", "dTEC": "dTEC_data", "ROTI": "ROTI_data"}


def build_tasks() -> list[tuple[str, str, str, str, float]]:
    """构造所有补绘任务。"""
    tasks: list[tuple[str, str, str, str, float]] = []
    for category, cfg_path in CATEGORY_CONFIGS.items():
        cfg = load_config(cfg_path, "batch")
        data_dir = cfg.data.root / SOURCE_DIRS[category]
        for year_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
            for doy_dir in sorted(p for p in year_dir.iterdir() if p.is_dir()):
                tasks.append((str(cfg_path), category, year_dir.name, doy_dir.name, THRESHOLDS[category]))
    return tasks


def worker(task: tuple[str, str, str, str, float]) -> tuple[str, str, str, int, int]:
    """执行单个补绘任务。"""
    cfg_path, category, year, doy, threshold = task
    cfg = load_config(cfg_path, "batch")
    files = scan_nc_files(cfg.data.root, category, year, doys=(doy,))
    rendered = 0
    skipped = 0
    for file_path in files:
        for slice_data in iter_time_slices(file_path, category):
            output_path = build_output_path(cfg, slice_data)
            if output_path.exists() and output_path.stat().st_mtime >= threshold:
                skipped += 1
                continue
            result = render_slice(slice_data, cfg, allow_skip=True)
            if result is not None:
                rendered += 1
    return category, year, doy, rendered, skipped


def main() -> None:
    """脚本主入口。"""
    tasks = build_tasks()
    max_workers = 8
    print(f"[INFO] Starting GNSS parallel refill with {len(tasks)} tasks and {max_workers} workers.")
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(worker, task): task for task in tasks}
        for future in as_completed(futures):
            category, year, doy, rendered, skipped = future.result()
            print(f"[DONE] {category} {year}-{doy}: rendered={rendered} skipped_current={skipped}")
            results.append((category, year, doy, rendered, skipped))

    summary: dict[str, list[int]] = {}
    for category, year, doy, rendered, skipped in results:
        summary.setdefault(category, [0, 0])
        summary[category][0] += rendered
        summary[category][1] += skipped
    for category in sorted(summary):
        rendered, skipped = summary[category]
        print(f"[SUMMARY] {category}: rendered={rendered} skipped_current={skipped}")


if __name__ == "__main__":
    main()
