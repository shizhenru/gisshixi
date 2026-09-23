from dataclasses import dataclass, field
from typing import Any


# --------------------------------------------------------------------------- #
# 属性分析的「配对」约定
#
# 属性 GWR 从 2 个字段扩展到 N(≥2) 个字段后，实际参与计算的是两两配对
# （共 C(N,2) 组）。配对键 / 显示名必须由 R 端、工作台、结果页共用同一套规则，
# 否则跨模块对不上号，因此统一放在这里。
#   配对键   <Y>__vs__<X>   —— 与栅格模式的 pairwise_metrics 键格式一致
#   显示名   <Y> ~ <X>      —— 回归方向：Y 是因变量、X 是自变量
# --------------------------------------------------------------------------- #
PAIR_SEP = "__vs__"


def pair_key(y: str, x: str) -> str:
    return f"{y}{PAIR_SEP}{x}"


def pair_label(y: str, x: str) -> str:
    return f"{y} ~ {x}"


def attribute_pairs(variables: list[str]) -> list[tuple[str, str]]:
    """候选字段 → 两两配对列表。靠前的字段作因变量 Y、靠后的作自变量 X。

    与 gwr_attribute.R / gwr_bandwidth.R 中的配对生成保持同一顺序，
    保证客户端预览的配对列表与算法实际产出的 pairs 一一对应。
    """
    unique = list(dict.fromkeys(v for v in variables if v))
    return [(unique[i], unique[j])
            for i in range(len(unique) - 1)
            for j in range(i + 1, len(unique))]


def parse_pair_key(key: str) -> tuple[str, str]:
    """配对键 → (Y, X)；不是配对键时返回 ("", "")。"""
    y, sep, x = (key or "").partition(PAIR_SEP)
    return (y, x) if sep and y and x else ("", "")


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
    geometry_checks: dict[str, Any] = field(default_factory=dict)

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
    variables: list[str] = field(default_factory=list)
    dependent_variable: str = ""
    independent_variable: str = ""
    kernel: str = "双平方核"
    bandwidth: float = 0.62
    bandwidth_mode: str = "最近邻个数"
    backend: str = "R 属性 GWR"

    def to_dict(self) -> dict[str, Any]:
        variables = list(self.variables)
        if not variables and self.dependent_variable and self.independent_variable:
            variables = [self.dependent_variable, self.independent_variable]
        return {
            "variables": variables,
            # 旧的 x / y 标量继续带出去：结果页指标卡、项目命名、散点渲染
            # 等仍按「第一组配对」读取，保留它们让既有代码不用全部改一遍。
            "dependent_variable": variables[0] if variables else "",
            "independent_variable": variables[1] if len(variables) > 1 else "",
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
    pairwise_metrics: dict = field(default_factory=dict)
    raster_names: list[str] = field(default_factory=list)
    raster_display_names: list[str] = field(default_factory=list)
    local_statistics: dict = field(default_factory=dict)
    output_shp: str = ""
    output_dir: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    # 属性 GWR：多字段两两配对的产出（单字段时代为空，界面按「一个配对」处理）
    pairs: list[dict] = field(default_factory=list)
    metrics_by_pair: dict = field(default_factory=dict)
    shp_by_pair: dict = field(default_factory=dict)
    figures_by_pair: dict = field(default_factory=dict)


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
    pair_key: str = ""      # 该次运行当前查看的配对（多字段时用）
