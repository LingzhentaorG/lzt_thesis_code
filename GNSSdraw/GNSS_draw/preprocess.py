"""GNSS 切片预处理模块。

该模块把 `reader.py` 读出的原始切片进一步转换为适合绘图的结构：

- 规范化经度范围
- 解析绘图区域
- 裁剪经纬度网格
- 屏蔽无效值
- 格式化标题和文件名中的时间字符串
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import CustomRegion, REGION_PRESETS
from .reader import SliceData


@dataclass(frozen=True)
class ProcessedSlice:
    """经过预处理后可直接送入绘图模块的切片对象。"""

    category: str
    source_path: str
    year: str
    doy: str
    timestamp: pd.Timestamp
    time_index: int
    lat: np.ndarray
    lon: np.ndarray
    values: np.ma.MaskedArray
    units: str | None
    region_name: str
    extent: tuple[float, float, float, float]


def prepare_slice(
    slice_data: SliceData,
    *,
    region_name: str,
    custom_region: CustomRegion | None,
    lon_mode: str,
) -> ProcessedSlice:
    """把原始切片转换为可绘图的 `ProcessedSlice`。"""
    lat = np.asarray(slice_data.lat, dtype=float)
    lon = np.asarray(slice_data.lon, dtype=float)
    values = np.asarray(slice_data.values, dtype=float)

    if lat.ndim != 1 or lon.ndim != 1 or values.ndim != 2:
        raise ValueError("Expected 1D latitude, 1D longitude, and 2D values for preprocessing.")

    # 先统一经度体系，再根据目标区域裁剪。
    lon, values, resolved_lon_mode = normalize_longitudes(lon, values, lon_mode)
    extent = resolve_region_extent(region_name, custom_region, resolved_lon_mode)
    lat, lon, values = crop_to_extent(lat, lon, values, extent)

    # 绘图阶段直接依赖掩码数组，因此这里把 NaN 统一转换成 masked 值。
    masked_values = np.ma.masked_invalid(values)

    if masked_values.count() == 0:
        raise ValueError(
            f"Selected data slice is empty after masking and cropping for region '{region_name}'."
        )

    return ProcessedSlice(
        category=slice_data.category,
        source_path=str(slice_data.source_path),
        year=slice_data.year,
        doy=slice_data.doy,
        timestamp=slice_data.timestamp,
        time_index=slice_data.time_index,
        lat=lat,
        lon=lon,
        values=masked_values,
        units=slice_data.units,
        region_name=region_name,
        extent=extent,
    )


def normalize_longitudes(
    lon: np.ndarray, values: np.ndarray, lon_mode: str
) -> tuple[np.ndarray, np.ndarray, str]:
    """把经度转换到目标体系，并同步重排二维值数组列顺序。"""
    resolved_mode = _resolve_target_lon_mode(lon, lon_mode)

    if resolved_mode == "-180_180":
        converted = ((lon + 180.0) % 360.0) - 180.0
        converted[np.isclose(converted, -180.0) & (lon >= 180.0)] = 180.0
    else:
        converted = lon % 360.0

    # 转换后需要重新排序，否则 pcolormesh 会按照原列顺序连接出错。
    order = np.argsort(converted)
    converted_sorted = converted[order]
    values_sorted = values[:, order]
    return converted_sorted, values_sorted, resolved_mode


def resolve_region_extent(
    region_name: str,
    custom_region: CustomRegion | None,
    lon_mode: str,
) -> tuple[float, float, float, float]:
    """把区域名称解析成具体的 `(lon_min, lon_max, lat_min, lat_max)`。"""
    if region_name == "custom":
        if custom_region is None:
            raise ValueError("plot.region is 'custom' but [region.custom] is not configured.")
        extent = (
            custom_region.lon_min,
            custom_region.lon_max,
            custom_region.lat_min,
            custom_region.lat_max,
        )
    else:
        extent = REGION_PRESETS[region_name]

    lon_min, lon_max, lat_min, lat_max = extent
    if lon_mode == "0_360":
        # 当目标经度体系是 0~360 时，需要同步变换区域经度范围。
        if lon_min == -180.0 and lon_max == 180.0:
            lon_min, lon_max = 0.0, 360.0
        else:
            lon_min = lon_min % 360.0
            lon_max = lon_max % 360.0
            if lon_min > lon_max:
                raise ValueError(
                    f"Region '{region_name}' wraps the dateline after longitude conversion, "
                    "which is not supported in this version."
                )

    return (float(lon_min), float(lon_max), float(lat_min), float(lat_max))


def crop_to_extent(
    lat: np.ndarray,
    lon: np.ndarray,
    values: np.ndarray,
    extent: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """按区域范围裁剪一维经纬度和二维数值网格。"""
    lon_min, lon_max, lat_min, lat_max = extent

    lat_mask = (lat >= lat_min) & (lat <= lat_max)
    lon_mask = (lon >= lon_min) & (lon <= lon_max)

    if not np.any(lat_mask):
        raise ValueError("Latitude crop produced an empty selection.")
    if not np.any(lon_mask):
        raise ValueError("Longitude crop produced an empty selection.")

    cropped_lat = lat[lat_mask]
    cropped_lon = lon[lon_mask]
    cropped_values = values[np.ix_(lat_mask, lon_mask)]
    return cropped_lat, cropped_lon, cropped_values


def format_title_timestamp(timestamp: pd.Timestamp) -> str:
    """把时间格式化为图题中使用的 `YYYY-MM-DD HH:MM`。"""
    return timestamp.strftime("%Y-%m-%d %H:%M")


def format_filename_timestamp(timestamp: pd.Timestamp) -> str:
    """把时间格式化为文件名中使用的 `YYYYMMDDTHHMMZ`。"""
    return timestamp.strftime("%Y%m%dT%H%MZ")


def _resolve_target_lon_mode(lon: np.ndarray, lon_mode: str) -> str:
    """在 `auto` 模式下根据原始经度范围自动推断目标体系。"""
    if lon_mode == "auto":
        return "0_360" if np.nanmax(lon) > 180.0 else "-180_180"
    return lon_mode
