from __future__ import annotations

import logging
from pathlib import Path

from .config import AppConfig
from .plotter import plot_map
from .preprocess import format_filename_timestamp, format_title_timestamp, prepare_slice
from .reader import NcFileInfo, SliceData, inspect_file, iter_time_slices, load_time_slice, scan_nc_files


LOGGER = logging.getLogger(__name__)


def export_single(config: AppConfig) -> Path:
    if config.data.file is None:
        raise ValueError("Single mode requires a file path in the config.")

    LOGGER.info("Current file: %s", config.data.file)
    selection = (
        f"timestamp={config.data.timestamp}"
        if config.data.timestamp
        else f"time_index={config.data.time_index or 0}"
    )
    LOGGER.info("Selecting slice with %s", selection)

    slice_data = load_time_slice(
        config.data.file,
        config.data.category,
        time_index=config.data.time_index,
        timestamp=config.data.timestamp,
    )
    return render_slice(slice_data, config, allow_skip=False)


def export_batch(config: AppConfig) -> list[Path]:
    files: list[Path] = []
    years = config.data.years or (config.data.year,)
    for year in years:
        files.extend(
            scan_nc_files(
                config.data.root,
                config.data.category,
                year,
                doys=config.data.doys,
            )
        )

    inspected_files: list[NcFileInfo] = []
    for file_path in files:
        try:
            inspected_files.append(inspect_file(file_path, config.data.category))
        except Exception as exc:
            LOGGER.error("Failed to inspect %s: %s", file_path, exc)

    if not inspected_files:
        raise RuntimeError("No readable .nc files were found for batch export.")

    inspected_files.sort(key=lambda item: item.first_timestamp)
    total_slices = sum(len(item.times) for item in inspected_files)
    LOGGER.info(
        "Discovered %s files and %s time slices for category %s.",
        len(inspected_files),
        total_slices,
        config.data.category,
    )

    outputs: list[Path] = []
    for file_info in inspected_files:
        LOGGER.info("Current file: %s", file_info.path)
        try:
            for slice_data in iter_time_slices(file_info.path, config.data.category):
                output = render_slice(slice_data, config, allow_skip=True)
                if output is not None:
                    outputs.append(output)
        except Exception as exc:
            LOGGER.error("Failed to process file %s: %s", file_info.path, exc)

    if not outputs:
        raise RuntimeError("Batch export did not generate any figures.")

    LOGGER.info("Batch export completed. Generated %s figures.", len(outputs))
    return outputs


def render_slice(slice_data: SliceData, config: AppConfig, *, allow_skip: bool) -> Path | None:
    LOGGER.info("Current processing time: %s UTC", format_title_timestamp(slice_data.timestamp))

    try:
        processed = prepare_slice(
            slice_data,
            region_name=config.plot.region,
            custom_region=config.custom_region,
            lon_mode=config.plot.lon_mode,
        )
    except ValueError as exc:
        if allow_skip:
            LOGGER.warning(
                "Skipping %s at %s UTC: %s",
                slice_data.source_path.name,
                format_title_timestamp(slice_data.timestamp),
                exc,
            )
            return None
        raise

    output_path = build_output_path(config, slice_data)
    try:
        plot_map(
            processed,
            style=config.style_for(slice_data.category),
            output_path=output_path,
            dpi=config.output.dpi,
            figure_size=config.plot.figure_size,
            requested_font_family=config.plot.font_family,
            magnetic_equator=config.plot.magnetic_equator,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not create the output figure at {output_path}") from exc

    LOGGER.info("Output path: %s", output_path)
    return output_path


def build_output_path(config: AppConfig, slice_data: SliceData) -> Path:
    filename = (
        f"{slice_data.category}_"
        f"{format_filename_timestamp(slice_data.timestamp)}_"
        f"{config.plot.region}."
        f"{config.output.image_format}"
    )
    return (
        config.output.root
        / slice_data.category
        / slice_data.year
        / slice_data.doy
        / filename
    )
