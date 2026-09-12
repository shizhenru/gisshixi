import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .base import AlgorithmRunner


class PythonRunner(AlgorithmRunner):
    name = "Python"

    def __init__(self, script_path: Path):
        self.script_path = script_path

    def run(self, config: dict[str, Any], output_path: Path) -> dict[str, Any]:
        config_path = output_path.with_name("python_task.json")
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(self.script_path), str(config_path), str(output_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Python 算法执行失败")
        return json.loads(output_path.read_text(encoding="utf-8"))
