"""Generate reproducible raster-analysis-like data for visualization debugging."""
from __future__ import annotations

import csv
import json
from itertools import combinations
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "debug_simulation"
SEED = 20260918
WIDTH = 80
HEIGHT = 60
WINDOW_SIZE = 5
ZERO_EPSILON = 1e-12
NAMES = ["reference", "comparison_a", "comparison_b", "comparison_c"]


def safe_mean(values: np.ndarray) -> float:
    values = values[np.isfinite(values)]
    return float(values.mean()) if values.size else float("nan")


def safe_median(values: np.ndarray) -> float:
    values = values[np.isfinite(values)]
    return float(np.median(values)) if values.size else float("nan")


def metric_value(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def calculate_pair_metrics(left: np.ndarray, right: np.ndarray) -> dict[str, float | int | None]:
    valid = np.isfinite(left) & np.isfinite(right)
    left_values = left[valid]
    right_values = right[valid]
    difference = left_values - right_values
    correlation = np.corrcoef(left_values, right_values)[0, 1] if len(left_values) >= 2 else np.nan
    relative = np.abs(difference[np.abs(left_values) > ZERO_EPSILON] / left_values[np.abs(left_values) > ZERO_EPSILON])
    return {
        "me": metric_value(safe_mean(difference)),
        "mae": metric_value(safe_mean(np.abs(difference))),
        "mre": metric_value(safe_mean(relative)),
        "rmse": metric_value(float(np.sqrt(np.mean(difference**2)))),
        "correlation": metric_value(float(correlation)),
        "valid_cells": int(len(left_values)),
    }


def local_mean(values: np.ndarray, size: int) -> np.ndarray:
    pad = size // 2
    padded = np.pad(values, pad, mode="edge")
    result = np.zeros_like(values, dtype=float)
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            result[row, column] = padded[row:row + size, column:column + size].mean()
    return result


def calculate_local_metrics(left: np.ndarray, right: np.ndarray) -> dict[str, np.ndarray]:
    difference = left - right
    absolute_difference = np.abs(difference)
    relative_difference = np.divide(
        absolute_difference,
        np.abs(left),
        out=np.full_like(left, np.nan, dtype=float),
        where=np.abs(left) > ZERO_EPSILON,
    )
    local_me = local_mean(difference, WINDOW_SIZE)
    local_mae = local_mean(absolute_difference, WINDOW_SIZE)
    local_mre = local_mean(relative_difference, WINDOW_SIZE)
    local_rmse = np.sqrt(local_mean(difference**2, WINDOW_SIZE))
    local_x = local_mean(right, WINDOW_SIZE)
    local_y = local_mean(left, WINDOW_SIZE)
    local_x2 = local_mean(right**2, WINDOW_SIZE)
    local_y2 = local_mean(left**2, WINDOW_SIZE)
    local_xy = local_mean(left * right, WINDOW_SIZE)
    local_coefficient = np.divide(local_xy, local_x2, out=np.full_like(left, np.nan), where=local_x2 > ZERO_EPSILON)
    residual_ss = local_y2 - 2 * local_coefficient * local_xy + local_coefficient**2 * local_x2
    local_r2 = np.divide(
        local_y2 - residual_ss,
        local_y2,
        out=np.full_like(left, np.nan),
        where=local_y2 > ZERO_EPSILON,
    )
    local_correlation = np.divide(
        local_xy - local_x * local_y,
        np.sqrt(np.maximum(local_x2 - local_x**2, 0) * np.maximum(local_y2 - local_y**2, 0)),
        out=np.full_like(left, np.nan),
        where=(local_x2 - local_x**2 > ZERO_EPSILON) & (local_y2 - local_y**2 > ZERO_EPSILON),
    )
    return {
        "local_ME": local_me,
        "local_MAE": local_mae,
        "local_MRE": local_mre,
        "local_RMSE": local_rmse,
        "local_correlation": np.clip(local_correlation, -1, 1),
        "local_coefficient_no_intercept": local_coefficient,
        "local_R2_no_intercept": np.clip(local_r2, 0, 1),
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rng = np.random.default_rng(SEED)
    y_grid, x_grid = np.mgrid[0:HEIGHT, 0:WIDTH]
    trend = 30 + 0.8 * x_grid + 0.45 * y_grid + 8 * np.sin(x_grid / 9) + 5 * np.cos(y_grid / 8)
    data = {
        "reference": trend + rng.normal(0, 2.0, trend.shape),
        "comparison_a": 1.04 * trend + 3 + rng.normal(0, 5.0, trend.shape),
        "comparison_b": 0.92 * trend - 2 + rng.normal(0, 7.0, trend.shape),
        "comparison_c": 1.12 * trend + 1 + 10 * np.sin((x_grid + y_grid) / 15) + rng.normal(0, 4.0, trend.shape),
    }
    valid_mask = rng.random(trend.shape) > 0.015
    for name in NAMES:
        data[name] = np.where(valid_mask, data[name], np.nan)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    flat_rows = []
    for index in range(WIDTH * HEIGHT):
        row, column = divmod(index, WIDTH)
        flat_rows.append({"row": row, "column": column, **{name: data[name].flat[index] for name in NAMES}})
    write_csv(OUTPUT_DIR / "scatter_data.csv", ["row", "column", *NAMES], flat_rows)

    pairwise_metrics = {}
    for left_name, right_name in combinations(NAMES, 2):
        metrics = calculate_pair_metrics(data[left_name], data[right_name])
        pairwise_metrics[f"{left_name}__vs__{right_name}"] = {
            "left": left_name,
            "right": right_name,
            **metrics,
        }
    pair_rows = [{"pair": key, **value} for key, value in pairwise_metrics.items()]
    write_csv(
        OUTPUT_DIR / "pairwise_metrics.csv",
        ["pair", "left", "right", "me", "mae", "mre", "rmse", "correlation", "valid_cells"],
        pair_rows,
    )

    first_left, first_right = NAMES[:2]
    local_metrics = calculate_local_metrics(data[first_left], data[first_right])
    local_rows = []
    for index in range(WIDTH * HEIGHT):
        row, column = divmod(index, WIDTH)
        local_rows.append({"row": row, "column": column, **{name: values.flat[index] for name, values in local_metrics.items()}})
    write_csv(OUTPUT_DIR / "local_metrics.csv", ["row", "column", *local_metrics], local_rows)

    first_metrics = dict(pairwise_metrics[f"{first_left}__vs__{first_right}"])
    for name, values in local_metrics.items():
        first_metrics[f"{name}_median"] = metric_value(safe_median(values))
    result = {
        "status": "success",
        "engine": "Python debug simulation",
        "message": "可重复的栅格散点图矩阵调试数据",
        "raster_names": NAMES,
        "shape": [HEIGHT, WIDTH],
        "window_size": WINDOW_SIZE,
        "pairwise_metrics": pairwise_metrics,
        "metrics": first_metrics,
        "artifacts": {
            "scatter_data": "scatter_data.csv",
            "pairwise_metrics": "pairwise_metrics.csv",
            "local_metrics": "local_metrics.csv",
            "scatter_matrix": "scatter_matrix.png",
            "scatter_matrix_pdf": "scatter_matrix.pdf",
        },
    }
    (OUTPUT_DIR / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "README.md").write_text(
        "# 栅格可视化调试数据\n\n"
        "运行 `python generate_debug_raster_data.py` 重新生成数据，再运行 `python plot_debug_scatter_matrix.py` 更新图像。\n\n"
        "- `scatter_data.csv`：所有模拟像元值。\n"
        "- `pairwise_metrics.csv`：全部变量两两比较的全局指标。\n"
        "- `local_metrics.csv`：首对变量的窗口局部指标。\n"
        "- `result.json`：模拟客户端结果结构。\n",
        encoding="utf-8",
    )
    print(f"generated {len(flat_rows)} cells in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
