from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager


BZ_DATASET_ID = "OMNI_HRO2_1MIN"
INDEX_DATASET_ID = "OMNI2_H0_MRG1HR"
DATA_URL = "https://cdaweb.gsfc.nasa.gov/hapi/data"

OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "outputs"
DATA_DIR = OUTPUT_ROOT / "data"
FIG_DIR = OUTPUT_ROOT / "figures"


@dataclass(frozen=True)
class EventWindow:
    slug: str
    start: str
    end: str

    @property
    def title_range(self) -> str:
        start_dt = pd.Timestamp(self.start).strftime("%Y-%m-%d %H:%M")
        end_dt = pd.Timestamp(self.end).strftime("%Y-%m-%d %H:%M")
        return f"{start_dt} to {end_dt} UTC"

    @property
    def start_ts(self) -> pd.Timestamp:
        return pd.Timestamp(self.start).tz_convert("UTC")

    @property
    def end_ts(self) -> pd.Timestamp:
        return pd.Timestamp(self.end).tz_convert("UTC")


EVENT_WINDOWS: tuple[EventWindow, ...] = (
    EventWindow("20240510_20240513", "2024-05-10T00:00:00Z", "2024-05-13T00:00:00Z"),
    EventWindow("20241010_20241013", "2024-10-10T00:00:00Z", "2024-10-13T00:00:00Z"),
    EventWindow("20241231_20250103", "2024-12-31T00:00:00Z", "2025-01-03T00:00:00Z"),
)


def configure_matplotlib() -> None:
    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    serif_fonts = [
        "Times New Roman",
        "Nimbus Roman",
        "TeX Gyre Termes",
        "Liberation Serif",
        "DejaVu Serif",
    ]
    selected = [font for font in serif_fonts if font in available_fonts]

    plt.rcParams["font.family"] = "serif"
    plt.rcParams["font.serif"] = selected or ["DejaVu Serif"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"
    plt.rcParams["axes.edgecolor"] = "black"
    plt.rcParams["axes.linewidth"] = 1.0
    plt.rcParams["savefig.facecolor"] = "white"


def kp_code_to_decimal(value: float | int | None) -> float:
    if value is None or pd.isna(value):
        return np.nan
    value = int(value)
    remainder_map = {0: 0.0, 3: 1 / 3, 7: 2 / 3}
    remainder = value % 10
    if remainder not in remainder_map:
        return value / 10.0
    return value // 10 + remainder_map[remainder]


def hapi_query(dataset_id: str, parameters: str, start: str, end: str) -> str:
    query = {
        "id": dataset_id,
        "parameters": parameters,
        "time.min": start,
        "time.max": end,
        "format": "csv",
    }
    return f"{DATA_URL}?{urlencode(query)}"


def fetch_csv(url: str, column_names: list[str]) -> pd.DataFrame:
    with urlopen(url, timeout=90) as response:
        payload = response.read().decode("utf-8", errors="replace")
    if "HAPI error" in payload:
        raise RuntimeError(payload)
    return pd.read_csv(StringIO(payload), names=column_names)


def fetch_bz_window(window: EventWindow) -> pd.DataFrame:
    url = hapi_query(BZ_DATASET_ID, "BZ_GSM", window.start, window.end)
    frame = fetch_csv(url, ["Time", "IMF_Bz_nT"])
    frame["Time"] = pd.to_datetime(frame["Time"], utc=True)
    frame["IMF_Bz_nT"] = frame["IMF_Bz_nT"].replace(9999.99, np.nan)
    return frame.sort_values("Time").reset_index(drop=True)


def fetch_index_window(window: EventWindow) -> pd.DataFrame:
    url = hapi_query(INDEX_DATASET_ID, "KP1800,DST1800", window.start, window.end)
    frame = fetch_csv(url, ["Time", "Kp_code", "Dst_nT"])
    frame["Time"] = pd.to_datetime(frame["Time"], utc=True)
    frame = frame.sort_values("Time").reset_index(drop=True)

    frame["PlotTime"] = frame["Time"] - pd.Timedelta(minutes=30)
    frame["Dst_nT"] = frame["Dst_nT"].replace(99999, np.nan)
    frame["Kp_code"] = frame["Kp_code"].replace(99, np.nan)
    frame["Kp"] = frame["Kp_code"].map(kp_code_to_decimal)
    return frame


def reduce_kp_to_3hour(indices_frame: pd.DataFrame) -> pd.DataFrame:
    kp_frame = indices_frame.loc[:, ["PlotTime", "Kp"]].dropna().copy()
    kp_frame["KpStart"] = kp_frame["PlotTime"].dt.floor("3h")
    kp_frame = kp_frame.groupby("KpStart", as_index=False)["Kp"].first()
    kp_frame["KpEnd"] = kp_frame["KpStart"] + pd.Timedelta(hours=3)
    return kp_frame


def save_bz_csv(frame: pd.DataFrame, window: EventWindow) -> Path:
    output_path = DATA_DIR / f"omni_bz_1min_{window.slug}.csv"
    export_frame = frame.copy()
    export_frame["Time"] = export_frame["Time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    export_frame.to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path


def save_indices_csv(frame: pd.DataFrame, kp_frame: pd.DataFrame, window: EventWindow) -> tuple[Path, Path]:
    hourly_path = DATA_DIR / f"omni_dst_kp_hourly_{window.slug}.csv"
    kp_path = DATA_DIR / f"omni_kp_3hour_{window.slug}.csv"

    hourly_export = frame.copy()
    hourly_export["Time"] = hourly_export["Time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    hourly_export["PlotTime"] = hourly_export["PlotTime"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    hourly_export.to_csv(hourly_path, index=False, encoding="utf-8-sig")

    kp_export = kp_frame.copy()
    kp_export["KpStart"] = kp_export["KpStart"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    kp_export["KpEnd"] = kp_export["KpEnd"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    kp_export.to_csv(kp_path, index=False, encoding="utf-8-sig")

    return hourly_path, kp_path


def add_common_axis_style(axis: plt.Axes) -> None:
    axis.grid(True, axis="y", which="major", linestyle="--", linewidth=0.55, color="#d0d0d0")
    axis.grid(True, axis="x", which="major", linestyle=":", linewidth=0.45, color="#e0e0e0")
    axis.tick_params(which="major", direction="in", top=True, right=True, length=6, width=0.9, labelsize=10)
    axis.tick_params(which="minor", direction="in", top=True, right=True, length=3, width=0.7)
    axis.minorticks_on()


def add_stat_text(axis: plt.Axes, text: str) -> None:
    axis.text(
        0.012,
        0.92,
        text,
        transform=axis.transAxes,
        ha="left",
        va="top",
        fontsize=10,
        bbox={"boxstyle": "square,pad=0.22", "facecolor": "white", "edgecolor": "#b0b0b0", "linewidth": 0.6},
    )


def plot_window(bz_frame: pd.DataFrame, indices_frame: pd.DataFrame, kp_frame: pd.DataFrame, window: EventWindow) -> Path:
    bz_time = bz_frame["Time"].dt.tz_convert("UTC").dt.tz_localize(None)
    bz = bz_frame["IMF_Bz_nT"]

    dst_time = indices_frame["PlotTime"].dt.tz_convert("UTC").dt.tz_localize(None)
    dst = indices_frame["Dst_nT"]

    kp_start = kp_frame["KpStart"].dt.tz_convert("UTC").dt.tz_localize(None)
    kp = kp_frame["Kp"]

    start_dt = window.start_ts.tz_localize(None)
    end_dt = window.end_ts.tz_localize(None)

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(12.2, 9.6),
        sharex=True,
        gridspec_kw={"height_ratios": [1.15, 1.0, 0.85]},
    )
    fig.subplots_adjust(top=0.86, bottom=0.09, left=0.10, right=0.98, hspace=0.10)

    fig.suptitle("OMNI Solar Wind Parameters", fontsize=18, y=0.965)
    fig.text(0.5, 0.925, window.title_range, ha="center", va="center", fontsize=12.5)

    ax_bz, ax_dst, ax_kp = axes

    ax_bz.plot(bz_time, bz, color="#1f4e79", linewidth=0.85)
    ax_bz.axhline(0, color="black", linewidth=0.8)
    ax_bz.set_ylabel("IMF Bz (nT)", fontsize=12)
    ax_bz.set_title("(a) IMF Bz (GSM, 1 min)", loc="left", fontsize=12, pad=8)
    add_stat_text(ax_bz, f"Max = {bz.max(skipna=True):.1f} nT\nMin = {bz.min(skipna=True):.1f} nT")
    add_common_axis_style(ax_bz)

    ax_dst.plot(dst_time, dst, color="#2f6f3e", linewidth=1.05)
    ax_dst.axhline(-50, color="#7f1d1d", linewidth=0.9, linestyle="--")
    ax_dst.fill_between(dst_time, dst, -50, where=dst < -50, color="#b24c4c", alpha=0.14)
    ax_dst.text(start_dt + pd.Timedelta(hours=1), -43, "Dst = -50 nT", fontsize=10, color="#7f1d1d")
    ax_dst.set_ylabel("Dst (nT)", fontsize=12)
    ax_dst.set_title("(b) Disturbance Storm Time Index", loc="left", fontsize=12, pad=8)
    add_stat_text(ax_dst, f"Minimum = {dst.min(skipna=True):.0f} nT")
    add_common_axis_style(ax_dst)

    ax_kp.bar(
        kp_start,
        kp,
        width=3 / 24,
        align="edge",
        color="#6b7280",
        edgecolor="black",
        linewidth=0.4,
    )
    ax_kp.set_ylabel("Kp", fontsize=12)
    ax_kp.set_title("(c) Planetary Kp Index (3 h)", loc="left", fontsize=12, pad=8)
    ax_kp.set_xlabel("Time (UTC)", fontsize=12)
    ax_kp.set_ylim(0, max(9.2, float(np.nanmax(kp)) + 0.5))
    add_stat_text(ax_kp, f"Max = {kp.max(skipna=True):.1f}\nMin = {kp.min(skipna=True):.1f}")
    add_common_axis_style(ax_kp)

    for axis in axes:
        axis.set_xlim(start_dt, end_dt)
        axis.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18]))
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d\n%H:%M"))
        axis.xaxis.set_minor_locator(mdates.HourLocator(interval=1))

    figure_path = FIG_DIR / f"omni_timeseries_{window.slug}.png"
    fig.savefig(figure_path, dpi=300)
    plt.close(fig)
    return figure_path


def main() -> None:
    configure_matplotlib()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    for window in EVENT_WINDOWS:
        bz_frame = fetch_bz_window(window)
        indices_frame = fetch_index_window(window)
        kp_frame = reduce_kp_to_3hour(indices_frame)

        bz_csv_path = save_bz_csv(bz_frame, window)
        hourly_csv_path, kp_csv_path = save_indices_csv(indices_frame, kp_frame, window)
        figure_path = plot_window(bz_frame, indices_frame, kp_frame, window)

        print(f"[ok] {window.slug}")
        print(f"  bz csv     : {bz_csv_path}")
        print(f"  hourly csv : {hourly_csv_path}")
        print(f"  kp csv     : {kp_csv_path}")
        print(f"  fig        : {figure_path}")


if __name__ == "__main__":
    main()
