#!/usr/bin/env python
"""Plot GOLD NI1 135.6 nm geolocated maps from CHA/CHB tar archives."""

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
    tar_path: Path
    member_name: str
    hemisphere: str
    obs_time: datetime


@dataclass(frozen=True)
class PairMatch:
    cha: ArchiveEntry
    chb: ArchiveEntry
    delta: timedelta

    @property
    def midpoint(self) -> datetime:
        return self.cha.obs_time + (self.chb.obs_time - self.cha.obs_time) / 2


def parse_args() -> argparse.Namespace:
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
        help="Fallback scatter point size in points^2 when a swath is not 2D.",
    )
    parser.add_argument(
        "--gap-factor",
        type=float,
        default=6.0,
        help=(
            "Mask pcolormesh cells whose neighbor spacing is more than this many times "
            "the swath's median spacing. Higher values are less aggressive."
        ),
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
    parser.add_argument(
        "--merge-mode",
        choices=("native", "grid"),
        default="native",
        help=(
            "'native' plots each swath with pcolormesh; "
            "'grid' resamples both swaths onto a regular latitude/longitude grid."
        ),
    )
    parser.add_argument(
        "--grid-step",
        type=float,
        default=0.25,
        help="Grid spacing in degrees when --merge-mode grid is used. Default: 0.25",
    )
    return parser.parse_args()


def iter_tar_paths(raw_inputs: Iterable[str]) -> list[Path]:
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
    extracted = archive.extractfile(member_name)
    if extracted is None:
        raise FileNotFoundError(f"Failed to read {member_name} from archive.")
    return extracted.read()


def read_geo_grid(
    archive: tarfile.TarFile,
    member_name: str,
    target_nm: float,
    quality_mode: str,
) -> tuple[np.ndarray, np.ndarray, np.ma.MaskedArray]:
    """Read one swath and keep its original 2D topology intact."""
    dataset_bytes = read_dataset_bytes(archive, member_name)
    with Dataset("inmemory.nc", memory=dataset_bytes) as dataset:
        latitude = np.ma.filled(dataset.variables["REFERENCE_POINT_LAT"][:], np.nan).astype(np.float64)
        longitude = np.ma.filled(dataset.variables["REFERENCE_POINT_LON"][:], np.nan).astype(np.float64)
        wavelength = np.ma.filled(dataset.variables["WAVELENGTH"][:], np.nan).astype(np.float64)
        radiance = np.ma.filled(dataset.variables["RADIANCE"][:], np.nan).astype(np.float64)
        quality_flag = np.ma.filled(dataset.variables["QUALITY_FLAG"][:], 0).astype(np.uint32)

    nearest_index = np.abs(wavelength - target_nm).argmin(axis=2)
    radiance_1356 = np.take_along_axis(radiance, nearest_index[..., None], axis=2)[..., 0]

    valid = np.isfinite(latitude) & np.isfinite(longitude) & np.isfinite(radiance_1356)
    valid &= (latitude >= -90.0) & (latitude <= 90.0)
    valid &= (longitude >= -180.0) & (longitude <= 180.0)
    if quality_mode == "good":
        valid &= quality_flag == 0

    z = np.ma.array(radiance_1356, mask=~valid)
    lon = longitude.astype(np.float64, copy=False)
    lat = latitude.astype(np.float64, copy=False)
    lon[~valid] = np.nan
    lat[~valid] = np.nan
    return lon, lat, z


def estimate_median_spacing(lon: np.ndarray, lat: np.ndarray) -> float:
    finite = np.isfinite(lon) & np.isfinite(lat)
    dx = np.hypot(np.diff(lon, axis=1), np.diff(lat, axis=1))
    dy = np.hypot(np.diff(lon, axis=0), np.diff(lat, axis=0))

    valid_dx = finite[:, 1:] & finite[:, :-1] & np.isfinite(dx) & (dx > 0)
    valid_dy = finite[1:, :] & finite[:-1, :] & np.isfinite(dy) & (dy > 0)

    spacing_samples = []
    if np.any(valid_dx):
        spacing_samples.append(dx[valid_dx])
    if np.any(valid_dy):
        spacing_samples.append(dy[valid_dy])
    if not spacing_samples:
        return np.inf
    return float(np.nanmedian(np.concatenate(spacing_samples)))


def center_to_edges(center: np.ndarray) -> np.ndarray:
    """Approximate cell corner coordinates from a curvilinear center grid.

    Any edge/corner that depends on one or more invalid centers is kept as NaN so
    the corresponding pcolormesh cell can be masked out later.
    """
    m, n = center.shape
    edge = np.full((m + 1, n + 1), np.nan, dtype=np.float64)
    finite = np.isfinite(center)

    interior = 0.25 * (
        center[:-1, :-1] + center[1:, :-1] + center[:-1, 1:] + center[1:, 1:]
    )
    interior_ok = finite[:-1, :-1] & finite[1:, :-1] & finite[:-1, 1:] & finite[1:, 1:]
    edge[1:-1, 1:-1][interior_ok] = interior[interior_ok]

    top_ok = finite[0, :-1] & np.isfinite(edge[1, 1:-1])
    edge[0, 1:-1][top_ok] = 2.0 * center[0, :-1][top_ok] - edge[1, 1:-1][top_ok]

    bottom_ok = finite[-1, :-1] & np.isfinite(edge[-2, 1:-1])
    edge[-1, 1:-1][bottom_ok] = 2.0 * center[-1, :-1][bottom_ok] - edge[-2, 1:-1][bottom_ok]

    left_ok = finite[:-1, 0] & np.isfinite(edge[1:-1, 1])
    edge[1:-1, 0][left_ok] = 2.0 * center[:-1, 0][left_ok] - edge[1:-1, 1][left_ok]

    right_ok = finite[:-1, -1] & np.isfinite(edge[1:-1, -2])
    edge[1:-1, -1][right_ok] = 2.0 * center[:-1, -1][right_ok] - edge[1:-1, -2][right_ok]

    if np.isfinite(center[0, 0]) and np.isfinite(edge[1, 1]):
        edge[0, 0] = 2.0 * center[0, 0] - edge[1, 1]
    if np.isfinite(center[0, -1]) and np.isfinite(edge[1, -2]):
        edge[0, -1] = 2.0 * center[0, -1] - edge[1, -2]
    if np.isfinite(center[-1, 0]) and np.isfinite(edge[-2, 1]):
        edge[-1, 0] = 2.0 * center[-1, 0] - edge[-2, 1]
    if np.isfinite(center[-1, -1]) and np.isfinite(edge[-2, -2]):
        edge[-1, -1] = 2.0 * center[-1, -1] - edge[-2, -2]

    return edge


def build_cell_mask(
    lon: np.ndarray,
    lat: np.ndarray,
    data: np.ma.MaskedArray,
    lon_edge: np.ndarray,
    lat_edge: np.ndarray,
    gap_factor: float,
) -> np.ndarray:
    """Return an MxN mask for pcolormesh cells centered on the swath pixels."""
    center_valid = np.isfinite(lon) & np.isfinite(lat) & ~np.ma.getmaskarray(data)
    edge_valid = np.isfinite(lon_edge) & np.isfinite(lat_edge)

    cell_mask = ~center_valid
    cell_mask |= ~(
        edge_valid[:-1, :-1]
        & edge_valid[:-1, 1:]
        & edge_valid[1:, :-1]
        & edge_valid[1:, 1:]
    )

    median_spacing = estimate_median_spacing(lon, lat)
    if np.isfinite(median_spacing) and median_spacing > 0:
        threshold = gap_factor * median_spacing
        top = np.hypot(lon_edge[:-1, 1:] - lon_edge[:-1, :-1], lat_edge[:-1, 1:] - lat_edge[:-1, :-1])
        bottom = np.hypot(lon_edge[1:, 1:] - lon_edge[1:, :-1], lat_edge[1:, 1:] - lat_edge[1:, :-1])
        left = np.hypot(lon_edge[1:, :-1] - lon_edge[:-1, :-1], lat_edge[1:, :-1] - lat_edge[:-1, :-1])
        right = np.hypot(lon_edge[1:, 1:] - lon_edge[:-1, 1:], lat_edge[1:, 1:] - lat_edge[:-1, 1:])
        diag1 = np.hypot(lon_edge[1:, 1:] - lon_edge[:-1, :-1], lat_edge[1:, 1:] - lat_edge[:-1, :-1])
        diag2 = np.hypot(lon_edge[1:, :-1] - lon_edge[:-1, 1:], lat_edge[1:, :-1] - lat_edge[:-1, 1:])

        cell_mask |= (
            (top > threshold)
            | (bottom > threshold)
            | (left > threshold)
            | (right > threshold)
            | (diag1 > threshold * 1.5)
            | (diag2 > threshold * 1.5)
        )

    return cell_mask


def sanitize_edge_array(edge: np.ndarray, fallback: float) -> np.ndarray:
    """Replace invalid edge coordinates after their cells have been masked out."""
    clean = np.array(edge, copy=True)
    clean[~np.isfinite(clean)] = fallback
    return clean


def plot_swath(
    ax: GeoAxes,
    lon: np.ndarray,
    lat: np.ndarray,
    z: np.ma.MaskedArray,
    *,
    vmin: float,
    vmax: float,
    point_size: float,
    gap_factor: float,
):
    """Plot one swath without connecting it to the other hemisphere."""
    if lon.ndim != 2 or lat.ndim != 2 or z.ndim != 2 or min(z.shape) < 2:
        finite = np.isfinite(lon) & np.isfinite(lat) & ~np.ma.getmaskarray(z)
        return ax.scatter(
            lon[finite],
            lat[finite],
            c=np.asarray(z)[finite],
            s=point_size,
            marker="s",
            linewidths=0,
            edgecolors="none",
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
            transform=ccrs.PlateCarree(),
            zorder=3,
            rasterized=True,
        )

    lon_edge = center_to_edges(lon)
    lat_edge = center_to_edges(lat)
    cell_mask = build_cell_mask(lon, lat, z, lon_edge, lat_edge, gap_factor)
    z_cell = np.ma.array(np.asarray(z, dtype=np.float64), mask=cell_mask)

    lon_fallback = float(np.nanmedian(lon[np.isfinite(lon)])) if np.any(np.isfinite(lon)) else 0.0
    lat_fallback = float(np.nanmedian(lat[np.isfinite(lat)])) if np.any(np.isfinite(lat)) else 0.0
    lon_edge = sanitize_edge_array(lon_edge, lon_fallback)
    lat_edge = sanitize_edge_array(lat_edge, lat_fallback)

    if z_cell.count() == 0:
        finite = np.isfinite(lon) & np.isfinite(lat) & ~np.ma.getmaskarray(z)
        return ax.scatter(
            lon[finite],
            lat[finite],
            c=np.asarray(z)[finite],
            s=point_size,
            marker="s",
            linewidths=0,
            edgecolors="none",
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
            transform=ccrs.PlateCarree(),
            zorder=3,
            rasterized=True,
        )

    return ax.pcolormesh(
        lon_edge,
        lat_edge,
        z_cell,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        shading="flat",
        transform=ccrs.PlateCarree(),
        zorder=3,
        rasterized=True,
    )


def masked_to_points(

    lon: np.ndarray,
    lat: np.ndarray,
    z: np.ma.MaskedArray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mask = np.isfinite(lon) & np.isfinite(lat) & ~np.ma.getmaskarray(z)
    values = np.asarray(z.filled(np.nan), dtype=np.float64)
    mask &= np.isfinite(values)
    return lon[mask].ravel(), lat[mask].ravel(), values[mask].ravel()


def merge_swaths_to_regular_grid(
    swaths: list[tuple[np.ndarray, np.ndarray, np.ma.MaskedArray]],
    extent: tuple[float, float, float, float],
    grid_step: float,
) -> tuple[np.ndarray, np.ndarray, np.ma.MaskedArray] | None:
    west, east, south, north = extent
    if grid_step <= 0:
        raise ValueError("grid_step must be positive.")

    lon_edges = np.arange(west, east + grid_step, grid_step, dtype=np.float64)
    lat_edges = np.arange(south, north + grid_step, grid_step, dtype=np.float64)
    if lon_edges.size < 2 or lat_edges.size < 2:
        raise ValueError("Grid produced fewer than two edges; check --grid-step and --extent.")

    sum_grid = np.zeros((lat_edges.size - 1, lon_edges.size - 1), dtype=np.float64)
    count_grid = np.zeros_like(sum_grid, dtype=np.int32)

    for lon, lat, z in swaths:
        x, y, v = masked_to_points(lon, lat, z)
        if v.size == 0:
            continue

        xi = np.searchsorted(lon_edges, x, side="right") - 1
        yi = np.searchsorted(lat_edges, y, side="right") - 1
        keep = (xi >= 0) & (xi < sum_grid.shape[1]) & (yi >= 0) & (yi < sum_grid.shape[0])
        if not np.any(keep):
            continue
        xi = xi[keep]
        yi = yi[keep]
        v = v[keep]

        np.add.at(sum_grid, (yi, xi), v)
        np.add.at(count_grid, (yi, xi), 1)

    if not np.any(count_grid):
        return None

    mean_grid = np.divide(
        sum_grid,
        count_grid,
        out=np.full_like(sum_grid, np.nan, dtype=np.float64),
        where=count_grid > 0,
    )
    z_grid = np.ma.masked_invalid(mean_grid)
    return lon_edges, lat_edges, z_grid


def plot_merged_grid(
    ax: GeoAxes,
    swaths: list[tuple[np.ndarray, np.ndarray, np.ma.MaskedArray]],
    *,
    extent: tuple[float, float, float, float],
    grid_step: float,
    vmin: float,
    vmax: float,
):
    merged = merge_swaths_to_regular_grid(swaths, extent, grid_step)
    if merged is None:
        return None
    lon_edges, lat_edges, z_grid = merged
    return ax.pcolormesh(
        lon_edges,
        lat_edges,
        z_grid,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        shading="flat",
        transform=ccrs.PlateCarree(),
        zorder=3,
        rasterized=True,
    )


def format_pair_title(pair: PairMatch) -> str:
    midpoint = pair.midpoint.strftime("%Y-%m-%d %H:%MUT")
    if pair.cha.obs_time == pair.chb.obs_time:
        return midpoint
    cha_time = pair.cha.obs_time.strftime("%H:%M")
    chb_time = pair.chb.obs_time.strftime("%H:%M")
    return f"{midpoint}  |  CHA {cha_time} + CHB {chb_time}"


def format_output_name(pair: PairMatch, target_nm: float) -> str:
    midpoint = pair.midpoint.strftime("%Y%m%dT%H%MZ")
    cha_label = pair.cha.obs_time.strftime("%H%M")
    chb_label = pair.chb.obs_time.strftime("%H%M")
    wavelength_label = str(target_nm).replace(".", "p")
    return f"{midpoint}_CHA-{cha_label}_CHB-{chb_label}_{wavelength_label}nm.png"


def add_map_background(ax: GeoAxes) -> None:
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
    west, east, south, north = extent
    lon_line = np.linspace(west, east, num_points)
    lat_line = np.zeros_like(lon_line)

    for i, lon_val in enumerate(lon_line):
        lat_guess = 0.0
        for _ in range(10):
            mlat, _ = apex.geo2apex(lat_guess, lon_val, 0)
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
    gap_factor: float,
    merge_mode: str,
    grid_step: float,
    extent: tuple[float, float, float, float],
    vmin: float,
    vmax: float,
    dpi: int,
    apex: Apex,
) -> None:
    cha_lon, cha_lat, cha_rad = read_geo_grid(archive, pair.cha.member_name, target_nm, quality_mode)
    chb_lon, chb_lat, chb_rad = read_geo_grid(archive, pair.chb.member_name, target_nm, quality_mode)

    if cha_rad.count() == 0 and chb_rad.count() == 0:
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

    swaths = [(cha_lon, cha_lat, cha_rad), (chb_lon, chb_lat, chb_rad)]

    mesh = None
    if merge_mode == "grid":
        mesh = plot_merged_grid(
            geo_ax,
            swaths,
            extent=extent,
            grid_step=grid_step,
            vmin=vmin,
            vmax=vmax,
        )
    else:
        for lon, lat, z in swaths:
            if z.count() == 0:
                continue
            mesh = plot_swath(
                geo_ax,
                lon,
                lat,
                z,
                vmin=vmin,
                vmax=vmax,
                point_size=point_size,
                gap_factor=gap_factor,
            )

    if mesh is None:
        raise RuntimeError("No drawable pixels remained after merging.")

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
    gap_factor: float,
    merge_mode: str,
    grid_step: float,
    extent: tuple[float, float, float, float],
    vmin: float,
    vmax: float,
    dpi: int,
    limit: int | None,
    verbose: bool,
) -> tuple[int, int]:
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
                gap_factor=gap_factor,
                merge_mode=merge_mode,
                grid_step=grid_step,
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
    args = parse_args()
    if args.vmax <= args.vmin:
        raise ValueError("--vmax must be greater than --vmin.")
    if args.point_size <= 0:
        raise ValueError("--point-size must be greater than 0.")
    if args.gap_factor <= 0:
        raise ValueError("--gap-factor must be greater than 0.")
    if args.grid_step <= 0:
        raise ValueError("--grid-step must be greater than 0.")
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
            gap_factor=args.gap_factor,
            merge_mode=args.merge_mode,
            grid_step=args.grid_step,
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
