from pathlib import Path


def export_report(path: str, result: dict, parameters: dict) -> Path:
    target = Path(path)
    lines = [
        "# 空间数据交叉验证分析报告",
        "",
        "## 分析配置",
        "",
    ]
    for key, value in parameters.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## 结果指标", ""])
    for key, value in result.get("metrics", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## 说明", "", result.get("message", "")])
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def export_data_catalog(path: str, sources) -> Path:
    target = Path(path)
    lines = ["数据集,类型,路径,空间范围,坐标系,状态,记录/分辨率"]
    for source in sources:
        values = [source.name, source.data_type, source.path, source.extent, source.crs, source.status, source.records]
        lines.append(",".join(str(value).replace(",", "，") for value in values))
    target.write_text("\n".join(lines), encoding="utf-8-sig")
    return target
