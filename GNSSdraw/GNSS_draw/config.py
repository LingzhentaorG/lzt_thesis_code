from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib


CATEGORY_ALIASES = {
    "vtec": "VTEC",
    "atec": "VTEC",
    "dtec": "dTEC",
    "roti": "ROTI",
}

SOURCE_DIRS = {
    "VTEC": "VTEC_data",
    "dTEC": "dTEC_data",
    "ROTI": "ROTI_data",
}

STYLE_SECTION_NAMES = {
    "VTEC": "vtec",
    "dTEC": "dtec",
    "ROTI": "roti",
}

REGION_PRESETS = {
    "global": (-180.0, 180.0, -90.0, 90.0),
    "asia_pacific": (60.0, 180.0, -50.0, 60.0),
    "south_america": (-90.0, -30.0, -60.0, 20.0),
    "americas": (-170.0, -20.0, -80.0, 80.0),
}

DEFAULT_STYLES = {
    "VTEC": {"cmap": "viridis", "vmin": 0.0, "vmax": 80.0},
    "dTEC": {"cmap": "viridis", "vmin": -0.4, "vmax": 0.4},
    "ROTI": {"cmap": "viridis", "vmin": 0.0, "vmax": 1.0},
}

SUPPORTED_IMAGE_FORMATS = {
    "png": "png",
    "jpg": "jpg",
    "jpeg": "jpg",
}

SUPPORTED_LON_MODES = {
    "auto": "auto",
    "-180_180": "-180_180",
    "-180to180": "-180_180",
    "-180-180": "-180_180",
    "180": "-180_180",
    "0_360": "0_360",
    "0to360": "0_360",
    "360": "0_360",
}

REGION_ALIASES = {
    "global": "global",
    "asia_pacific": "asia_pacific",
    "asia-pacific": "asia_pacific",
    "south_america": "south_america",
    "south-america": "south_america",
    "americas": "americas",
    "america": "americas",
    "custom": "custom",
}


@dataclass(frozen=True)
class StyleConfig:
    cmap: str
    vmin: float
    vmax: float


@dataclass(frozen=True)
class CustomRegion:
    lon_min: float
    lon_max: float
    lat_min: float
    lat_max: float


@dataclass(frozen=True)
class MagneticEquatorConfig:
    enabled: bool
    color: str
    linewidth: float


@dataclass(frozen=True)
class DataConfig:
    root: Path
    year: str
    category: str
    mode: str | None
    file: Path | None
    timestamp: str | None
    time_index: int | None
    doys: tuple[str, ...] | None


@dataclass(frozen=True)
class OutputConfig:
    root: Path
    image_format: str
    dpi: int


@dataclass(frozen=True)
class PlotConfig:
    region: str
    lon_mode: str
    figure_size: tuple[float, float]
    font_family: str
    magnetic_equator: MagneticEquatorConfig


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    data: DataConfig
    output: OutputConfig
    plot: PlotConfig
    styles: dict[str, StyleConfig]
    custom_region: CustomRegion | None

    def style_for(self, category: str) -> StyleConfig:
        return self.styles[category]


def load_config(config_path: str | Path, cli_mode: str) -> AppConfig:
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")

    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a TOML table at the top level.")

    base_dir = path.parent
    data_table = _get_table(raw, "data")
    output_table = _get_table(raw, "output")
    plot_table = _get_table(raw, "plot")
    style_table = _get_table(raw, "style")
    region_table = _get_table(raw, "region")

    category = normalize_category(data_table.get("category", "VTEC"))
    declared_mode = _normalize_mode(data_table.get("mode")) if data_table.get("mode") else None
    year = str(data_table.get("year", "2024"))
    data_root = _resolve_path(data_table.get("root"), base_dir, default=base_dir / ".." / "Data_download")
    output_root = _resolve_path(output_table.get("root"), base_dir, default=base_dir / "outputs")
    file_path = _resolve_optional_file(data_table.get("file"), base_dir, data_root)

    timestamp = str(data_table["timestamp"]).strip() if data_table.get("timestamp") else None
    time_index = _parse_optional_int(data_table.get("time_index"), "data.time_index")
    doys = _parse_doys(data_table.get("doys"))

    image_format = _normalize_image_format(output_table.get("image_format", "png"))
    dpi = _parse_optional_int(output_table.get("dpi", 300), "output.dpi") or 300

    region_name = _normalize_region(plot_table.get("region", "americas"))
    lon_mode = _normalize_lon_mode(plot_table.get("lon_mode", "auto"))
    figure_size = _parse_figure_size(plot_table.get("figure_size", (12.0, 6.75)))
    font_family = str(plot_table.get("font_family", "Times New Roman")).strip() or "Times New Roman"
    magnetic_equator = _parse_magnetic_equator(plot_table)

    styles = {
        category_name: _parse_style(style_table.get(section_name), DEFAULT_STYLES[category_name])
        for category_name, section_name in STYLE_SECTION_NAMES.items()
    }
    custom_region = _parse_custom_region(region_table.get("custom"))

    if cli_mode == "single" and file_path is None:
        raise ValueError("Single mode requires [data].file in the config.")

    return AppConfig(
        config_path=path,
        data=DataConfig(
            root=data_root,
            year=year,
            category=category,
            mode=declared_mode,
            file=file_path,
            timestamp=timestamp,
            time_index=time_index,
            doys=doys,
        ),
        output=OutputConfig(root=output_root, image_format=image_format, dpi=dpi),
        plot=PlotConfig(
            region=region_name,
            lon_mode=lon_mode,
            figure_size=figure_size,
            font_family=font_family,
            magnetic_equator=magnetic_equator,
        ),
        styles=styles,
        custom_region=custom_region,
    )


def normalize_category(value: Any) -> str:
    key = str(value).strip().lower()
    category = CATEGORY_ALIASES.get(key)
    if category is None:
        allowed = ", ".join(sorted(CATEGORY_ALIASES))
        raise ValueError(f"Unsupported category '{value}'. Supported values: {allowed}")
    return category


def _get_table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Config section [{key}] must be a table.")
    return value


def _resolve_path(raw: Any, base_dir: Path, default: Path) -> Path:
    if raw is None:
        return default.resolve()
    return _candidate_path(Path(str(raw)), base_dir).resolve()


def _resolve_optional_file(raw: Any, base_dir: Path, data_root: Path) -> Path | None:
    if raw is None:
        return None
    candidate = Path(str(raw)).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    primary = (base_dir / candidate).resolve()
    if primary.exists():
        return primary

    secondary = (data_root / candidate).resolve()
    if secondary.exists():
        return secondary

    return primary


def _candidate_path(path: Path, base_dir: Path) -> Path:
    if path.is_absolute():
        return path.expanduser()
    return (base_dir / path).expanduser()


def _normalize_mode(value: Any) -> str:
    mode = str(value).strip().lower()
    if mode not in {"single", "batch"}:
        raise ValueError("Config field data.mode must be 'single' or 'batch'.")
    return mode


def _normalize_image_format(value: Any) -> str:
    image_format = str(value).strip().lower()
    normalized = SUPPORTED_IMAGE_FORMATS.get(image_format)
    if normalized is None:
        allowed = ", ".join(sorted(SUPPORTED_IMAGE_FORMATS))
        raise ValueError(f"Unsupported output.image_format '{value}'. Supported values: {allowed}")
    return normalized


def _normalize_region(value: Any) -> str:
    key = str(value).strip().lower()
    region = REGION_ALIASES.get(key)
    if region is None:
        allowed = ", ".join(sorted(REGION_ALIASES))
        raise ValueError(f"Unsupported plot.region '{value}'. Supported values: {allowed}")
    return region


def _normalize_lon_mode(value: Any) -> str:
    key = str(value).strip().lower()
    lon_mode = SUPPORTED_LON_MODES.get(key)
    if lon_mode is None:
        allowed = ", ".join(sorted(SUPPORTED_LON_MODES))
        raise ValueError(f"Unsupported plot.lon_mode '{value}'. Supported values: {allowed}")
    return lon_mode


def _parse_optional_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Config field {name} must be an integer.") from exc


def _parse_doys(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("Config field data.doys must be an array.")
    return tuple(str(item).zfill(3) for item in value)


def _parse_figure_size(value: Any) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("Config field plot.figure_size must contain exactly two numbers.")
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError) as exc:
        raise ValueError("Config field plot.figure_size must contain numeric values.") from exc


def _parse_style(value: Any, defaults: dict[str, float | str]) -> StyleConfig:
    table = value or {}
    if not isinstance(table, dict):
        raise ValueError("Each [style.<category>] section must be a table.")
    try:
        return StyleConfig(
            cmap=str(table.get("cmap", defaults["cmap"])),
            vmin=float(table.get("vmin", defaults["vmin"])),
            vmax=float(table.get("vmax", defaults["vmax"])),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Style values must be numeric for vmin/vmax and string for cmap.") from exc


def _parse_custom_region(value: Any) -> CustomRegion | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Config section [region.custom] must be a table.")
    try:
        return CustomRegion(
            lon_min=float(value["lon_min"]),
            lon_max=float(value["lon_max"]),
            lat_min=float(value["lat_min"]),
            lat_max=float(value["lat_max"]),
        )
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(f"Missing region.custom.{missing} in config.") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError("Custom region bounds must be numeric.") from exc


def _parse_magnetic_equator(plot_table: dict[str, Any]) -> MagneticEquatorConfig:
    """
    解析磁赤道配置选项。

    Args:
        plot_table: plot 配置部分的字典

    Returns:
        MagneticEquatorConfig: 磁赤道配置对象
    """
    enabled = bool(plot_table.get("show_magnetic_equator", False))
    color = str(plot_table.get("magnetic_equator_color", "red")).strip() or "red"
    try:
        linewidth = float(plot_table.get("magnetic_equator_linewidth", 1.5))
    except (TypeError, ValueError):
        linewidth = 1.5
    return MagneticEquatorConfig(enabled=enabled, color=color, linewidth=linewidth)
