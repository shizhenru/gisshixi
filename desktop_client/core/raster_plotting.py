from __future__ import annotations

import csv
from pathlib import Path


HIST_COLOR = "#F3BD82"
POINT_COLOR = "#AAA9BC"
LINE_COLOR = "#A83232"
TEXT_COLOR = "#9C4A4A"
KDE_COLOR = "#A99B7C"


def plot_scatter_matrix(data_path: Path, output_path: Path, names: list[str]) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return False

    rows = []
    with data_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                rows.append([float(row[name]) for name in names])
            except (KeyError, TypeError, ValueError):
                continue
    if len(rows) < 3 or len(names) < 2:
        return False

    values = np.asarray(rows, dtype=float)
    size = max(8.0, min(16.0, 2.8 * len(names)))
    figure, axes = plt.subplots(len(names), len(names), figsize=(size, size), squeeze=False)
    for row_index, y_name in enumerate(names):
        for column_index, x_name in enumerate(names):
            axis = axes[row_index][column_index]
            x_values = values[:, column_index]
            y_values = values[:, row_index]
            if row_index == column_index:
                _draw_histogram(axis, x_values, x_name, np)
            elif row_index > column_index:
                _draw_scatter(axis, x_values, y_values, np)
            else:
                _draw_metrics(axis, x_values, y_values, np)
            axis.grid(False)
            if row_index == len(names) - 1:
                axis.set_xlabel(x_name, fontsize=9)
            else:
                axis.tick_params(labelbottom=False)
            if column_index == 0:
                axis.set_ylabel(y_name, fontsize=9)
            else:
                axis.tick_params(labelleft=False)
            axis.tick_params(labelsize=7, colors="#4A4A4A")
    figure.suptitle("Raster pixel scatterplot matrix", fontsize=14)
    figure.tight_layout()
    figure.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(figure)
    return True


def _pair_metrics(x_values, y_values, np):
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
        "finite": finite,
    }


def _draw_scatter(axis, x_values, y_values, np):
    metrics = _pair_metrics(x_values, y_values, np)
    finite = metrics["finite"]
    if not finite.any():
        return
    x_valid = x_values[finite]
    y_valid = y_values[finite]
    axis.scatter(x_valid, y_valid, s=19, alpha=0.65, color=POINT_COLOR, edgecolors="none")
    slope, intercept = np.polyfit(x_valid, y_valid, 1)
    low = min(x_valid.min(), y_valid.min())
    high = max(x_valid.max(), y_valid.max())
    axis.plot([low, high], intercept + slope * np.array([low, high]), color=LINE_COLOR, linewidth=1.8)
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


def _draw_metrics(axis, x_values, y_values, np):
    axis.set_xticks([])
    axis.set_yticks([])
    for spine in axis.spines.values():
        spine.set_visible(False)
    metrics = _pair_metrics(x_values, y_values, np)
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


def _draw_histogram(axis, values, name, np):
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