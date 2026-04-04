#!/usr/bin/env python
"""生成 GOLD 与高 ROTI 叠加的事件六宫格图。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import cartopy.crs as ccrs
import matplotlib

matplotlib.use("Agg")

from matplotlib import font_manager
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from gold_ni1_plot_stitched_v2 import (
    ArchiveEntry,
    add_magnetic_equator,
    add_map_background,
    discover_entries,
    plot_swath,
    read_geo_grid,
)


GOLD_TARGET_NM = 135.6
GOLD_QUALITY_MODE = "all"
GOLD_VMIN = 0.0
GOLD_VMAX = 300.0
ROTI_VMIN = 0.0
ROTI_VMAX = 1.0
POINT_SIZE = 9.0
GAP_FACTOR = 6.0
OVERLAY_POINT_SIZE = 12.0
EXTENT = (-105.0, 15.0, -60.0, 60.0)
DEFAULT_DPI = 180


@dataclass(frozen=True)
class EventDefinition:
    """单个事件六宫格的输入定义。"""

    name: str
    tar_path: Path
    target_times: tuple[datetime, datetime]
    output_name: str


@dataclass(frozen=True)
class MatchedGoldPair:
    """目标时刻匹配到的 GOLD 双半球观测对。"""

    cha: ArchiveEntry
    chb: ArchiveEntry
    target_time: datetime

    @property
    def midpoint(self) -> datetime:
        return self.cha.obs_time + (self.chb.obs_time - self.cha.obs_time) / 2


@dataclass(frozen=True)
class GoldPanelData:
    """单列 GOLD 绘图所需的数据。"""

    pair: MatchedGoldPair
    swaths: tuple[tuple[np.ndarray, np.ndarray, np.ma.MaskedArray], ...]


@dataclass(frozen=True)
class RotiPanelData:
    """单列 ROTI 绘图所需的数据。"""

    target_time: datetime
    matched_time: pd.Timestamp
    source_path: Path
    lat: np.ndarray
    lon: np.ndarray
    values: np.ma.MaskedArray


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Draw 3x2 GOLD / ROTI / GOLD+high ROTI figures for two fixed events."
    )
    parser.add_argument(
        "--roti-threshold",
        type=float,
        default=1.0,
        help="Threshold used to mark high ROTI points on the overlay row. Default: 1.0",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=script_dir / "six_panel_output",
        help="Directory used to store the generated PNG files.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"Output DPI. Default: {DEFAULT_DPI}",
    )
    return parser.parse_args()


def resolve_font_family(requested_font_family: str) -> str:
    """根据本机已安装字体选择最接近的衬线字体。"""
    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in (
        requested_font_family,
        "Times New Roman",
        "Times",
        "Nimbus Roman",
        "DejaVu Serif",
    ):
        if candidate in available_fonts:
            return candidate
    return "serif"


def build_event_definitions(repo_root: Path) -> tuple[EventDefinition, ...]:
    """返回固定的两组事件定义。"""
    gold_root = repo_root / "GOLDdraw"
    return (
        EventDefinition(
            name="2024-10-11 Event",
            tar_path=gold_root / "NI2024101020241010.tar",
            target_times=(
                datetime(2024, 10, 11, 0, 10),
                datetime(2024, 10, 11, 0, 22),
            ),
            output_name="gold_roti_event_20241011.png",
        ),
        EventDefinition(
            name="2024-12-31 Event",
            tar_path=gold_root / "NI2024123120241231.tar",
            target_times=(
                datetime(2024, 12, 31, 23, 23),
                datetime(2024, 12, 31, 23, 53),
            ),
            output_name="gold_roti_event_20241231.png",
        ),
    )


def match_gold_pair_by_time(
    entries: list[ArchiveEntry],
    target_time: datetime,
    *,
    max_target_delta_minutes: float = 5.0,
    max_pair_delta_minutes: float = 5.0,
) -> MatchedGoldPair:
    """为目标时刻寻找最近且物理上合理的 CHA/CHB 配对。"""
    cha_entries = [entry for entry in entries if entry.hemisphere == "CHA"]
    chb_entries = [entry for entry in entries if entry.hemisphere == "CHB"]
    if not cha_entries or not chb_entries:
        raise RuntimeError("Could not find both CHA and CHB entries in the GOLD archive.")

    best_cha = min(cha_entries, key=lambda item: abs(item.obs_time - target_time))
    best_chb = min(chb_entries, key=lambda item: abs(item.obs_time - target_time))

    cha_delta = abs(best_cha.obs_time - target_time)
    chb_delta = abs(best_chb.obs_time - target_time)
    pair_delta = abs(best_chb.obs_time - best_cha.obs_time)

    if cha_delta > timedelta(minutes=max_target_delta_minutes):
        raise RuntimeError(
            f"No CHA observation within {max_target_delta_minutes:.1f} minutes of {format_ut(target_time)}."
        )
    if chb_delta > timedelta(minutes=max_target_delta_minutes):
        raise RuntimeError(
            f"No CHB observation within {max_target_delta_minutes:.1f} minutes of {format_ut(target_time)}."
        )
    if pair_delta > timedelta(minutes=max_pair_delta_minutes):
        raise RuntimeError(
            f"Nearest CHA/CHB observations near {format_ut(target_time)} are too far apart."
        )

    return MatchedGoldPair(cha=best_cha, chb=best_chb, target_time=target_time)


def load_gold_panel(pair: MatchedGoldPair) -> GoldPanelData:
    """读取一个目标时刻所需的 GOLD 条带。"""
    swaths: list[tuple[np.ndarray, np.ndarray, np.ma.MaskedArray]] = []
    for entry in (pair.cha, pair.chb):
        lon, lat, radiance = read_geo_grid(entry, GOLD_TARGET_NM, GOLD_QUALITY_MODE)
        if radiance.count() > 0:
            swaths.append((lon, lat, radiance))

    if not swaths:
        raise RuntimeError(f"No drawable GOLD pixels remained for {format_ut(pair.target_time)}.")

    return GoldPanelData(pair=pair, swaths=tuple(swaths))


def build_roti_candidate_paths(roti_root: Path, target_time: datetime) -> tuple[Path, ...]:
    """返回目标时刻相邻 3 个小时的候选 nc 文件。"""
    candidates: list[Path] = []
    for hour_offset in (-1, 0, 1):
        candidate_time = target_time + timedelta(hours=hour_offset)
        doy = candidate_time.timetuple().tm_yday
        candidate = (
            roti_root
            / f"{candidate_time.year:04d}"
            / f"{doy:03d}"
            / candidate_time.strftime("%Y%m%d%H_roti.nc")
        )
        candidates.append(candidate)
    return tuple(dict.fromkeys(candidates))


def normalize_longitudes(lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """将经度统一到 -180~180，并返回重排索引。"""
    normalized = ((lon + 180.0) % 360.0) - 180.0
    normalized[np.isclose(normalized, -180.0) & (lon >= 180.0)] = 180.0
    order = np.argsort(normalized)
    return normalized[order], order


def crop_roti_grid(
    lat: np.ndarray,
    lon: np.ndarray,
    values: np.ndarray,
    extent: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ma.MaskedArray]:
    """按目标图幅裁剪 ROTI 二维网格。"""
    west, east, south, north = extent
    lon_normalized, order = normalize_longitudes(lon)
    values = values[:, order]

    lat_mask = (lat >= south) & (lat <= north)
    lon_mask = (lon_normalized >= west) & (lon_normalized <= east)
    if not np.any(lat_mask):
        raise RuntimeError("ROTI latitude crop produced an empty selection.")
    if not np.any(lon_mask):
        raise RuntimeError("ROTI longitude crop produced an empty selection.")

    cropped_lat = lat[lat_mask]
    cropped_lon = lon_normalized[lon_mask]
    cropped_values = values[np.ix_(lat_mask, lon_mask)]
    masked_values = np.ma.masked_invalid(cropped_values)
    if masked_values.count() == 0:
        raise RuntimeError("No finite ROTI values remained after cropping.")
    return cropped_lat, cropped_lon, masked_values


def load_nearest_roti_panel(
    roti_root: Path,
    target_time: datetime,
    *,
    extent: tuple[float, float, float, float],
    max_delta_minutes: float = 5.0,
) -> RotiPanelData:
    """在 5 分钟窗口内读取与目标时刻最近的 ROTI 切片。"""
    target_timestamp = pd.Timestamp(target_time)
    best_match: RotiPanelData | None = None
    best_delta: pd.Timedelta | None = None

    for candidate_path in build_roti_candidate_paths(roti_root, target_time):
        if not candidate_path.exists():
            continue

        with xr.open_dataset(candidate_path) as dataset:
            times = pd.to_datetime(dataset["time"].values)
            if len(times) == 0:
                continue

            deltas = pd.to_timedelta(np.abs(times - target_timestamp))
            nearest_index = int(np.argmin(deltas))
            nearest_time = pd.Timestamp(times[nearest_index])
            delta = deltas[nearest_index]

            if best_delta is not None and delta > best_delta:
                continue
            if best_delta is not None and delta == best_delta and nearest_time >= best_match.matched_time:
                continue

            lat = np.asarray(dataset["lat"].values, dtype=float)
            lon = np.asarray(dataset["lon"].values, dtype=float)
            values = np.asarray(
                dataset["roti"].isel(time=nearest_index).transpose("latitude", "longitude").values,
                dtype=float,
            )
            cropped_lat, cropped_lon, cropped_values = crop_roti_grid(lat, lon, values, extent)
            best_match = RotiPanelData(
                target_time=target_time,
                matched_time=nearest_time,
                source_path=candidate_path,
                lat=cropped_lat,
                lon=cropped_lon,
                values=cropped_values,
            )
            best_delta = delta

    if best_match is None or best_delta is None:
        raise RuntimeError(f"Could not find any ROTI nc file around {format_ut(target_time)}.")
    if best_delta > pd.Timedelta(minutes=max_delta_minutes):
        raise RuntimeError(
            f"No ROTI slice within {max_delta_minutes:.1f} minutes of {format_ut(target_time)}."
        )
    return best_match


def format_ut(value: datetime | pd.Timestamp) -> str:
    """格式化为统一的 UTC 字符串。"""
    timestamp = pd.Timestamp(value)
    return timestamp.strftime("%Y-%m-%d %H:%M UT")


def format_hm(value: datetime | pd.Timestamp) -> str:
    """格式化为 HH:MM。"""
    timestamp = pd.Timestamp(value)
    return timestamp.strftime("%H:%M")


def build_axis_title_gold(panel: GoldPanelData) -> str:
    """生成 GOLD 子图标题。"""
    return (
        "GOLD\n"
        f"Target {format_ut(panel.pair.target_time)} | "
        f"CHA {format_hm(panel.pair.cha.obs_time)} + CHB {format_hm(panel.pair.chb.obs_time)}"
    )


def build_axis_title_roti(panel: RotiPanelData) -> str:
    """生成 ROTI 子图标题。"""
    return (
        "ROTI\n"
        f"Target {format_ut(panel.target_time)} | Nearest {format_hm(panel.matched_time)}"
    )


def build_axis_title_overlay(gold_panel: GoldPanelData, roti_panel: RotiPanelData, threshold: float) -> str:
    """生成叠加子图标题。"""
    return (
        f"GOLD + ROTI >= {threshold:.1f}\n"
        f"GOLD CHA {format_hm(gold_panel.pair.cha.obs_time)} + CHB {format_hm(gold_panel.pair.chb.obs_time)} | "
        f"ROTI {format_hm(roti_panel.matched_time)}"
    )


def add_row_label(axis: plt.Axes, label: str) -> None:
    """在左列外侧增加行标签。"""
    axis.text(
        -0.13,
        0.5,
        label,
        rotation=90,
        transform=axis.transAxes,
        va="center",
        ha="center",
        fontsize=13,
        fontweight="bold",
    )


def configure_axis(axis: plt.Axes, timestamp: datetime | pd.Timestamp) -> None:
    """为每个子图设置地图底图与图幅。"""
    add_map_background(axis)
    axis.set_extent(EXTENT, crs=ccrs.PlateCarree())
    add_magnetic_equator(axis, EXTENT, pd.Timestamp(timestamp).to_pydatetime())


def draw_gold_panel(axis: plt.Axes, panel: GoldPanelData) -> object:
    """绘制 GOLD 行。"""
    mesh = None
    for lon, lat, radiance in panel.swaths:
        mesh = plot_swath(
            axis,
            lon,
            lat,
            radiance,
            vmin=GOLD_VMIN,
            vmax=GOLD_VMAX,
            point_size=POINT_SIZE,
            gap_factor=GAP_FACTOR,
        )
    if mesh is None:
        raise RuntimeError(f"Failed to draw GOLD panel for {format_ut(panel.pair.target_time)}.")
    return mesh


def draw_roti_panel(axis: plt.Axes, panel: RotiPanelData) -> object:
    """绘制 ROTI 行。"""
    return axis.pcolormesh(
        panel.lon,
        panel.lat,
        panel.values,
        cmap="viridis",
        vmin=ROTI_VMIN,
        vmax=ROTI_VMAX,
        shading="auto",
        transform=ccrs.PlateCarree(),
        rasterized=True,
        zorder=3,
    )


def draw_overlay_panel(axis: plt.Axes, gold_panel: GoldPanelData, roti_panel: RotiPanelData, threshold: float) -> tuple[object, int]:
    """绘制底部叠加行。"""
    gold_mesh = draw_gold_panel(axis, gold_panel)
    lon_grid, lat_grid = np.meshgrid(roti_panel.lon, roti_panel.lat)
    mask = ~np.ma.getmaskarray(roti_panel.values) & (np.asarray(roti_panel.values) >= threshold)
    high_count = int(np.count_nonzero(mask))

    if high_count > 0:
        axis.scatter(
            lon_grid[mask],
            lat_grid[mask],
            s=OVERLAY_POINT_SIZE,
            c="red",
            linewidths=0,
            edgecolors="none",
            alpha=0.85,
            transform=ccrs.PlateCarree(),
            zorder=6,
            rasterized=True,
        )

    legend_handle = Line2D(
        [0],
        [0],
        marker="o",
        color="none",
        markerfacecolor="red",
        markeredgecolor="none",
        markersize=6,
        label=f"ROTI >= {threshold:.1f} (n={high_count})",
    )
    axis.legend(handles=[legend_handle], loc="upper right", fontsize=8, frameon=True)
    return gold_mesh, high_count


def build_event_figure(
    event: EventDefinition,
    roti_root: Path,
    output_dir: Path,
    *,
    roti_threshold: float,
    dpi: int,
    requested_font_family: str = "Times New Roman",
) -> Path:
    """为单个事件生成一张 3x2 六宫格图。"""
    entries = discover_entries(event.tar_path)
    if not entries:
        raise RuntimeError(f"No readable GOLD entries found in {event.tar_path}.")

    gold_panels = [load_gold_panel(match_gold_pair_by_time(entries, target_time)) for target_time in event.target_times]
    roti_panels = [load_nearest_roti_panel(roti_root, target_time, extent=EXTENT) for target_time in event.target_times]

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / event.output_name
    font_family = resolve_font_family(requested_font_family)

    with plt.rc_context({"font.family": font_family}):
        figure, axes = plt.subplots(
            3,
            2,
            figsize=(15.0, 16.5),
            subplot_kw={"projection": ccrs.PlateCarree()},
            constrained_layout=True,
        )

        row_labels = ("GOLD", "ROTI", "GOLD + High ROTI")
        for row_index, label in enumerate(row_labels):
            add_row_label(axes[row_index, 0], label)

        gold_row_mesh = None
        roti_row_mesh = None
        overlay_row_mesh = None

        for column_index, (gold_panel, roti_panel) in enumerate(zip(gold_panels, roti_panels, strict=True)):
            top_axis = axes[0, column_index]
            middle_axis = axes[1, column_index]
            bottom_axis = axes[2, column_index]

            configure_axis(top_axis, gold_panel.pair.target_time)
            configure_axis(middle_axis, roti_panel.target_time)
            configure_axis(bottom_axis, gold_panel.pair.target_time)

            gold_row_mesh = draw_gold_panel(top_axis, gold_panel)
            roti_row_mesh = draw_roti_panel(middle_axis, roti_panel)
            overlay_row_mesh, high_count = draw_overlay_panel(bottom_axis, gold_panel, roti_panel, roti_threshold)

            top_axis.set_title(build_axis_title_gold(gold_panel), fontsize=10)
            middle_axis.set_title(build_axis_title_roti(roti_panel), fontsize=10)
            bottom_axis.set_title(build_axis_title_overlay(gold_panel, roti_panel, roti_threshold), fontsize=10)

            print(
                "[INFO] "
                f"{format_ut(gold_panel.pair.target_time)} -> "
                f"GOLD CHA {format_hm(gold_panel.pair.cha.obs_time)} / CHB {format_hm(gold_panel.pair.chb.obs_time)}, "
                f"ROTI {format_hm(roti_panel.matched_time)}, "
                f"high-ROTI points: {high_count}"
            )

        if gold_row_mesh is not None:
            colorbar = figure.colorbar(gold_row_mesh, ax=axes[0, :].tolist(), shrink=0.92, pad=0.02, aspect=35)
            colorbar.set_label(f"GOLD Radiance @ {GOLD_TARGET_NM:.1f} nm (Rayleighs/nm)")
        if roti_row_mesh is not None:
            colorbar = figure.colorbar(roti_row_mesh, ax=axes[1, :].tolist(), shrink=0.92, pad=0.02, aspect=35)
            colorbar.set_label("ROTI")
        if overlay_row_mesh is not None:
            colorbar = figure.colorbar(
                overlay_row_mesh,
                ax=axes[2, :].tolist(),
                shrink=0.92,
                pad=0.02,
                aspect=35,
            )
            colorbar.set_label(f"GOLD Radiance @ {GOLD_TARGET_NM:.1f} nm (Rayleighs/nm)")

        figure.suptitle(
            f"{event.name}: GOLD, ROTI, and GOLD + High ROTI",
            fontsize=16,
            fontweight="bold",
        )
        figure.savefig(output_path, dpi=dpi, bbox_inches="tight", pad_inches=0.05)
        plt.close(figure)

    print(f"[OK] Saved event figure to {output_path}")
    return output_path


def main() -> int:
    """脚本主入口。"""
    args = parse_args()
    if args.roti_threshold < 0:
        raise ValueError("--roti-threshold must be non-negative.")
    if args.dpi <= 0:
        raise ValueError("--dpi must be greater than 0.")

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    roti_root = repo_root / "GNSSdraw" / "Data_download" / "ROTI_data"
    if not roti_root.exists():
        raise FileNotFoundError(f"ROTI data root does not exist: {roti_root}")

    output_dir = args.output_dir.expanduser().resolve()
    outputs = []
    for event in build_event_definitions(repo_root):
        outputs.append(
            build_event_figure(
                event,
                roti_root,
                output_dir,
                roti_threshold=args.roti_threshold,
                dpi=args.dpi,
            )
        )

    print(f"[DONE] Wrote {len(outputs)} figures to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
