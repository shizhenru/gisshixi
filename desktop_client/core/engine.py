import json
from pathlib import Path
from typing import Any

from .algorithms.python_runner import PythonRunner
from .algorithms.r_runner import RRunner
from .algorithms.raster_runner import RasterTerraRunner
from .models import AnalysisResult


def _attribute_artifacts(payload: dict) -> dict:
    """属性 GWR 的产物清单：结果 SHP + 各类图表路径。"""
    artifacts = {}
    if payload.get("output_shp"):
        artifacts["result_shp"] = payload["output_shp"]
    figures = payload.get("figures") or {}
    for name, path in figures.items():
        if path:
            artifacts[name] = path
    return artifacts


class AnalysisEngine:
    """Language-neutral task dispatcher. Add more runners without changing the UI."""

    def __init__(self, project_dir: Path | None = None, rscript_path: str = ""):
        root = project_dir or Path(__file__).resolve().parents[1]
        self.project_dir = root
        attribute_scripts = root / "core" / "algorithms" / "scripts" / "attribute"
        self.python_runner = PythonRunner(attribute_scripts / "gwr_placeholder.py")
        self.r_runner = RRunner(attribute_scripts / "gwr_placeholder.R", rscript_path)
        self.r_gwr_runner = RRunner(attribute_scripts / "gwr_attribute.R", rscript_path)
        raster_script = root.parent / "栅格数据算法" / "desktop_raster_terra_analysis.R"
        self.raster_runner = RasterTerraRunner(raster_script, rscript_path)
        self.geometry_runner = PythonRunner(root / "core" / "algorithms" / "scripts" / "geometry" / "geometry_validation.py")

    def run(self, parameters: dict[str, Any]) -> AnalysisResult:
        output_path = self.project_dir / ".runtime" / "analysis_result.json"
        output_path.parent.mkdir(exist_ok=True)
        backend = parameters.get("backend", "R 属性 GWR")
        try:
            if parameters.get("analysis_type") == "geometry":
                payload = self.geometry_runner.run(parameters, output_path)
                return AnalysisResult(status=payload.get("status", "success"), engine=payload.get("engine", "外接矩形法"), metrics={k: str(v) for k, v in payload.get("metrics", {}).items()}, message=payload.get("message", ""), output_path=str(output_path), output_dir=payload.get("output_dir", ""), artifacts=payload.get("artifacts", {}))
            if parameters.get("analysis_type") == "raster" or backend.startswith("栅格"):
                payload = self.raster_runner.run(parameters, output_path)
                return AnalysisResult(
                    status=payload.get("status", "success"),
                    engine=payload.get("engine", "R / terra"),
                    metrics={k: str(v) for k, v in payload.get("metrics", {}).items()},
                    message=payload.get("message", "栅格分析完成"),
                    output_path=str(output_path),
                    local_values=payload.get("local_values", []),
                    pairwise_metrics=payload.get("pairwise_metrics", {}),
                    raster_names=payload.get("raster_names", []),
                    raster_display_names=payload.get("raster_display_names", []),
                    local_statistics=payload.get("local_statistics", {}),
                    output_dir=payload.get("output_dir", ""),
                    artifacts=payload.get("artifacts", {}),
                )
            if backend.startswith("混合"):
                return AnalysisResult(
                    status="ready",
                    engine="混合调度接口",
                    message="混合调度接口已预留。后续可在此处串联 Python 预处理、R 建模和统一结果汇总。",
                    output_path=str(output_path),
                )
            if backend == "R 属性 GWR":
                payload = self.r_gwr_runner.run(parameters, output_path)
            elif backend.startswith("R"):
                payload = self.r_runner.run(parameters, output_path)
            else:
                payload = self.python_runner.run(parameters, output_path)
            return AnalysisResult(
                status=payload.get("status", "success"),
                engine=payload.get("engine", backend),
                metrics=payload.get("metrics", {}),
                message=payload.get("message", "分析完成"),
                output_path=str(output_path),
                local_values=payload.get("local_values", []),
                local_columns=payload.get("columns", {}),
                output_shp=payload.get("output_shp") or "",
                # 属性 GWR 会把结果 SHP 写到这个目录，结果页据此显示/打开
                output_dir=payload.get("output_dir") or str(output_path.parent),
                # 结果 SHP 与四张图都算产物：前者列为「输出文件」，后者填进图表页签
                artifacts=_attribute_artifacts(payload),
            )
        except Exception as exc:
            return AnalysisResult(
                status="error",
                engine=backend,
                message=str(exc),
                output_path=str(output_path),
            )
