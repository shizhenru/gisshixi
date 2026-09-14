import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .base import AlgorithmRunner


class RRunner(AlgorithmRunner):
    name = "R"

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
        config_path = output_path.with_name("r_task.json")
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        completed = subprocess.run(
            self._command() + [str(self.script_path), str(config_path), str(output_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "R 算法执行失败")
        return json.loads(output_path.read_text(encoding="utf-8"))
