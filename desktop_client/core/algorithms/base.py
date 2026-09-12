from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class AlgorithmRunner(ABC):
    name = "未命名算法"

    @abstractmethod
    def run(self, config: dict[str, Any], output_path: Path) -> dict[str, Any]:
        raise NotImplementedError
