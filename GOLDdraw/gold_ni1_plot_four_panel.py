#!/usr/bin/env python
"""Plot GOLD NI1 135.6 nm data as a 2x2 four-panel figure from tar archive."""

from __future__ import annotations

import re
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib
import numpy as np
from apexpy import Apex
from netCDF4 import Dataset

if TYPE_CHECKING:
    from cartopy.mpl.geoaxes import GeoAxes

matplotlib.use("Agg")
import matplotlib.pyplot as plt


FILE_PATTERN = re.compile(
    r"GOLD_L1C_(CH[AB])_NI1_(\d{4})_(\d{3})_(\d{2})_(\d{2})_.*\.nc$"
)


@dataclass(frozen=True)
class ArchiveEntry:
    """Represents a single NetCDF file entry within a tar archive."""
    tar_path: Path
    member_name: str
    hemisphere: str
    obs_time: datetime


@dataclass(frozen=True)
class PairMatch:
    """Represents a matched pair of CHA and CHB observations."""
    cha: ArchiveEntry
    chb: ArchiveEntry

    @property
    def midpoint(self) -> datetime:
        """Calculate the midpoint time between CHA and CHB observations."""
        return self.cha.obs_time + (self.chb.obs_time - self.cha.obs_time) / 2


def parse_entry(tar_path: Path, member_name: str) -> ArchiveEntry | None:
    """Parse a tar member name to extract hemisphere and observation time."""
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
    """Discover all valid NI1 entries within a tar archive."""
    entries: list[ArchiveEntry] = []
    with tarfile.open(tar_path) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            entry = parse_entry(tar_path, member.name)
            if entry is not None:
                entries.append(entry)
    return sorted(entries, key=lambda item: (item.obs_time, item.hemisphere, item.member_name))


def match_pair_by_time(
    entries: list[ArchiveEntry], target_time: datetime, max_delta_minutes: float = 5.0
) -> PairMatch | None:
    """Find a matching CHA/CHB pair closest to the target time."""
    cha_entries = [e for e in entries if e.hemisphere == "CHA"]
    chb_entries = [e for e in entries if e.hemisphere == "CHB"]

    best_cha = None
    best_chb = None
    best_cha_diff = None
    best_chb_diff = None

    for entry in cha_entries:
        diff = abs((entry.obs_time - target_time).total_seconds())
        if best_cha_diff is None or diff < best_cha_diff:
            best_cha_diff = diff
            best_cha = entry

    for entry in chb_entries:
        diff = abs((entry.obs_time - target_time).total_seconds())
        if best_chb_diff is None or diff < best_chb_diff:
            best_chb_diff = diff
            best_chb = entry

    if best_cha is None or best_chb is None:
        return None

    pair_diff = abs((best_chb.obs_time - best_cha.obs_time).total_seconds())
    if pair_diff > max_delta_minutes * 60:
        return None

    return PairMatch(cha=best_cha, chb=best_chb)


def read_dataset_bytes(archive: tarfile.TarFile, member_name: str) -> bytes:
    """Read the raw bytes of a file from within a tar archive."""
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
    """Read geographic coordinates and radiance data from a NetCDF file."""
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
    """Estimate the median spacing between adjacent grid points."""
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
    """Convert center coordinates to edge coordinates for pcolormesh."""
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
    """Build a mask for pcolormesh cells based on validity and gap detection."""
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
    """Replace invalid edge coordinates with a fallback value."""
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
    """Plot a single swath using pcolormesh or scatter as fallback."""
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


def add_map_background(ax: GeoAxes) -> None:
    """Add map background features to a GeoAxes."""
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
    gl.top_labels = True
    gl.right_labels = False
    gl.bottom_labels = False
    gl.xlabel_style = {'size': 12}
    gl.ylabel_style = {'size': 12}


def compute_magnetic_equator(
    apex: Apex,
    extent: tuple[float, float, float, float],
    num_points: int = 500,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute the magnetic equator coordinates within the given extent."""
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


def add_magnetic_equator(ax: GeoAxes, apex: Apex, extent: tuple[float, float, float, float]) -> None:
    """Add the magnetic equator line to the map."""
    try:
        lon_eq, lat_eq = compute_magnetic_equator(apex, extent)
        if len(lon_eq) > 1:
            ax.plot(
                lon_eq,
                lat_eq,
                color="#ff6b6b",
                linewidth=1.5,
                linestyle="--",
                transform=ccrs.PlateCarree(),
                zorder=10,
            )
    except Exception as e:
        print(f"[WARN] Failed to draw magnetic equator: {e}")


def format_panel_title(pair: PairMatch) -> str:
    """Format the title for a single panel.
    
    When CHA and CHB observation times differ, display both times.
    Format: '2024-10-10 23:22UT  |  CHA 23:21 + CHB 23:24'
    """
    midpoint = pair.midpoint.strftime("%Y-%m-%d %H:%MUT")
    if pair.cha.obs_time == pair.chb.obs_time:
        return midpoint
    cha_time = pair.cha.obs_time.strftime("%H:%M")
    chb_time = pair.chb.obs_time.strftime("%H:%M")
    return f"{midpoint}  |  CHA {cha_time} + CHB {chb_time}"


def estimate_projected_aspect(
    projection: ccrs.Projection,
    extent: tuple[float, float, float, float],
    num_samples: int = 181,
) -> float:
    """Estimate the projected width/height ratio of a map extent."""
    west, east, south, north = extent

    lon_top = np.linspace(west, east, num_samples)
    lon_bottom = np.linspace(west, east, num_samples)
    lat_left = np.linspace(south, north, num_samples)
    lat_right = np.linspace(south, north, num_samples)

    lon = np.concatenate(
        [
            lon_top,
            lon_bottom,
            np.full(num_samples, west, dtype=np.float64),
            np.full(num_samples, east, dtype=np.float64),
        ]
    )
    lat = np.concatenate(
        [
            np.full(num_samples, north, dtype=np.float64),
            np.full(num_samples, south, dtype=np.float64),
            lat_left,
            lat_right,
        ]
    )

    projected = projection.transform_points(ccrs.PlateCarree(), lon, lat)
    x = projected[:, 0]
    y = projected[:, 1]
    valid = np.isfinite(x) & np.isfinite(y)
    if not np.any(valid):
        return 1.0

    width = float(np.nanmax(x[valid]) - np.nanmin(x[valid]))
    height = float(np.nanmax(y[valid]) - np.nanmin(y[valid]))
    if width <= 0.0 or height <= 0.0:
        return 1.0
    return width / height


def create_four_panel_figure(
    tar_path: Path,
    target_times: list[datetime],
    output_path: Path,
    target_nm: float = 135.6,
    quality_mode: str = "all",
    figsize: tuple[float, float] = (14.0, 11.0),
    point_size: float = 9.0,
    gap_factor: float = 6.0,
    extent: tuple[float, float, float, float] = (-105.0, 15.0, -60.0, 60.0),
    vmin: float = 0.0,
    vmax: float = 300.0,
    dpi: int = 180,
) -> bool:
    """Create a 2x2 four-panel figure from the specified times in a tar archive."""
    entries = discover_entries(tar_path)
    if not entries:
        print(f"[ERROR] No entries found in {tar_path}")
        return False

    pairs: list[PairMatch | None] = []
    for target_time in target_times:
        pair = match_pair_by_time(entries, target_time)
        pairs.append(pair)
        if pair is None:
            print(f"[WARN] No matching pair found for {target_time}")

    if all(p is None for p in pairs):
        print("[ERROR] No valid pairs found for any target time")
        return False

    valid_pairs = [(i, p) for i, p in enumerate(pairs) if p is not None]
    valid_pairs.sort(key=lambda item: item[1].midpoint)
    sorted_indices = {orig_idx: new_idx for new_idx, (orig_idx, _) in enumerate(valid_pairs)}

    left_margin = 0.08
    right_margin = 0.06
    bottom_margin = 0.10
    top_margin = 0.10
    h_gap = 0.04
    v_gap = 0.06
    cbar_gap = 0.025
    cbar_width = 0.018

    fig = plt.figure(figsize=figsize)

    projection = ccrs.PlateCarree()
    map_aspect = estimate_projected_aspect(projection, extent)
    fig_width, fig_height = figsize

    available_width = 1.0 - left_margin - right_margin - cbar_gap - cbar_width
    available_height = 1.0 - bottom_margin - top_margin
    max_plot_width = (available_width - h_gap) / 2.0
    max_plot_height = (available_height - v_gap) / 2.0

    # Cartopy keeps the geographic aspect ratio inside each GeoAxes.
    # If the axes box is too wide, the extra width becomes internal blank space.
    plot_width = max_plot_height * (fig_height / fig_width) * map_aspect
    plot_height = max_plot_height

    if plot_width > max_plot_width:
        plot_width = max_plot_width
        plot_height = plot_width * (fig_width / fig_height) / map_aspect

    content_height = 2.0 * plot_height + v_gap
    content_bottom = bottom_margin + (available_height - content_height) / 2.0

    axes: list[GeoAxes] = []
    meshes: list = []

    apex = Apex(date=2024.5)

    with tarfile.open(tar_path) as archive:
        for new_idx, (orig_idx, pair) in enumerate(valid_pairs):
            row = new_idx // 2
            col = new_idx % 2

            left = left_margin + col * (plot_width + h_gap)
            bottom = content_bottom + (1 - row) * (plot_height + v_gap)

            ax = fig.add_axes([left, bottom, plot_width, plot_height], projection=projection)
            axes.append(ax)

            ax.set_extent(extent, crs=projection)
            add_map_background(ax)
            add_magnetic_equator(ax, apex, extent)

            cha_lon, cha_lat, cha_rad = read_geo_grid(
                archive, pair.cha.member_name, target_nm, quality_mode
            )
            chb_lon, chb_lat, chb_rad = read_geo_grid(
                archive, pair.chb.member_name, target_nm, quality_mode
            )

            mesh = None
            for lon, lat, z in [(cha_lon, cha_lat, cha_rad), (chb_lon, chb_lat, chb_rad)]:
                if z.count() == 0:
                    continue
                mesh = plot_swath(
                    ax,
                    lon,
                    lat,
                    z,
                    vmin=vmin,
                    vmax=vmax,
                    point_size=point_size,
                    gap_factor=gap_factor,
                )

            meshes.append(mesh)
            panel_label = chr(ord('a') + new_idx)
            ax.text(
                0.5, -0.02, f"({panel_label}) {format_panel_title(pair)}",
                transform=ax.transAxes,
                fontsize=12,
                ha='center',
                va='top'
            )

    valid_meshes = [m for m in meshes if m is not None]
    if valid_meshes:
        cbar_left = left_margin + 2.0 * plot_width + h_gap + cbar_gap
        cbar_bottom = content_bottom
        cbar_height = content_height

        cbar_ax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
        cbar = fig.colorbar(valid_meshes[0], cax=cbar_ax)
        cbar.set_label(f"Radiance @ {target_nm:.1f} nm (Rayleighs/nm)", fontsize=12)
        cbar.ax.tick_params(labelsize=12)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)

    print(f"[OK] Saved four-panel figure to {output_path}")
    return True


def main() -> int:
    """Main entry point for the four-panel plot generation script."""
    tar_path = Path(r"d:\Desktop\GOLDdraw\NI2024100820241014.tar")

    target_times = [
        datetime(2024, 10, 10, 23, 52),
        datetime(2024, 10, 11, 0, 22),
        datetime(2024, 10, 12, 0, 22),
        datetime(2024, 10, 9, 0, 23),
    ]

    output_dir = Path(r"d:\Desktop\GOLDdraw\four_panel_output")
    output_path = output_dir / "four_panel_135p6nm.png"

    success = create_four_panel_figure(
        tar_path=tar_path,
        target_times=target_times,
        output_path=output_path,
        target_nm=135.6,
        quality_mode="all",
        figsize=(14.0, 11.0),
        point_size=9.0,
        gap_factor=6.0,
        extent=(-105.0, 15.0, -60.0, 60.0),
        vmin=0.0,
        vmax=300.0,
        dpi=180,
    )

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
