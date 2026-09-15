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
    bandwidth_mode: str = "最近邻个数"
    backend: str = "R 属性 GWR"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependent_variable": self.dependent_variable,
            "independent_variable": self.independent_variable,
            "kernel": self.kernel,
            "bandwidth": self.bandwidth,
            "bandwidth_mode": self.bandwidth_mode,
            "backend": self.backend,
        }


@dataclass
class RasterAnalysisParameters:
    window_size: int = 5
    resampling: str = "bilinear"
    zero_epsilon: float = 1e-12
    scatter_max_points: int = 50000
    write_local_rasters: bool = True
    write_scatter_plot: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_size": self.window_size,
            "resampling": self.resampling,
            "zero_epsilon": self.zero_epsilon,
            "scatter_max_points": self.scatter_max_points,
            "write_local_rasters": self.write_local_rasters,
            "write_scatter_plot": self.write_scatter_plot,
        }


@dataclass
class AnalysisResult:
    status: str = "ready"
    engine: str = "未运行"
    metrics: dict[str, str] = field(default_factory=dict)
    message: str = "等待运行分析"
    output_path: str = ""
    local_values: list[float] = field(default_factory=list)
    local_columns: dict = field(default_factory=dict)
    output_shp: str = ""
    output_dir: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass
class AnalysisRun:
    """一次分析运行（会话工作区中的临时项目）。"""
    name: str = ""
    parameters: dict = field(default_factory=dict)
    result: AnalysisResult = field(default_factory=AnalysisResult)
    shp_path: str = ""
    symbology_field: str = ""
    symbology_method: str = "自然间断点"
    symbology_classes: int = 5
