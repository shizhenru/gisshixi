from dataclasses import dataclass, field
from typing import Any


@dataclass
class DataSource:
    name: str
    data_type: str
    path: str
    extent: str = "待读取"
    crs: str = "待识别"
    status: str = "待检查"
    records: str = "-"
    icon: str = "▤"
    fields: list[str] = field(default_factory=list)
    geometry_type: str = ""
    warnings: list[str] = field(default_factory=list)
    reader: str = ""

    def summary(self) -> str:
        """一行人可读的读取结果摘要，用于状态栏提示。"""
        if self.reader == "fallback":
            return f"未读取：{self.name}"
        parts = [f"已读取 {self.name}", self.records]
        if self.fields:
            parts.append(f"{len(self.fields)} 字段")
        if self.geometry_type:
            parts.append(self.geometry_type)
        return " · ".join(parts)


@dataclass
class AnalysisParameters:
    dependent_variable: str = ""
    independent_variable: str = ""
    kernel: str = "双平方核"
    bandwidth: float = 0.62
    bandwidth_mode: str = "自适应带宽"
    distance_metric: str = "投影坐标距离（米）"
    backend: str = "Python 占位算法"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependent_variable": self.dependent_variable,
            "independent_variable": self.independent_variable,
            "kernel": self.kernel,
            "bandwidth": self.bandwidth,
            "bandwidth_mode": self.bandwidth_mode,
            "distance_metric": self.distance_metric,
            "backend": self.backend,
        }


@dataclass
class AnalysisResult:
    status: str = "ready"
    engine: str = "未运行"
    metrics: dict[str, str] = field(default_factory=dict)
    message: str = "等待运行分析"
    output_path: str = ""
    local_values: list[float] = field(default_factory=list)
