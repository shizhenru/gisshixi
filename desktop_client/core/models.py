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


@dataclass
class AnalysisParameters:
    dependent_variable: str = "夜光遥感"
    independent_variable: str = "人口密度"
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
    engine: str = "演示引擎"
    metrics: dict[str, str] = field(default_factory=lambda: {
        "mae": "8.42",
        "rmse": "13.67",
        "correlation": "0.82",
        "local_r2": "0.74",
        "difference_area": "18.6%",
        "duration": "02:41",
    })
    message: str = "等待运行分析"
    output_path: str = ""
    local_values: list[float] = field(default_factory=lambda: [
        0.86, 0.78, 0.71, 0.64, 0.82, 0.75, 0.69, 0.91, 0.73,
        0.66, 0.59, 0.84, 0.77, 0.62, 0.81, 0.72, 0.68, 0.88,
    ])
