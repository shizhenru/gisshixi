import math
from pathlib import Path


_RASTER_STAT_LABELS = {
    "local_r2": "局部 R²",
    "coefficient": "回归系数",
    "local_corr": "局部相关系数",
    "lme": "LME",
    "lmae": "LMAE",
    "lmre": "LMRE",
    "lrmse": "LRMSE",
}
_RASTER_STAT_KEYS = ("min", "q1", "median", "q3", "max", "mean", "sd")
_MISSING_TEXT = {"", "-", "—", "na", "nan", "none", "null"}


def _numeric_value(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_present(value):
    return _numeric_value(value) is not None or (
        value is not None and str(value).strip().lower() not in _MISSING_TEXT
    )


def _has_raster_statistic(values):
    if not isinstance(values, dict):
        return False
    count = _numeric_value(values.get("count"))
    if count is not None and count <= 0:
        return False
    return any(_numeric_value(values.get(key)) is not None for key in _RASTER_STAT_KEYS)


def _format_report_value(value):
    if not _is_present(value):
        return "—"
    number = _numeric_value(value)
    return f"{number:.6g}" if number is not None else str(value)


def build_report_text(result: dict, parameters: dict) -> str:
    """Build a report without emitting rows for metrics that have no value."""
    lines = [
        "# 空间数据交叉验证分析报告",
        "",
        "## 分析配置",
        "",
    ]
    for key, value in parameters.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## 结果指标", ""])
    for key, value in (result.get("metrics") or {}).items():
        if _is_present(value):
            lines.append(f"- {key}: {_format_report_value(value)}")

    # 属性 GWR 与栅格分析都用这套两两比较结构，标题不能再写死「栅格」
    pairwise_metrics = result.get("pairwise_metrics") or {}
    if pairwise_metrics:
        lines.extend(["", "## 两两比较", ""])
        for pair_name, values in pairwise_metrics.items():
            lines.append(f"### {(values or {}).get('label') or pair_name}")
            for key, value in (values or {}).items():
                if _is_present(value):
                    lines.append(f"- {key}: {_format_report_value(value)}")
            lines.append("")

    local_statistics = result.get("local_statistics") or {}
    if local_statistics:
        lines.extend(["## 局部指标统计", ""])
        for pair_name, statistics in local_statistics.items():
            rows = []
            for key, label in _RASTER_STAT_LABELS.items():
                values = (statistics or {}).get(key) or {}
                if _has_raster_statistic(values):
                    rows.append((label, values))
            if not rows:
                continue
            label = (pairwise_metrics.get(pair_name) or {}).get("label") or pair_name
            lines.extend([
                f"### {label}",
                "",
                "| 局部指标 | 有效数 | 最小值 | Q1 | 中位数 | Q3 | 最大值 | 均值 | 标准差 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ])
            for label, values in rows:
                cells = [
                    label,
                    values.get("count"),
                    values.get("min"),
                    values.get("q1"),
                    values.get("median"),
                    values.get("q3"),
                    values.get("max"),
                    values.get("mean"),
                    values.get("sd"),
                ]
                lines.append("| " + " | ".join(_format_report_value(value) for value in cells) + " |")
            lines.append("")

    lines.extend(["## 说明", "", result.get("message", "")])
    return "\n".join(lines)


def export_report(path: str, result: dict, parameters: dict) -> Path:
    target = Path(path)
    target.write_text(build_report_text(result, parameters), encoding="utf-8")
    return target


def export_data_catalog(path: str, sources) -> Path:
    target = Path(path)
    lines = ["数据集,类型,路径,空间范围,坐标系,状态,记录/分辨率"]
    for source in sources:
        values = [source.name, source.data_type, source.path, source.extent, source.crs, source.status, source.records]
        lines.append(",".join(str(value).replace(",", "，") for value in values))
    target.write_text("\n".join(lines), encoding="utf-8-sig")
    return target
