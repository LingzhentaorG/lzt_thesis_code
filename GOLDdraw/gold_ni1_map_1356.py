#!/usr/bin/env python
"""GOLD NI1 135.6 nm 散点制图脚本。

该脚本直接读取 `.tar` 归档中的 GOLD NI1 NetCDF 文件，自动完成：

1. 识别 `CHA` 与 `CHB` 两个半球观测通道
2. 按时间配对两类观测
3. 提取最接近 135.6 nm 的辐亮度
4. 合并成一张地理定位散点图
5. 输出为批量 PNG 文件
"""

from __future__ import annotations

import argparse
import re
import tarfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

import cartopy.crs as ccrs  # type: ignore[import-untyped]
import cartopy.feature as cfeature  # type: ignore[import-untyped]
import matplotlib
import numpy as np
from apexpy import Apex  # type: ignore[import-untyped]
from cartopy.mpl.gridliner import Gridliner  # type: ignore[import-untyped]
from mpl_toolkits.axes_grid1 import make_axes_locatable
from netCDF4 import Dataset  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from cartopy.mpl.geoaxes import GeoAxes  # type: ignore[import-untyped]

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


FILE_PATTERN = re.compile(
    r"GOLD_L1C_(CH[AB])_NI1_(\d{4})_(\d{3})_(\d{2})_(\d{2})_.*\.nc$"
)


@dataclass(frozen=True)
class ArchiveEntry:
    """表示归档中的一个可用 NetCDF 成员。"""

    tar_path: Path
    member_name: str
    hemisphere: str
    obs_time: datetime


@dataclass(frozen=True)
class PairMatch:
    """表示一个成功配对的 `CHA/CHB` 观测对。"""

    cha: ArchiveEntry
    chb: ArchiveEntry
    delta: timedelta

    @property
    def midpoint(self) -> datetime:
        """返回两路观测时间的中点，作为图题和输出命名的主时间。"""
        return self.cha.obs_time + (self.chb.obs_time - self.cha.obs_time) / 2


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description=(
            "Read GOLD NI1 CHA/CHB NetCDF files directly from .tar archives and "
            "save one geolocated PNG per matched pair."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=["."],
        help="One or more .tar files or directories containing .tar files. Default: current directory.",
    )
    parser.add_argument(
        "--output-root",
        default="png_output",
        help="Directory used to store the generated PNG files.",
    )
    parser.add_argument(
        "--target-nm",
        type=float,
        default=135.6,
        help="Target wavelength in nm. Default: 135.6",
    )
    parser.add_argument(
        "--max-pair-minutes",
        type=float,
        default=5.0,
        help="Maximum allowed CHA/CHB start-time difference in minutes.",
    )
    parser.add_argument(
        "--quality-mode",
        choices=("good", "all"),
        default="all",
        help="'all' keeps all finite pixels; 'good' keeps only QUALITY_FLAG == 0 pixels.",
    )
    parser.add_argument(
        "--vmin",
        type=float,
        default=0.0,
        help="Lower bound of the color scale.",
    )
    parser.add_argument(
        "--vmax",
        type=float,
        default=300.0,
        help="Upper bound of the color scale.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=180,
        help="PNG output DPI.",
    )
    parser.add_argument(
        "--figsize",
        nargs=2,
        type=float,
        metavar=("WIDTH", "HEIGHT"),
        default=(7.2, 5.8),
        help="Figure size in inches. Default: 7.2 5.8",
    )
    parser.add_argument(
        "--point-size",
        type=float,
        default=9.0,
        help="Scatter point size in points^2.",
    )
    parser.add_argument(
        "--extent",
        nargs=4,
        type=float,
        metavar=("WEST", "EAST", "SOUTH", "NORTH"),
        default=(-105.0, 15.0, -60.0, 60.0),
        help=(
            "Fixed map extent in degrees. "
            "Default: -105 15 -60 60 (105W to 15E, latitude within 60 degrees)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N matched pairs from each archive.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print one line per generated PNG file.",
    )
    return parser.parse_args()


def iter_tar_paths(raw_inputs: Iterable[str]) -> list[Path]:
    """把输入参数统一展开为去重后的 `.tar` 路径列表。"""
    tar_paths: list[Path] = []
    for raw in raw_inputs:
        path = Path(raw).expanduser().resolve()
        if path.is_file() and path.suffix.lower() == ".tar":
            tar_paths.append(path)
            continue
        if path.is_dir():
            tar_paths.extend(sorted(p.resolve() for p in path.rglob("*.tar")))
            continue
        raise FileNotFoundError(f"Input path is not a .tar file or directory: {path}")
    unique_paths = sorted(dict.fromkeys(tar_paths))
    if not unique_paths:
        raise FileNotFoundError("No .tar files were found in the provided inputs.")
    return unique_paths


def parse_entry(tar_path: Path, member_name: str) -> ArchiveEntry | None:
    """从文件名中解析半球标识与观测时间。"""
    match = FILE_PATTERN.search(member_name)
    if not match:
        return None
    hemisphere, year, doy, hour, minute = match.groups()
    obs_time = datetime.strptime(f"{year} {doy} {hour} {minute}", "%Y %j %H %M")
    return ArchiveEntry(
        tar_path=tar_path,
        member_name=member_name,
        hemisphere=hemisphere,
        obs_time=obs_time,
    )


def discover_entries(tar_path: Path) -> list[ArchiveEntry]:
    """扫描一个归档，提取其中全部可识别的 GOLD NI1 成员。"""
    entries: list[ArchiveEntry] = []
    with tarfile.open(tar_path) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            entry = parse_entry(tar_path, member.name)
            if entry is not None:
                entries.append(entry)
    return sorted(entries, key=lambda item: (item.obs_time, item.hemisphere, item.member_name))


def match_pairs(entries: list[ArchiveEntry], max_delta_minutes: float) -> tuple[list[PairMatch], list[ArchiveEntry]]:
    """按时间差贪心匹配 `CHA` 与 `CHB` 观测。"""
    cha_entries = [entry for entry in entries if entry.hemisphere == "CHA"]
    chb_entries = [entry for entry in entries if entry.hemisphere == "CHB"]
    max_delta = timedelta(minutes=max_delta_minutes)

    candidates: list[tuple[timedelta, int, int]] = []
    for cha_index, cha_entry in enumerate(cha_entries):
        for chb_index, chb_entry in enumerate(chb_entries):
            if cha_entry.obs_time.date() != chb_entry.obs_time.date():
                continue
            delta = abs(chb_entry.obs_time - cha_entry.obs_time)
            if delta <= max_delta:
                candidates.append((delta, cha_index, chb_index))

    # 先按时间差最小排序，再做一次不重复使用的贪心配对。
    candidates.sort(
        key=lambda item: (
            item[0],
            cha_entries[item[1]].obs_time,
            chb_entries[item[2]].obs_time,
        )
    )

    used_cha: set[int] = set()
    used_chb: set[int] = set()
    pairs: list[PairMatch] = []
    for delta, cha_index, chb_index in candidates:
        if cha_index in used_cha or chb_index in used_chb:
            continue
        used_cha.add(cha_index)
        used_chb.add(chb_index)
        pairs.append(
            PairMatch(
                cha=cha_entries[cha_index],
                chb=chb_entries[chb_index],
                delta=delta,
            )
        )

    unmatched = [
        entry
        for index, entry in enumerate(cha_entries)
        if index not in used_cha
    ] + [
        entry
        for index, entry in enumerate(chb_entries)
        if index not in used_chb
    ]

    pairs.sort(key=lambda pair: (pair.midpoint, pair.cha.obs_time, pair.chb.obs_time))
    unmatched.sort(key=lambda item: (item.obs_time, item.hemisphere))
    return pairs, unmatched


def read_dataset_bytes(archive: tarfile.TarFile, member_name: str) -> bytes:
    """从 tar 归档中读取指定成员的原始字节。"""
    extracted = archive.extractfile(member_name)
    if extracted is None:
        raise FileNotFoundError(f"Failed to read {member_name} from archive.")
    return extracted.read()


def read_geo_points(
    archive: tarfile.TarFile,
    member_name: str,
    target_nm: float,
    quality_mode: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """读取单个观测条带的经纬度点云与目标波长辐亮度。"""
    dataset_bytes = read_dataset_bytes(archive, member_name)
    with Dataset("inmemory.nc", memory=dataset_bytes) as dataset:
        latitude = np.ma.filled(dataset.variables["REFERENCE_POINT_LAT"][:], np.nan).astype(np.float64)
        longitude = np.ma.filled(dataset.variables["REFERENCE_POINT_LON"][:], np.nan).astype(np.float64)
        wavelength = np.ma.filled(dataset.variables["WAVELENGTH"][:], np.nan).astype(np.float64)
        radiance = np.ma.filled(dataset.variables["RADIANCE"][:], np.nan).astype(np.float64)
        quality_flag = np.ma.filled(dataset.variables["QUALITY_FLAG"][:], 0).astype(np.uint32)

    # 每个像元的波长轴上选择最接近目标波长的位置。
    nearest_index = np.abs(wavelength - target_nm).argmin(axis=2)
    radiance_1356 = np.take_along_axis(radiance, nearest_index[..., None], axis=2)[..., 0]

    # 仅保留坐标和辐亮度都有效的像元；必要时进一步按质量标志筛选。
    valid = np.isfinite(latitude) & np.isfinite(longitude) & np.isfinite(radiance_1356)
    valid &= (latitude >= -90.0) & (latitude <= 90.0)
    valid &= (longitude >= -180.0) & (longitude <= 180.0)
    if quality_mode == "good":
        valid &= quality_flag == 0

    return longitude[valid], latitude[valid], radiance_1356[valid]


def format_pair_title(pair: PairMatch) -> str:
    """生成图题文字。"""
    midpoint = pair.midpoint.strftime("%Y-%m-%d %H:%MUT")
    if pair.cha.obs_time == pair.chb.obs_time:
        return midpoint
    cha_time = pair.cha.obs_time.strftime("%H:%M")
    chb_time = pair.chb.obs_time.strftime("%H:%M")
    return f"{midpoint}  |  CHA {cha_time} + CHB {chb_time}"


def format_output_name(pair: PairMatch, target_nm: float) -> str:
    """生成输出 PNG 文件名。"""
    midpoint = pair.midpoint.strftime("%Y%m%dT%H%MZ")
    cha_label = pair.cha.obs_time.strftime("%H%M")
    chb_label = pair.chb.obs_time.strftime("%H%M")
    wavelength_label = str(target_nm).replace(".", "p")
    return f"{midpoint}_CHA-{cha_label}_CHB-{chb_label}_{wavelength_label}nm.png"


def add_map_background(ax: GeoAxes) -> None:
    """为地图添加海洋、陆地、边界和经纬网背景。"""
    ax.set_facecolor("#b7d6e6")
    ax.add_feature(
        cfeature.OCEAN.with_scale("110m"),
        facecolor="#b7d6e6",
        edgecolor="none",
        zorder=0,
    )
    ax.add_feature(
        cfeature.LAND.with_scale("110m"),
        facecolor="#efefef",
        edgecolor="#9a9a9a",
        linewidth=0.4,
        zorder=1,
    )
    ax.add_feature(
        cfeature.BORDERS.with_scale("110m"),
        edgecolor="#9a9a9a",
        linewidth=0.35,
        zorder=4,
    )
    ax.coastlines(resolution="110m", color="#4c4c4c", linewidth=0.55, zorder=4)
    gl = ax.gridlines(
        crs=ccrs.PlateCarree(),
        draw_labels=True,
        linewidth=0.5,
        linestyle=":",
        color="#5a7a8a",
        alpha=0.8,
        zorder=2,
    )
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"size": 8}
    gl.ylabel_style = {"size": 8}


def compute_magnetic_equator(
    apex: Apex,
    extent: tuple[float, float, float, float],
    num_points: int = 500,
) -> tuple[np.ndarray, np.ndarray]:
    """
    计算磁赤道线的经纬度坐标。

    参数:
        apex: ApexPy 实例
        extent: 地图范围 (west, east, south, north)
        num_points: 采样点数

    返回:
        (longitude, latitude) 磁赤道线的坐标数组
    """
    west, east, south, north = extent
    lon_line = np.linspace(west, east, num_points)
    lat_line = np.zeros_like(lon_line)

    for i, lon in enumerate(lon_line):
        lat_guess = 0.0
        for _ in range(10):
            mlat, _ = apex.geo2apex(lat_guess, lon, 0)
            if np.isnan(mlat):
                break
            lat_guess = lat_guess - mlat
            if abs(mlat) < 0.01:
                break
        lat_line[i] = np.clip(lat_guess, south, north)

    valid = np.isfinite(lat_line) & (lat_line >= south) & (lat_line <= north)
    return lon_line[valid], lat_line[valid]


def add_magnetic_equator(
    ax: GeoAxes,
    apex: Apex,
    extent: tuple[float, float, float, float],
) -> None:
    """
    在地图上绘制磁赤道线。

    参数:
        ax: matplotlib 坐标轴
        apex: ApexPy 实例
        extent: 地图范围
    """
    lon_eq, lat_eq = compute_magnetic_equator(apex, extent)
    if len(lon_eq) > 1:
        ax.plot(
            lon_eq,
            lat_eq,
            color="red",
            linewidth=1.2,
            linestyle="--",
            transform=ccrs.PlateCarree(),
            zorder=5,
            label="Magnetic Equator",
        )


def plot_pair(
    pair: PairMatch,
    archive: tarfile.TarFile,
    output_path: Path,
    target_nm: float,
    quality_mode: str,
    figsize: tuple[float, float],
    point_size: float,
    extent: tuple[float, float, float, float],
    vmin: float,
    vmax: float,
    dpi: int,
    apex: Apex,
) -> None:
    """把一个 `CHA/CHB` 配对绘制成单张散点图。"""
    cha_lon, cha_lat, cha_rad = read_geo_points(archive, pair.cha.member_name, target_nm, quality_mode)
    chb_lon, chb_lat, chb_rad = read_geo_points(archive, pair.chb.member_name, target_nm, quality_mode)

    # 两个半球的有效点直接拼接成一套散点坐标。
    longitude = np.concatenate([cha_lon, chb_lon])
    latitude = np.concatenate([cha_lat, chb_lat])
    radiance = np.concatenate([cha_rad, chb_rad])
    if radiance.size == 0:
        raise RuntimeError(
            "No valid pixels remained after masking. "
            "Try --quality-mode all if you want to inspect everything."
        )

    fig, ax = plt.subplots(
        figsize=figsize,
        subplot_kw={"projection": ccrs.PlateCarree()},
    )
    geo_ax: GeoAxes = ax  # type: ignore[assignment]
    add_map_background(geo_ax)
    geo_ax.set_extent(extent, crs=ccrs.PlateCarree())

    mesh = geo_ax.scatter(
        longitude,
        latitude,
        c=radiance,
        s=point_size,
        marker="o",
        linewidths=0,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        transform=ccrs.PlateCarree(),
        zorder=3,
        rasterized=True,
    )

    add_magnetic_equator(geo_ax, apex, extent)

    divider = make_axes_locatable(geo_ax)
    cax = divider.append_axes("right", size="3%", pad=0.1, axes_class=plt.Axes)
    colorbar = fig.colorbar(mesh, cax=cax)
    colorbar.set_label(f"Radiance @ {target_nm:.1f} nm (Rayleighs/nm)")

    geo_ax.set_title(format_pair_title(pair))
    fig.tight_layout()  # type: ignore[attr-defined]
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", pad_inches=0.05)  # type: ignore[attr-defined]
    plt.close(fig)


def process_archive(
    tar_path: Path,
    output_root: Path,
    target_nm: float,
    max_pair_minutes: float,
    quality_mode: str,
    figsize: tuple[float, float],
    point_size: float,
    extent: tuple[float, float, float, float],
    vmin: float,
    vmax: float,
    dpi: int,
    limit: int | None,
    verbose: bool,
) -> tuple[int, int]:
    """处理单个归档文件，并返回写出的图像数与未配对文件数。"""
    entries = discover_entries(tar_path)
    if not entries:
        print(f"[WARN] {tar_path.name}: no GOLD NI1 CHA/CHB files found.")
        return 0, 0

    pairs, unmatched = match_pairs(entries, max_pair_minutes)
    if limit is not None:
        pairs = pairs[:limit]
    tar_output_dir = output_root / tar_path.stem
    tar_output_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[INFO] {tar_path.name}: found {len(entries)} files, "
        f"matched {len(pairs)} pairs, unmatched {len(unmatched)}."
    )

    written = 0
    apex = Apex(date=2020.0)
    with tarfile.open(tar_path) as archive:
        for pair in pairs:
            output_name = format_output_name(pair, target_nm)
            output_path = tar_output_dir / output_name
            plot_pair(
                pair=pair,
                archive=archive,
                output_path=output_path,
                target_nm=target_nm,
                quality_mode=quality_mode,
                figsize=figsize,
                point_size=point_size,
                extent=extent,
                vmin=vmin,
                vmax=vmax,
                dpi=dpi,
                apex=apex,
            )
            written += 1
            if verbose:
                print(f"[OK] {output_path}")

    for entry in unmatched[:10]:
        print(
            "[WARN] Unmatched file: "
            f"{entry.hemisphere} {entry.obs_time:%Y-%m-%d %H:%M} {Path(entry.member_name).name}"
        )
    if len(unmatched) > 10:
        print(f"[WARN] ... {len(unmatched) - 10} more unmatched files not shown.")

    return written, len(unmatched)


def main() -> int:
    """脚本主入口。"""
    args = parse_args()
    if args.vmax <= args.vmin:
        raise ValueError("--vmax must be greater than --vmin.")
    if args.point_size <= 0:
        raise ValueError("--point-size must be greater than 0.")
    west, east, south, north = args.extent
    if west >= east:
        raise ValueError("--extent requires WEST < EAST.")
    if south >= north:
        raise ValueError("--extent requires SOUTH < NORTH.")

    tar_paths = iter_tar_paths(args.inputs)
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    total_written = 0
    total_unmatched = 0
    for tar_path in tar_paths:
        written, unmatched = process_archive(
            tar_path=tar_path,
            output_root=output_root,
            target_nm=args.target_nm,
            max_pair_minutes=args.max_pair_minutes,
            quality_mode=args.quality_mode,
            figsize=tuple(args.figsize),
            point_size=args.point_size,
            extent=tuple(args.extent),
            vmin=args.vmin,
            vmax=args.vmax,
            dpi=args.dpi,
            limit=args.limit,
            verbose=args.verbose,
        )
        total_written += written
        total_unmatched += unmatched

    print(
        "[DONE] "
        f"Wrote {total_written} PNG files to {output_root}. "
        f"Total unmatched files: {total_unmatched}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
