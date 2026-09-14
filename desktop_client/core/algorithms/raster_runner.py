import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .base import AlgorithmRunner


class RasterTerraRunner(AlgorithmRunner):
    name = "R / terra"

    def __init__(self, script_path: Path, rscript_path: str = ""):
        self.script_path = script_path
        self.rscript_path = rscript_path or shutil.which("Rscript") or ""

    def _command(self) -> list[str]:
        if self.rscript_path:
            return [self.rscript_path]
        python_path = Path(sys.executable).resolve()
        if python_path.parent.name == "gdal":
            conda = python_path.parents[2] / "Scripts" / "conda.exe"
            if conda.exists():
                return [str(conda), "run", "--no-capture-output", "-p", str(python_path.parent), "Rscript"]
        raise FileNotFoundError("未找到 Rscript.exe，请在系统设置中配置 Rscript 路径")

    def run(self, config: dict[str, Any], output_path: Path) -> dict[str, Any]:
        raster_paths = config.get("raster_paths") or []
        if len(raster_paths) < 2:
            raise ValueError("栅格异源同质分析至少需要两个栅格数据集")

        result_dir = output_path.parent / "raster_analysis"
        result_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="spatial_validation_raster_"))
        temp_inputs = temp_dir / "inputs"
        temp_inputs.mkdir()
        safe_inputs = []
        for index, raster_path in enumerate(raster_paths[:2], start=1):
            source = Path(raster_path)
            if not source.exists():
                raise FileNotFoundError(f"栅格输入文件不存在：{source}")
            target = temp_inputs / f"input_{index}{source.suffix.lower()}"
            shutil.copy2(source, target)
            safe_inputs.append(target)
        args = [
            *self._command(),
            str(self.script_path),
            str(safe_inputs[0]),
            str(safe_inputs[1]),
            str(temp_dir),
            str(int(config.get("window_size", 5))),
            str(int(config.get("scatter_max_points", 50000))),
        ]
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        try:
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "栅格 R 算法执行失败")

            result_file = temp_dir / "result.json"
            if not result_file.exists():
                raise RuntimeError("栅格 R 算法未生成 result.json")
            result = json.loads(result_file.read_text(encoding="utf-8"))
            for artifact in temp_dir.iterdir():
                target = result_dir / artifact.name
                if artifact.is_file():
                    shutil.copy2(artifact, target)
            result["output_dir"] = str(result_dir)
            result["stdout"] = completed.stdout[-2000:]
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
