"""Parameterized axis-aligned bounding-box geometry cross-validation."""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely import area, box, centroid, distance, intersection, length, make_valid, union


def _sql_literal(value):
    try:
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    except (TypeError, ValueError):
        return "'" + str(value).replace("'", "''") + "'"


def load_layer(path, category_field, category_values, target_crs, min_area, limit=0):
    values_sql = ", ".join(_sql_literal(value) for value in category_values)
    where = f'"{category_field}" IN ({values_sql})'
    frame = gpd.read_file(path, columns=[category_field, "geometry"], engine="pyogrio", where=where)
    if category_field not in frame.columns:
        raise ValueError(f"类别字段不存在：{category_field}")
    if frame.crs is None:
        raise ValueError(f"数据缺少 CRS，无法进行米制计算：{path}")
    original_count = len(frame)
    if limit:
        frame = frame.iloc[: int(limit)].copy()
    null_before = int(frame.geometry.isna().sum())
    empty_before = int(frame.geometry.is_empty.sum())
    invalid_mask = ~frame.geometry.is_valid & frame.geometry.notna()
    invalid_before = int(invalid_mask.sum())
    if invalid_before:
        frame.loc[invalid_mask, "geometry"] = make_valid(frame.loc[invalid_mask].geometry.array)
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    frame = frame.to_crs(target_crs)
    frame["area_m2"] = frame.geometry.area
    frame = frame[frame.area_m2 >= min_area].copy()
    frame["source_id"] = frame.index.astype(np.int64)
    frame["category_key"] = frame[category_field].astype(str)
    frame["perimeter_m"] = frame.geometry.length
    centers = frame.geometry.centroid
    frame["centroid_x_m"] = centers.x
    frame["centroid_y_m"] = centers.y
    bounds = frame.geometry.bounds
    frame[["minx", "miny", "maxx", "maxy"]] = bounds
    frame["bbox_area_m2"] = (frame.maxx - frame.minx) * (frame.maxy - frame.miny)
    frame.reset_index(drop=True, inplace=True)
    stats = {
        "input_features": original_count,
        "processed_features": len(frame),
        "null_geometries": null_before,
        "empty_geometries": empty_before,
        "invalid_geometries_repaired": invalid_before,
        "excluded_after_repair_or_area_filter": original_count - len(frame),
    }
    return frame, stats


def build_candidates(data_a, data_b):
    if data_a.empty or data_b.empty:
        return pd.DataFrame(columns=["a_id", "b_id", "rect_intersection_m2", "rect_iou"])
    boxes_a = gpd.GeoSeries(
        box(data_a.minx.to_numpy(), data_a.miny.to_numpy(), data_a.maxx.to_numpy(), data_a.maxy.to_numpy()),
        index=data_a.index,
        crs=data_a.crs,
    )
    boxes_b = gpd.GeoSeries(
        box(data_b.minx.to_numpy(), data_b.miny.to_numpy(), data_b.maxx.to_numpy(), data_b.maxy.to_numpy()),
        index=data_b.index,
        crs=data_b.crs,
    )
    left, right = boxes_b.sindex.query(boxes_a, predicate="intersects")
    if not len(left):
        return pd.DataFrame(columns=["a_id", "b_id", "rect_intersection_m2", "rect_iou"])
    a = data_a.iloc[left]
    b = data_b.iloc[right]
    width = np.maximum(0.0, np.minimum(a.maxx.to_numpy(), b.maxx.to_numpy()) - np.maximum(a.minx.to_numpy(), b.minx.to_numpy()))
    height = np.maximum(0.0, np.minimum(a.maxy.to_numpy(), b.maxy.to_numpy()) - np.maximum(a.miny.to_numpy(), b.miny.to_numpy()))
    intersection_area = width * height
    union_area = a.bbox_area_m2.to_numpy() + b.bbox_area_m2.to_numpy() - intersection_area
    iou = np.divide(intersection_area, union_area, out=np.zeros_like(intersection_area), where=union_area > 0)
    candidates = pd.DataFrame({
        "a_id": left.astype(np.int64),
        "b_id": right.astype(np.int64),
        "rect_intersection_m2": intersection_area,
        "rect_iou": iou,
    })
    candidates = candidates[candidates.rect_iou > 0].copy()
    candidates.sort_values(
        ["rect_iou", "rect_intersection_m2", "a_id", "b_id"],
        ascending=[False, False, True, True],
        inplace=True,
    )
    candidates.reset_index(drop=True, inplace=True)
    return candidates


def greedy_match(candidates, threshold):
    used_a, used_b, selected = set(), set(), []
    for row in candidates[candidates.rect_iou >= threshold].itertuples(index=False):
        if row.a_id in used_a or row.b_id in used_b:
            continue
        used_a.add(row.a_id)
        used_b.add(row.b_id)
        selected.append((int(row.a_id), int(row.b_id), float(row.rect_intersection_m2), float(row.rect_iou)))
    return pd.DataFrame(selected, columns=["a_id", "b_id", "rect_intersection_m2", "rect_iou"])


def add_geometry_metrics(matches, data_a, data_b):
    if matches.empty:
        return matches
    ids_a = matches.a_id.to_numpy(dtype=np.int64)
    ids_b = matches.b_id.to_numpy(dtype=np.int64)
    geom_a = data_a.geometry.array.take(ids_a)
    geom_b = data_b.geometry.array.take(ids_b)
    area_a = area(geom_a)
    area_b = area(geom_b)
    inter_area = area(intersection(geom_a, geom_b))
    union_area = area(union(geom_a, geom_b))
    perimeter_a = length(geom_a)
    perimeter_b = length(geom_b)
    result = matches.copy()
    result["a_source_id"] = data_a.iloc[ids_a].source_id.to_numpy()
    result["b_source_id"] = data_b.iloc[ids_b].source_id.to_numpy()
    result["a_area_m2"] = area_a
    result["b_area_m2"] = area_b
    result["relative_area_error"] = np.divide(area_b - area_a, area_a, out=np.full_like(area_a, np.nan), where=area_a > 0)
    result["absolute_relative_area_error"] = np.abs(result.relative_area_error)
    result["polygon_intersection_m2"] = inter_area
    result["polygon_union_m2"] = union_area
    result["polygon_iou"] = np.divide(inter_area, union_area, out=np.zeros_like(inter_area), where=union_area > 0)
    result["centroid_distance_m"] = distance(centroid(geom_a), centroid(geom_b))
    result["a_perimeter_m"] = perimeter_a
    result["b_perimeter_m"] = perimeter_b
    result["absolute_relative_perimeter_error"] = np.divide(
        np.abs(perimeter_b - perimeter_a), perimeter_a,
        out=np.full_like(perimeter_a, np.nan), where=perimeter_a > 0,
    )
    result["pair_x_m"] = (
        data_a.iloc[ids_a].centroid_x_m.to_numpy() + data_b.iloc[ids_b].centroid_x_m.to_numpy()
    ) / 2
    result["pair_y_m"] = (
        data_a.iloc[ids_a].centroid_y_m.to_numpy() + data_b.iloc[ids_b].centroid_y_m.to_numpy()
    ) / 2
    result["geometry"] = union(geom_a, geom_b)
    return result


def summarize(matches, threshold, count_a, count_b):
    count = len(matches)
    balanced = 2 * count / (count_a + count_b) if count_a + count_b else 0.0
    median_iou = float(matches.polygon_iou.median()) if count else 0.0
    tradeoff = 2 * balanced * median_iou / (balanced + median_iou) if balanced + median_iou else 0.0
    return {
        "threshold": threshold,
        "matched_pairs": count,
        "a_total": count_a,
        "b_total": count_b,
        "a_match_rate": count / count_a if count_a else 0.0,
        "b_match_rate": count / count_b if count_b else 0.0,
        "balanced_match_rate": balanced,
        "mean_rect_iou": float(matches.rect_iou.mean()) if count else None,
        "median_polygon_iou": median_iou,
        "mean_polygon_iou": float(matches.polygon_iou.mean()) if count else None,
        "median_centroid_distance_m": float(matches.centroid_distance_m.median()) if count else None,
        "median_abs_relative_area_error": float(matches.absolute_relative_area_error.median()) if count else None,
        "median_abs_relative_perimeter_error": float(matches.absolute_relative_perimeter_error.median()) if count else None,
        "tradeoff_score": tradeoff,
    }


def calculate_gw(matches, bandwidth, radius_factor=3.0):
    if matches.empty:
        return matches.copy()
    points = matches[["pair_x_m", "pair_y_m"]].to_numpy(float)
    tree = cKDTree(points)
    signed = matches.relative_area_error.to_numpy(float)
    values = {
        "GW_relative_area_ME": signed,
        "GW_relative_area_MAE": np.abs(signed),
        "GW_polygon_iou": matches.polygon_iou.to_numpy(float),
        "GW_centroid_distance_m": matches.centroid_distance_m.to_numpy(float),
        "GW_abs_relative_perimeter_error": matches.absolute_relative_perimeter_error.to_numpy(float),
    }
    output = {name: np.empty(len(matches), dtype=float) for name in values}
    output["GW_relative_area_RMSE"] = np.empty(len(matches), dtype=float)
    output["GW_neighbor_count"] = np.empty(len(matches), dtype=np.int64)
    for index, point in enumerate(points):
        neighbors = tree.query_ball_point(point, bandwidth * radius_factor)
        delta = points[neighbors] - point
        dist2 = np.einsum("ij,ij->i", delta, delta)
        weights = np.exp(-dist2 / (2 * bandwidth * bandwidth))
        weight_sum = weights.sum()
        for name, source in values.items():
            output[name][index] = np.dot(weights, source[neighbors]) / weight_sum
        output["GW_relative_area_RMSE"][index] = math.sqrt(np.dot(weights, signed[neighbors] ** 2) / weight_sum)
        output["GW_neighbor_count"][index] = len(neighbors)
    result = matches.copy()
    for name, values_array in output.items():
        result[name] = values_array
    return result


def make_3x3_figures(matches, thresholds, figures_dir, crs):
    figures_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    specs = [
        ("polygon_iou", "原始面 IoU", "viridis"),
        ("centroid_distance_m", "质心距离（米）", "plasma"),
        ("absolute_relative_area_error", "面积绝对相对误差", "magma"),
        ("absolute_relative_perimeter_error", "周长绝对相对误差", "inferno"),
    ]
    artifacts = {}
    geo = gpd.GeoDataFrame(matches.copy(), geometry="geometry", crs=crs) if not matches.empty else None
    if geo is not None and len(geo):
        bounds = geo.total_bounds
        pad_x = max((bounds[2] - bounds[0]) * 0.04, 100)
        pad_y = max((bounds[3] - bounds[1]) * 0.04, 100)
    for field, title, cmap in specs:
        fig, axes = plt.subplots(3, 3, figsize=(15, 13), dpi=150)
        fig.subplots_adjust(left=0.03, right=0.88, bottom=0.03, top=0.91, wspace=0.12, hspace=0.18)
        finite = geo[field].replace([np.inf, -np.inf], np.nan).dropna().to_numpy(float) if geo is not None and len(geo) else np.array([])
        if len(finite):
            low, high = np.nanpercentile(finite, [2, 98])
            if not np.isfinite(low) or not np.isfinite(high) or low == high:
                low, high = float(np.nanmin(finite)), float(np.nanmax(finite) or 1.0)
                if low == high:
                    high = low + 1.0
        else:
            low, high = 0.0, 1.0
        for axis, threshold in zip(axes.ravel(), thresholds):
            subset = geo[geo.threshold == threshold] if geo is not None else None
            if subset is not None and len(subset):
                subset.plot(ax=axis, column=field, cmap=cmap, vmin=low, vmax=high, linewidth=0.1, edgecolor="white")
                axis.set_xlim(bounds[0] - pad_x, bounds[2] + pad_x)
                axis.set_ylim(bounds[1] - pad_y, bounds[3] + pad_y)
            else:
                axis.text(0.5, 0.5, "无匹配", transform=axis.transAxes, ha="center", va="center", color="#777777")
            axis.set_aspect("equal")
            axis.set_axis_off()
            axis.set_title(f"矩形 IoU 阈值 = {threshold:g}\n匹配对：{0 if subset is None else len(subset):,}")
        scalar = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=low, vmax=high))
        scalar.set_array([])
        color_axis = fig.add_axes([0.91, 0.2, 0.02, 0.6])
        fig.colorbar(scalar, cax=color_axis, label=title + "（2%–98% 色标）")
        fig.suptitle(f"全部类别综合：{title}", fontsize=17, fontweight="bold")
        target = figures_dir / f"overall_3x3_{field}.png"
        fig.savefig(target, dpi=180)
        plt.close(fig)
        artifacts[field] = str(target)
    return artifacts


def write_report(report_path, config, metadata, overall, category_summary):
    best = metadata["recommended_threshold"]
    best_row = overall[overall.threshold == best].iloc[0]
    mapping_text = "、".join(
        f"{item['a_value']}↔{item['b_value']}（{item.get('label') or '未命名'}）"
        for item in config["category_mappings"]
    )
    lines = [
        "# 外接矩形法几何交叉验证综合报告", "",
        "## 1. 输入与配置", "",
        f"- 几何数据 A：`{config['geometry_a']}`",
        f"- 几何数据 B：`{config['geometry_b']}`",
        f"- A / B 类别字段：`{config['category_field_a']}` / `{config['category_field_b']}`",
        f"- 类别映射：{mapping_text}",
        f"- 计算投影：`{config['projected_crs']}`",
        f"- 最小面积：{float(config.get('min_area_m2', 0)):,.2f} m²",
        f"- 地理加权带宽：{float(config.get('bandwidth_m', 5000)):,.2f} m", "",
        "## 2. 数据质量处理", "",
        f"A 中修复无效几何 {metadata['a_checks']['invalid_geometries_repaired']:,} 个，排除 {metadata['a_checks']['excluded_after_repair_or_area_filter']:,} 个；",
        f"B 中修复无效几何 {metadata['b_checks']['invalid_geometries_repaired']:,} 个，排除 {metadata['b_checks']['excluded_after_repair_or_area_filter']:,} 个。原始 SHP 未被修改。", "",
        "## 3. 综合结果", "",
        f"共分析 {len(config['category_mappings'])} 组类别映射，生成 {metadata['candidate_pairs']:,} 个最低阈值候选对。",
        f"推荐矩形 IoU 阈值为 **{best:g}**；该阈值匹配 {int(best_row.matched_pairs):,} 对，A 匹配率为 {best_row.a_match_rate:.2%}，B 匹配率为 {best_row.b_match_rate:.2%}，平衡匹配率为 {best_row.balanced_match_rate:.2%}。",
        f"匹配对原始面 IoU 中位数为 {best_row.median_polygon_iou if pd.notna(best_row.median_polygon_iou) else float('nan'):.4f}，质心距离中位数为 {best_row.median_centroid_distance_m if pd.notna(best_row.median_centroid_distance_m) else float('nan'):,.2f} m。", "",
        "## 4. 方法说明", "",
        "外接矩形仅用于快速筛选候选对和一对一贪心匹配；面 IoU、面积误差、周长误差及质心距离均使用修复后的原始面几何计算。推荐阈值为当前数据、类别映射和参数条件下的探索性结果。", "",
        "## 5. 输出索引", "",
        "- `tables/overall_threshold_summary.csv`：全部类别综合阈值汇总。",
        "- `tables/category_threshold_summary.csv`：各类别阈值汇总。",
        "- `tables/all_categories_matches.csv`：全部匹配明细。",
        "- `tables/best_threshold_gw_metrics.csv`：推荐阈值地理加权指标。",
        "- `tables/run_metadata.json`：输入、参数、修复统计和运行信息。",
        "- `figures/overall_3x3_*.png`：4张全部类别综合空间图。", "",
        "## 6. 分类规模", "",
    ]
    for row in category_summary[["category", "a_value", "b_value", "a_total", "b_total"]].drop_duplicates().itertuples(index=False):
        lines.append(f"- {row.category}：A={row.a_value}（{int(row.a_total):,}），B={row.b_value}（{int(row.b_total):,}）")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def run(config, output_path):
    started = time.time()
    output_dir = Path(config["output_dir"])
    tables_dir = output_dir / "tables"
    figures_dir = output_dir / "figures"
    report_dir = output_dir / "report"
    tables_dir.mkdir(parents=True, exist_ok=True)
    thresholds = sorted({float(value) for value in config["thresholds"]})
    mappings = config["category_mappings"]
    data_a, stats_a = load_layer(
        config["geometry_a"], config["category_field_a"], [m["a_value"] for m in mappings], config["projected_crs"],
        float(config.get("min_area_m2", 0)), int(config.get("limit_a", 0)),
    )
    data_b, stats_b = load_layer(
        config["geometry_b"], config["category_field_b"], [m["b_value"] for m in mappings], config["projected_crs"],
        float(config.get("min_area_m2", 0)), int(config.get("limit_b", 0)),
    )
    summaries, match_frames = [], []
    category_meta = []
    total_candidates = 0
    for mapping in mappings:
        value_a, value_b = str(mapping["a_value"]), str(mapping["b_value"])
        label = mapping.get("label") or f"{value_a}-{value_b}"
        subset_a = data_a[data_a.category_key == value_a].reset_index(drop=True)
        subset_b = data_b[data_b.category_key == value_b].reset_index(drop=True)
        candidates = build_candidates(subset_a, subset_b)
        candidates = candidates[candidates.rect_iou >= min(thresholds)].copy()
        total_candidates += len(candidates)
        category_meta.append({"label": label, "a_value": value_a, "b_value": value_b, "a_features": len(subset_a), "b_features": len(subset_b), "candidate_pairs": len(candidates)})
        for threshold in thresholds:
            matches = add_geometry_metrics(greedy_match(candidates, threshold), subset_a, subset_b)
            summary = summarize(matches, threshold, len(subset_a), len(subset_b))
            summary.update({"category": label, "a_value": value_a, "b_value": value_b})
            summaries.append(summary)
            if not matches.empty:
                matches.insert(0, "category", label)
                matches.insert(1, "a_value", value_a)
                matches.insert(2, "b_value", value_b)
                matches.insert(3, "threshold", threshold)
                match_frames.append(matches)
    summary_frame = pd.DataFrame(summaries)
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
            "categories": len(category_rows),
            "matched_pairs": pairs,
            "a_total": count_a,
            "b_total": count_b,
            "a_match_rate": pairs / count_a if count_a else 0.0,
            "b_match_rate": pairs / count_b if count_b else 0.0,
            "balanced_match_rate": 2 * pairs / (count_a + count_b) if count_a + count_b else 0.0,
            "median_polygon_iou": float(match_rows.polygon_iou.median()) if len(match_rows) else None,
            "median_centroid_distance_m": float(match_rows.centroid_distance_m.median()) if len(match_rows) else None,
        })
    overall_frame = pd.DataFrame(overall_rows)
    score = overall_frame.balanced_match_rate.fillna(0) * overall_frame.median_polygon_iou.fillna(0)
    best_threshold = float(overall_frame.loc[score.idxmax(), "threshold"])
    best_matches = matches_frame[matches_frame.threshold == best_threshold].copy() if not matches_frame.empty else pd.DataFrame()
    gw = calculate_gw(best_matches, float(config.get("bandwidth_m", 5000)))

    summary_frame.to_csv(tables_dir / "category_threshold_summary.csv", index=False, encoding="utf-8-sig")
    overall_frame.to_csv(tables_dir / "overall_threshold_summary.csv", index=False, encoding="utf-8-sig")
    matches_table = matches_frame.drop(columns=["geometry"], errors="ignore")
    gw_table = gw.drop(columns=["geometry"], errors="ignore")
    matches_table.to_csv(tables_dir / "all_categories_matches.csv", index=False, encoding="utf-8-sig")
    gw_table.to_csv(tables_dir / "best_threshold_gw_metrics.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "geometry_a": config["geometry_a"], "geometry_b": config["geometry_b"],
        "category_field_a": config["category_field_a"], "category_field_b": config["category_field_b"],
        "category_mappings": mappings, "projected_crs": config["projected_crs"],
        "min_area_m2": config.get("min_area_m2", 0), "thresholds": thresholds,
        "bandwidth_m": config.get("bandwidth_m", 5000), "a_checks": stats_a, "b_checks": stats_b,
        "categories": category_meta, "candidate_pairs": total_candidates,
        "recommended_threshold": best_threshold, "elapsed_seconds": time.time() - started,
    }
    (tables_dir / "run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    figure_artifacts = {}
    if config.get("write_figures", True):
        figure_artifacts = make_3x3_figures(matches_frame, thresholds, figures_dir, config["projected_crs"])
    report_path = report_dir / "几何交叉验证综合报告.md"
    if config.get("write_report", True):
        write_report(report_path, config, metadata, overall_frame, summary_frame)
    metadata["elapsed_seconds"] = time.time() - started
    (tables_dir / "run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts = {
        "overall_summary": str(tables_dir / "overall_threshold_summary.csv"),
        "category_summary": str(tables_dir / "category_threshold_summary.csv"),
        "matches": str(tables_dir / "all_categories_matches.csv"),
        "gw_metrics": str(tables_dir / "best_threshold_gw_metrics.csv"),
        "metadata": str(tables_dir / "run_metadata.json"),
    }
    if config.get("write_report", True):
        artifacts["report"] = str(report_path)
    artifacts.update({f"figure_{key}": value for key, value in figure_artifacts.items()})
    result = {
        "status": "success", "engine": "外接矩形法几何交叉验证",
        "message": f"几何交叉验证完成：{len(mappings)} 类，推荐阈值 {best_threshold:g}，用时 {metadata['elapsed_seconds']:.1f} 秒",
        "metrics": {"categories": len(mappings), "candidate_pairs": total_candidates, "recommended_threshold": best_threshold, "matched_pairs": len(best_matches)},
        "output_dir": str(output_dir),
        "artifacts": artifacts,
    }
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    config_path, output_path = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        run(json.loads(config_path.read_text(encoding="utf-8")), output_path)
    except Exception as exc:  # noqa: BLE001
        Path(output_path).write_text(json.dumps({"status": "error", "engine": "外接矩形法几何交叉验证", "message": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
