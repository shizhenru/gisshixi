"""几何数据 · 地理加权带宽区间探索（桌面端适配器）。

复用 geometry_validation.py 中的原始算法函数（本文件不修改原算法代码）：
在推荐 IoU 阈值下的匹配结果上，按带宽序列批量计算地理加权指标曲线，
并返回每个带宽下按 A 要素 source_id（原始文件行序）对齐的 GW 面 IoU 值，
供客户端在地图上按带宽着色。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from geometry_validation import (  # noqa: E402 - 与原算法同目录，运行时导入
    add_geometry_metrics,
    build_candidates,
    calculate_gw,
    greedy_match,
    load_layer,
    summarize,
)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def _median_or_none(series) -> float | None:
    finite = series.dropna()
    if not len(finite):
        return None
    return float(finite.median())


def run(config, output_path):
    thresholds = sorted({float(value) for value in config["thresholds"]})
    mappings = config["category_mappings"]
    bandwidths = sorted({float(value) for value in config["bandwidths"]})
    bandwidths = [value for value in bandwidths if value > 0]
    if not bandwidths:
        raise ValueError("带宽序列为空或非法")
    data_a, _stats_a = load_layer(
        config["geometry_a"], config["category_field_a"], [m["a_value"] for m in mappings],
        config["projected_crs"], float(config.get("min_area_m2", 0)),
    )
    data_b, _stats_b = load_layer(
        config["geometry_b"], config["category_field_b"], [m["b_value"] for m in mappings],
        config["projected_crs"], float(config.get("min_area_m2", 0)),
    )
    # 与主分析相同的候选构建与推荐阈值选择（评分 = 平衡匹配率 × 面 IoU 中位数）
    summary_rows = []
    match_frames = []
    for mapping in mappings:
        value_a, value_b = str(mapping["a_value"]), str(mapping["b_value"])
        label = mapping.get("label") or f"{value_a}-{value_b}"
        subset_a = data_a[data_a.category_key == value_a].reset_index(drop=True)
        subset_b = data_b[data_b.category_key == value_b].reset_index(drop=True)
        candidates = build_candidates(subset_a, subset_b)
        candidates = candidates[candidates.rect_iou >= min(thresholds)].copy()
        for threshold in thresholds:
            matches = add_geometry_metrics(greedy_match(candidates, threshold), subset_a, subset_b)
            summary = summarize(matches, threshold, len(subset_a), len(subset_b))
            summary.update({"category": label, "a_value": value_a, "b_value": value_b})
            summary_rows.append(summary)
            if not matches.empty:
                matches.insert(0, "category", label)
                matches.insert(1, "a_value", value_a)
                matches.insert(2, "b_value", value_b)
                matches.insert(3, "threshold", threshold)
                match_frames.append(matches)
    summary_frame = pd.DataFrame(summary_rows)
    matches_frame = pd.concat(match_frames, ignore_index=True) if match_frames else pd.DataFrame()
    if summary_frame.empty:
        raise ValueError("所选类别没有可计算的要素")
    overall_rows = []
    for threshold in thresholds:
        category_rows = summary_frame[summary_frame.threshold == threshold]
        match_rows = matches_frame[matches_frame.threshold == threshold] if not matches_frame.empty else matches_frame
        count_a = int(category_rows.a_total.sum())
        count_b = int(category_rows.b_total.sum())
        pairs = int(category_rows.matched_pairs.sum())
        overall_rows.append({
            "threshold": threshold,
            "matched_pairs": pairs,
            "a_total": count_a,
            "b_total": count_b,
            "a_match_rate": pairs / count_a if count_a else 0.0,
            "b_match_rate": pairs / count_b if count_b else 0.0,
            "balanced_match_rate": 2 * pairs / (count_a + count_b) if count_a + count_b else 0.0,
            "median_polygon_iou": float(match_rows.polygon_iou.median()) if len(match_rows) else None,
        })
    overall_frame = pd.DataFrame(overall_rows)
    score = overall_frame.balanced_match_rate.fillna(0) * overall_frame.median_polygon_iou.fillna(0)
    best_threshold = float(overall_frame.loc[score.idxmax(), "threshold"])
    best_matches = matches_frame[matches_frame.threshold == best_threshold].copy() if not matches_frame.empty else pd.DataFrame()

    curve = []
    gw_iou_list = []
    for bandwidth in bandwidths:
        if best_matches.empty:
            curve.append({
                "bandwidth": bandwidth,
                "gw_iou_median": None,
                "gw_area_mae_median": None,
                "gw_centroid_median": None,
                "gw_rmse_median": None,
                "neighbor_median": None,
            })
            gw_iou_list.append({"source_ids": [], "values": []})
            continue
        gw = calculate_gw(best_matches, bandwidth)
        curve.append({
            "bandwidth": bandwidth,
            "gw_iou_median": _median_or_none(gw.GW_polygon_iou),
            "gw_area_mae_median": _median_or_none(gw.GW_relative_area_MAE),
            "gw_centroid_median": _median_or_none(gw.GW_centroid_distance_m),
            "gw_rmse_median": _median_or_none(gw.GW_relative_area_RMSE),
            "neighbor_median": _median_or_none(gw.GW_neighbor_count),
        })
        gw_iou_list.append({
            "source_ids": [int(value) for value in gw.a_source_id.tolist()],
            "values": [None if pd.isna(value) else float(value) for value in gw.GW_polygon_iou.tolist()],
        })

    result = {
        "status": "success",
        "engine": "外接矩形法几何交叉验证 · 带宽探索",
        "message": (
            f"几何带宽探索完成：推荐阈值 {best_threshold:g}，匹配 {int(len(best_matches)):,} 对，"
            f"共 {len(bandwidths)} 个带宽（{min(bandwidths):g} ~ {max(bandwidths):g} m）。"
        ),
        "bandwidths": bandwidths,
        "curve": curve,
        "gw_iou": gw_iou_list,
        "recommended_threshold": best_threshold,
        "config": config,
    }
    Path(output_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def main():
    config_path, output_path = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        run(json.loads(config_path.read_text(encoding="utf-8")), output_path)
    except Exception as exc:  # noqa: BLE001 - 失败以 JSON 错误回传，不抛进程异常
        Path(output_path).write_text(
            json.dumps(
                {"status": "error", "engine": "外接矩形法几何交叉验证 · 带宽探索", "message": str(exc)},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
