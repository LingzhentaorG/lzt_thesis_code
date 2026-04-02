"""GNSS 地图绘制模块。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

# 仓库中的绘图任务主要跑在批处理环境，因此强制使用无界面的 Agg 后端。
matplotlib.use("Agg")

import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib import font_manager
import matplotlib.pyplot as plt
import numpy as np

from .config import MagneticEquatorConfig, StyleConfig
from .preprocess import ProcessedSlice, format_title_timestamp


def plot_map(
    processed: ProcessedSlice,
    *,
    style: StyleConfig,
    output_path: Path,
    dpi: int,
    figure_size: tuple[float, float],
    requested_font_family: str,
    magnetic_equator: MagneticEquatorConfig | None = None,
) -> None:
    """把单个预处理切片绘制成地图并保存到磁盘。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_family = resolve_font_family(requested_font_family)

    with plt.rc_context({"font.family": font_family}):
        figure = plt.figure(figsize=figure_size)
        axis = plt.axes(projection=ccrs.PlateCarree())
        axis.set_extent(processed.extent, crs=ccrs.PlateCarree())

        mesh = axis.pcolormesh(
            processed.lon,
            processed.lat,
            processed.values,
            transform=ccrs.PlateCarree(),
            shading="auto",
            cmap=style.cmap,
            vmin=style.vmin,
            vmax=style.vmax,
        )

        axis.coastlines(resolution="110m", linewidth=0.8)
        axis.add_feature(cfeature.BORDERS.with_scale("110m"), linewidth=0.4)

        if magnetic_equator is not None and magnetic_equator.enabled:
            draw_magnetic_equator(
                axis,
                processed.extent,
                processed.timestamp,
                color=magnetic_equator.color,
                linewidth=magnetic_equator.linewidth,
            )

        gridlines = axis.gridlines(
            draw_labels=True,
            linewidth=0.4,
            color="gray",
            alpha=0.6,
            linestyle="--",
            x_inline=False,
            y_inline=False,
        )
        gridlines.top_labels = True
        gridlines.bottom_labels = False
        gridlines.right_labels = False

        title_text = f"{processed.category} Map {format_title_timestamp(processed.timestamp)} UTC"
        # 当前项目的图题放在图框下方中央，方便和地图主体分离。
        axis.text(
            0.5,
            -0.02,
            title_text,
            transform=axis.transAxes,
            fontsize=14,
            ha="center",
            va="top",
        )

        colorbar = figure.colorbar(mesh, ax=axis, shrink=1.0, aspect=30, pad=0.03)
        colorbar.set_label(_build_colorbar_label(processed))

        figure.tight_layout()
        figure.savefig(output_path, dpi=dpi, bbox_inches="tight")
        plt.close(figure)


def resolve_font_family(requested_font_family: str) -> str:
    """根据本机已安装字体，为绘图选择一个最合适的衬线字体。"""
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


def _build_colorbar_label(processed: ProcessedSlice) -> str:
    """生成色标标题，若存在单位则一并展示。"""
    if processed.units:
        return f"{processed.category} ({processed.units})"
    return processed.category


def draw_magnetic_equator(
    axis,
    extent: tuple[float, float, float, float],
    timestamp,
    color: str = "red",
    linewidth: float = 1.5,
) -> None:
    """在地图上绘制磁赤道线。

    实现逻辑：

    1. 在给定经度范围上逐列搜索
    2. 在当前图幅纬度范围内寻找磁纬由正变负或由负变正的位置
    3. 一旦发现过零区间，再用二分法细化真实地理纬度
    """
    try:
        from apexpy import Apex
    except ImportError:
        import logging

        logging.warning("apexpy is not installed. Magnetic equator will not be drawn.")
        return

    lon_min, lon_max, lat_min, lat_max = extent

    lon_resolution = 721
    lons = np.linspace(-180, 180, lon_resolution)

    try:
        apex = Apex(date=timestamp)
    except Exception:
        year = timestamp.year if hasattr(timestamp, "year") else 2024
        apex = Apex(date=year)

    mag_lats = []
    mag_lons = []

    for lon in lons:
        search_lats = np.linspace(lat_min, lat_max, 200)
        prev_mlat = None
        prev_lat = None

        for lat in search_lats:
            try:
                mlat, _ = apex.convert(lat, lon, "geo", "apex", height=300)
                mlat = float(mlat)

                if prev_mlat is not None and prev_mlat * mlat <= 0:
                    eq_lat = _find_equator_latitude(
                        apex,
                        prev_lat,
                        lat,
                        prev_mlat,
                        mlat,
                        lon,
                    )
                    if eq_lat is not None:
                        mag_lats.append(eq_lat)
                        mag_lons.append(lon)
                    break
                prev_mlat = mlat
                prev_lat = lat
            except Exception:
                continue

    if mag_lons and mag_lats:
        mag_lons = np.array(mag_lons)
        mag_lats = np.array(mag_lats)

        sort_idx = np.argsort(mag_lons)
        mag_lons = mag_lons[sort_idx]
        mag_lats = mag_lats[sort_idx]

        mask = (mag_lons >= lon_min) & (mag_lons <= lon_max)
        mag_lons = mag_lons[mask]
        mag_lats = mag_lats[mask]

        if len(mag_lons) > 1:
            # 若环境中没有 SciPy，则直接退回普通折线绘制。
            try:
                from scipy.interpolate import splprep, splev

                tck, _ = splprep([mag_lons, mag_lats], s=0, per=False)
                u_new = np.linspace(0, 1, 1000)
                smooth_lons, smooth_lats = splev(u_new, tck)

                axis.plot(
                    smooth_lons,
                    smooth_lats,
                    color=color,
                    linewidth=linewidth,
                    linestyle="--",
                    transform=ccrs.PlateCarree(),
                    label="Magnetic Equator",
                )
            except Exception:
                axis.plot(
                    mag_lons,
                    mag_lats,
                    color=color,
                    linewidth=linewidth,
                    linestyle="--",
                    transform=ccrs.PlateCarree(),
                    label="Magnetic Equator",
                )


def _find_equator_latitude(
    apex,
    lat_low: float,
    lat_high: float,
    mlat_low: float,
    mlat_high: float,
    lon: float,
    tolerance: float = 0.001,
    max_iter: int = 20,
) -> float | None:
    """在磁纬过零的区间内，用二分法细化磁赤道位置。"""
    for _ in range(max_iter):
        lat_mid = (lat_low + lat_high) / 2.0

        try:
            mlat_mid, _ = apex.convert(lat_mid, lon, "geo", "apex", height=300)
            mlat_mid = float(mlat_mid)
        except Exception:
            return None

        if abs(mlat_mid) < tolerance:
            return lat_mid

        if mlat_low * mlat_mid <= 0:
            lat_high = lat_mid
            mlat_high = mlat_mid
        else:
            lat_low = lat_mid
            mlat_low = mlat_mid

    return lat_mid
