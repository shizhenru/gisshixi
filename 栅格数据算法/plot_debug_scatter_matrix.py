"""Render the generated scatter-matrix debug data for visualization experiments."""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "debug_simulation"
DATA_PATH = DATA_DIR / "scatter_data.csv"
PNG_PATH = DATA_DIR / "scatter_matrix.png"
PDF_PATH = DATA_DIR / "scatter_matrix.pdf"
NAMES = ["reference", "comparison_a", "comparison_b", "comparison_c"]
HIST_COLOR = "#F3BD82"
POINT_COLOR = "#AAA9BC"
LINE_COLOR = "#A83232"
TEXT_COLOR = "#9C4A4A"
KDE_COLOR = "#A99B7C"


def load_values() -> np.ndarray:
    rows = []
    with DATA_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            values = []
            for name in NAMES:
                try:
                    values.append(float(row[name]))
                except (KeyError, TypeError, ValueError):
                    values.append(np.nan)
            rows.append(values)
    return np.asarray(rows, dtype=float)


def pair_metrics(x_values: np.ndarray, y_values: np.ndarray) -> dict[str, float | int]:
    finite = np.isfinite(x_values) & np.isfinite(y_values)
    x_valid = x_values[finite]
    y_valid = y_values[finite]
    difference = y_valid - x_valid
    correlation = np.corrcoef(x_valid, y_valid)[0, 1] if len(x_valid) > 1 else np.nan
    return {
        "r": float(correlation),
        "rmse": float(np.sqrt(np.mean(difference**2))),
        "mae": float(np.mean(np.abs(difference))),
        "me": float(np.mean(difference)),
        "n": int(len(x_valid)),
    }


def draw_scatter_panel(axis, x_values: np.ndarray, y_values: np.ndarray) -> None:
    finite = np.isfinite(x_values) & np.isfinite(y_values)
    if not finite.any():
        return
    x_valid = x_values[finite]
    y_valid = y_values[finite]
    axis.scatter(x_valid, y_valid, s=19, alpha=0.65, color=POINT_COLOR, edgecolors="none")
    slope, intercept = np.polyfit(x_valid, y_valid, 1)
    low = min(x_valid.min(), y_valid.min())
    high = max(x_valid.max(), y_valid.max())
    axis.plot([low, high], intercept + slope * np.array([low, high]), color=LINE_COLOR, linewidth=1.8)
    metrics = pair_metrics(x_values, y_values)
    axis.text(
        0.96,
        0.08,
        f"Pearson's r={metrics['r']:.2f}",
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        color=TEXT_COLOR,
        fontsize=8,
    )


def draw_metric_panel(axis, x_values: np.ndarray, y_values: np.ndarray) -> None:
    axis.set_xticks([])
    axis.set_yticks([])
    for spine in axis.spines.values():
        spine.set_visible(False)
    metrics = pair_metrics(x_values, y_values)
    axis.text(
        0.5,
        0.5,
        "\n".join(
            [
                f"Pearson's r = {metrics['r']:.2f}",
                f"RMSE = {metrics['rmse']:.2f}",
                f"MAE = {metrics['mae']:.2f}",
                f"ME = {metrics['me']:.2f}",
                f"n = {metrics['n']:,}",
            ]
        ),
        transform=axis.transAxes,
        ha="center",
        va="center",
        color=TEXT_COLOR,
        fontsize=9,
        linespacing=1.6,
    )


def draw_histogram_panel(axis, values: np.ndarray, name: str) -> None:
    finite = values[np.isfinite(values)]
    axis.hist(finite, bins=18, color=HIST_COLOR, edgecolor="#6F665F", linewidth=0.6)
    if len(finite) > 1 and np.ptp(finite) > 0:
        grid = np.linspace(finite.min(), finite.max(), 160)
        bandwidth = max(np.std(finite) * len(finite) ** (-1 / 5), np.ptp(finite) / 80)
        density = np.exp(-0.5 * ((grid[:, None] - finite[None, :]) / bandwidth) ** 2).sum(axis=1)
        density /= len(finite) * bandwidth * np.sqrt(2 * np.pi)
        scale = len(finite) * np.ptp(finite) / 18
        axis.plot(grid, density * scale, color=KDE_COLOR, linewidth=1.5)
    axis.set_title(name, fontsize=12, pad=3)


def main() -> None:
    values = load_values()
    if len(values) < 3:
        raise ValueError("需要至少 3 行有效模拟数据")
    size = max(8, min(16, 2.8 * len(NAMES)))
    figure, axes = plt.subplots(len(NAMES), len(NAMES), figsize=(size, size), squeeze=False)
    for row_index, y_name in enumerate(NAMES):
        for column_index, x_name in enumerate(NAMES):
            axis = axes[row_index, column_index]
            x_values = values[:, column_index]
            y_values = values[:, row_index]
            if row_index == column_index:
                draw_histogram_panel(axis, x_values, x_name)
            elif row_index > column_index:
                draw_scatter_panel(axis, x_values, y_values)
            else:
                draw_metric_panel(axis, x_values, y_values)
            axis.grid(False)
            axis.tick_params(labelsize=7, colors="#4A4A4A")
            if row_index == len(NAMES) - 1:
                axis.set_xlabel(x_name, fontsize=9)
            else:
                axis.tick_params(labelbottom=False)
            if column_index == 0:
                axis.set_ylabel(y_name, fontsize=9)
            else:
                axis.tick_params(labelleft=False)
    figure.suptitle("Simulated raster pixel scatterplot matrix", fontsize=14)
    figure.tight_layout()
    figure.savefig(PNG_PATH, dpi=160, bbox_inches="tight")
    figure.savefig(PDF_PATH, bbox_inches="tight")
    plt.close(figure)
    print(f"wrote {PNG_PATH}")
    print(f"wrote {PDF_PATH}")


if __name__ == "__main__":
    main()
