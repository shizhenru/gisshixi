import json
from pathlib import Path
from typing import Any

from .algorithms.python_runner import PythonRunner
from .algorithms.r_runner import RRunner
from .models import AnalysisResult


class AnalysisEngine:
    """Language-neutral task dispatcher. Add more runners without changing the UI."""

    def __init__(self, project_dir: Path | None = None, rscript_path: str = ""):
        root = project_dir or Path(__file__).resolve().parents[1]
        self.project_dir = root
        stubs = root / "core" / "algorithms" / "stubs"
        self.python_runner = PythonRunner(stubs / "gwr_placeholder.py")
        self.r_runner = RRunner(stubs / "gwr_placeholder.R", rscript_path)

    def run(self, parameters: dict[str, Any]) -> AnalysisResult:
        output_path = self.project_dir / ".runtime" / "analysis_result.json"
        output_path.parent.mkdir(exist_ok=True)
        backend = parameters.get("backend", "Python 占位算法")
        try:
            if backend.startswith("混合"):
                return AnalysisResult(
                    status="ready",
                    engine="混合调度接口",
                    message="混合调度接口已预留。后续可在此处串联 Python 预处理、R 建模和统一结果汇总。",
                    output_path=str(output_path),
                )
            if backend.startswith("R"):
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
            )
        except Exception as exc:
            return AnalysisResult(
                status="error",
                engine=backend,
                message=str(exc),
                output_path=str(output_path),
            )
