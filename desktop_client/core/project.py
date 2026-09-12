import json
from pathlib import Path

from .models import DataSource
from .io.readers import read_metadata


class ProjectStore:
    """Project metadata service. Replace the demo list with a real project database later."""

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir or Path(__file__).resolve().parents[1]
        self.runtime_dir = self.project_dir / ".runtime"
        self.runtime_dir.mkdir(exist_ok=True)
        self.sources = [
            DataSource("人口普查2020", "属性数据", "data/人口普查2020.csv", "武汉市行政区", "CGCS2000", "已配准", "2,815 条", "▤"),
            DataSource("NPP-VIIRS-2024", "栅格数据", "data/NPP-VIIRS-2024.tif", "武汉市域", "WGS 84", "待重采样", "500 m", "▦"),
            DataSource("LUCC-武汉", "几何数据", "data/LUCC-武汉.gpkg", "中心城区", "CGCS2000", "已配准", "9,674 要素", "◫"),
        ]

    def add_source(self, path: str) -> DataSource:
        file_path = Path(path)
        suffix = file_path.suffix.lower()
        if suffix in {".csv", ".xlsx", ".xls"}:
            data_type, icon = "属性数据", "▤"
        elif suffix in {".tif", ".tiff", ".img", ".asc"}:
            data_type, icon = "栅格数据", "▦"
        elif suffix in {".gpkg", ".shp", ".geojson", ".json"}:
            data_type, icon = "几何数据", "◫"
        else:
            data_type, icon = "其他数据", "•"
        metadata = read_metadata(str(file_path))
        source = DataSource(
            file_path.stem,
            data_type,
            str(file_path),
            extent=metadata["extent"],
            crs=metadata["crs"],
            status="待检查",
            records=metadata["records"],
            icon=icon,
        )
        self.sources.append(source)
        return source

    def save_config(self, payload: dict) -> Path:
        target = self.runtime_dir / "last_project.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target
