from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import sys
import logging

ROOT = Path(r'D:\Desktop\lzt_thesis_code')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'GNSSdraw'))

from GNSS_draw.config import load_config
from GNSS_draw.reader import scan_nc_files, iter_time_slices
from GNSS_draw.batch_export import build_output_path, render_slice

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')

CFG_ROOT = ROOT / 'GNSSdraw' / 'GNSS_draw'
CATEGORY_CONFIGS = {
    'VTEC': CFG_ROOT / 'config_vtec.toml',
    'dTEC': CFG_ROOT / 'config_dtec.toml',
    'ROTI': CFG_ROOT / 'config_roti.toml',
}
THRESHOLDS = {
    'VTEC': datetime(2026, 4, 2, 2, 38, 22).timestamp(),
    'dTEC': datetime(2026, 4, 2, 2, 49, 48).timestamp(),
    'ROTI': datetime(2026, 4, 2, 2, 49, 48).timestamp(),
}
SOURCE_DIRS = {'VTEC':'VTEC_data','dTEC':'dTEC_data','ROTI':'ROTI_data'}


def build_tasks():
    tasks = []
    for category, cfg_path in CATEGORY_CONFIGS.items():
        cfg = load_config(cfg_path, 'batch')
        data_dir = cfg.data.root / SOURCE_DIRS[category]
        for year_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
            for doy_dir in sorted(p for p in year_dir.iterdir() if p.is_dir()):
                tasks.append((str(cfg_path), category, year_dir.name, doy_dir.name, THRESHOLDS[category]))
    return tasks


def worker(task):
    cfg_path, category, year, doy, threshold = task
    cfg = load_config(cfg_path, 'batch')
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


def main():
    tasks = build_tasks()
    max_workers = 8
    print(f'[INFO] Starting GNSS parallel refill with {len(tasks)} tasks and {max_workers} workers.')
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(worker, task): task for task in tasks}
        for future in as_completed(futures):
            category, year, doy, rendered, skipped = future.result()
            print(f'[DONE] {category} {year}-{doy}: rendered={rendered} skipped_current={skipped}')
            results.append((category, year, doy, rendered, skipped))

    summary = {}
    for category, year, doy, rendered, skipped in results:
        summary.setdefault(category, [0, 0])
        summary[category][0] += rendered
        summary[category][1] += skipped
    for category in sorted(summary):
        rendered, skipped = summary[category]
        print(f'[SUMMARY] {category}: rendered={rendered} skipped_current={skipped}')


if __name__ == '__main__':
    main()
