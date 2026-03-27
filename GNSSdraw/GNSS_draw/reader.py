from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd
import xarray as xr

from .config import SOURCE_DIRS


TIME_CANDIDATES = ("time",)
LAT_CANDIDATES = ("lat", "latitude")
LON_CANDIDATES = ("lon", "longitude")
DATA_VAR_CANDIDATES = {
    "VTEC": ("atec", "vtec", "tec"),
    "dTEC": ("dtec",),
    "ROTI": ("roti",),
}


@dataclass(frozen=True)
class DatasetSchema:
    time_name: str
    time_dim: str
    lat_name: str
    lat_dim: str
    lon_name: str
    lon_dim: str
    data_name: str


@dataclass(frozen=True)
class NcFileInfo:
    path: Path
    year: str
    doy: str
    times: tuple[pd.Timestamp, ...]
    schema: DatasetSchema

    @property
    def first_timestamp(self) -> pd.Timestamp:
        return self.times[0]


@dataclass(frozen=True)
class SliceData:
    category: str
    source_path: Path
    year: str
    doy: str
    timestamp: pd.Timestamp
    time_index: int
    lat: np.ndarray
    lon: np.ndarray
    values: np.ndarray
    units: str | None


def scan_nc_files(data_root: Path, category: str, year: str, doys: tuple[str, ...] | None = None) -> list[Path]:
    category_root = data_root / SOURCE_DIRS[category] / year
    if not category_root.exists():
        raise FileNotFoundError(f"Data directory does not exist: {category_root}")

    if doys:
        day_dirs = [category_root / doy for doy in doys]
    else:
        day_dirs = sorted(path for path in category_root.iterdir() if path.is_dir())

    files: list[Path] = []
    for day_dir in day_dirs:
        if not day_dir.exists():
            continue
        files.extend(sorted(day_dir.glob("*.nc")))

    if not files:
        raise FileNotFoundError(f"No .nc files found under {category_root}")

    return files


def inspect_file(file_path: str | Path, category: str) -> NcFileInfo:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")

    try:
        with xr.open_dataset(path) as dataset:
            schema = detect_dataset_schema(dataset, category)
            times = extract_times(dataset, schema.time_name)
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to read netCDF file: {path}") from exc

    if not times:
        raise ValueError(f"No time values found in file: {path}")

    return NcFileInfo(
        path=path,
        year=path.parent.parent.name,
        doy=path.parent.name,
        times=times,
        schema=schema,
    )


def load_time_slice(
    file_path: str | Path,
    category: str,
    *,
    time_index: int | None = None,
    timestamp: str | pd.Timestamp | None = None,
) -> SliceData:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")

    try:
        with xr.open_dataset(path) as dataset:
            schema = detect_dataset_schema(dataset, category)
            times = extract_times(dataset, schema.time_name)
            selected_index = resolve_time_index(times, time_index=time_index, timestamp=timestamp)
            return build_slice(dataset, schema, category, path, times, selected_index)
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to read netCDF file: {path}") from exc


def iter_time_slices(file_path: str | Path, category: str) -> Iterator[SliceData]:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")

    try:
        with xr.open_dataset(path) as dataset:
            schema = detect_dataset_schema(dataset, category)
            times = extract_times(dataset, schema.time_name)
            for time_index in range(len(times)):
                yield build_slice(dataset, schema, category, path, times, time_index)
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to iterate netCDF file: {path}") from exc


def detect_dataset_schema(dataset: xr.Dataset, category: str) -> DatasetSchema:
    time_name = _find_name(dataset.variables, TIME_CANDIDATES)
    if time_name is None:
        raise ValueError("Could not identify the time variable in the netCDF file.")

    lat_name = _find_name(dataset.variables, LAT_CANDIDATES)
    if lat_name is None:
        raise ValueError("Could not identify the latitude variable in the netCDF file.")

    lon_name = _find_name(dataset.variables, LON_CANDIDATES)
    if lon_name is None:
        raise ValueError("Could not identify the longitude variable in the netCDF file.")

    time_dim = _single_dimension(dataset, time_name, "time")
    lat_dim = _single_dimension(dataset, lat_name, "latitude")
    lon_dim = _single_dimension(dataset, lon_name, "longitude")

    lower_data_vars = {name.lower(): name for name in dataset.data_vars}
    data_name = None
    for candidate in DATA_VAR_CANDIDATES[category]:
        data_name = lower_data_vars.get(candidate.lower())
        if data_name:
            break

    if data_name is None:
        expected = ", ".join(DATA_VAR_CANDIDATES[category])
        raise ValueError(
            f"Could not identify the data variable for {category}. Expected one of: {expected}"
        )

    data_array = dataset[data_name]
    expected_dims = {time_dim, lat_dim, lon_dim}
    if not expected_dims.issubset(set(data_array.dims)):
        raise ValueError(
            f"Data variable '{data_name}' does not include the expected dimensions "
            f"{sorted(expected_dims)}. Found dimensions: {list(data_array.dims)}"
        )

    return DatasetSchema(
        time_name=time_name,
        time_dim=time_dim,
        lat_name=lat_name,
        lat_dim=lat_dim,
        lon_name=lon_name,
        lon_dim=lon_dim,
        data_name=data_name,
    )


def extract_times(dataset: xr.Dataset, time_name: str) -> tuple[pd.Timestamp, ...]:
    try:
        values = pd.to_datetime(dataset[time_name].values, utc=True)
    except Exception as exc:
        raise ValueError("Failed to decode time values from the netCDF file.") from exc

    if isinstance(values, pd.Timestamp):
        values = pd.DatetimeIndex([values])

    return tuple(timestamp.tz_convert(None) for timestamp in values)


def resolve_time_index(
    times: tuple[pd.Timestamp, ...],
    *,
    time_index: int | None = None,
    timestamp: str | pd.Timestamp | None = None,
) -> int:
    if not times:
        raise ValueError("No time values were found in the file.")

    if timestamp is not None:
        target = normalize_timestamp(timestamp)
        for index, candidate in enumerate(times):
            if candidate == target:
                return index
        raise ValueError(
            f"Timestamp {target.strftime('%Y-%m-%d %H:%M:%S')} UTC was not found in the file."
        )

    index = 0 if time_index is None else time_index
    if index < 0 or index >= len(times):
        raise IndexError(f"time_index {index} is out of range for a file with {len(times)} slices.")
    return index


def normalize_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.to_datetime(value, utc=True)
    if isinstance(timestamp, pd.DatetimeIndex):
        if len(timestamp) != 1:
            raise ValueError(f"Expected one timestamp value, got {len(timestamp)}")
        timestamp = timestamp[0]
    return timestamp.tz_convert(None)


def build_slice(
    dataset: xr.Dataset,
    schema: DatasetSchema,
    category: str,
    path: Path,
    times: tuple[pd.Timestamp, ...],
    time_index: int,
) -> SliceData:
    data_array = dataset[schema.data_name]
    selected = data_array.isel({schema.time_dim: time_index}).transpose(schema.lat_dim, schema.lon_dim)

    lat = np.asarray(dataset[schema.lat_name].values, dtype=float)
    lon = np.asarray(dataset[schema.lon_name].values, dtype=float)
    values = np.asarray(selected.values, dtype=float)

    if lat.ndim != 1 or lon.ndim != 1 or values.ndim != 2:
        raise ValueError(
            "Expected 1D latitude, 1D longitude, and a 2D data slice after selecting one time index."
        )

    return SliceData(
        category=category,
        source_path=path,
        year=path.parent.parent.name,
        doy=path.parent.name,
        timestamp=times[time_index],
        time_index=time_index,
        lat=lat,
        lon=lon,
        values=values,
        units=data_array.attrs.get("units"),
    )


def _find_name(available: dict[str, object], candidates: tuple[str, ...]) -> str | None:
    lowered = {name.lower(): name for name in available}
    for candidate in candidates:
        matched = lowered.get(candidate.lower())
        if matched is not None:
            return matched
    return None


def _single_dimension(dataset: xr.Dataset, variable_name: str, label: str) -> str:
    variable = dataset[variable_name]
    if len(variable.dims) != 1:
        raise ValueError(f"The {label} variable '{variable_name}' must be one-dimensional.")
    return variable.dims[0]
