import json
from dataclasses import asdict
from pathlib import Path

from .models import DataSource
from .io.readers import read_metadata


def _classify(suffix: str) -> tuple[str, str]:
    """按扩展名归类数据类型并返回对应图标。"""
    if suffix in {".csv", ".xlsx", ".xls", ".xlsm"}:
        return "属性数据", "▤"
    if suffix in {".tif", ".tiff", ".img", ".asc"}:
        return "栅格数据", "▦"
    if suffix in {".gpkg", ".shp", ".geojson", ".json"}:
        return "几何数据", "◫"
    return "其他数据", "•"


def _status_for(metadata: dict) -> str:
    reader = metadata.get("reader", "")
    if reader == "fallback":
        return "读取失败"
    if any(("未安装" in w) or ("需安装" in w) for w in metadata.get("warnings", [])):
        return "需依赖"
    return "已读取"


class ProjectStore:
    """项目元数据服务。数据源列表持久化到 .runtime/sources.json。"""

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir or Path(__file__).resolve().parents[1]
        self.runtime_dir = self.project_dir / ".runtime"
        self.runtime_dir.mkdir(exist_ok=True)
        self._sources_file = self.runtime_dir / "sources.json"
        self.sources = self._load_sources()

    def _load_sources(self) -> list[DataSource]:
        if self._sources_file.exists():
            try:
                data = json.loads(self._sources_file.read_text(encoding="utf-8"))
                # 过滤掉旧的演示数据条目（reader 为空的占位项），只保留真实读取过的数据源
                return [DataSource(**item) for item in data if item.get("reader")]
            except (json.JSONDecodeError, TypeError, KeyError):
                pass
        return []

    def _persist(self) -> None:
        try:
            payload = [asdict(source) for source in self.sources]
            self._sources_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def add_source(self, path: str) -> DataSource:
        file_path = Path(path)
        data_type, icon = _classify(file_path.suffix.lower())
        metadata = read_metadata(str(file_path))
        source = DataSource(
            name=file_path.stem,
            data_type=data_type,
            path=str(file_path),
            extent=metadata.get("extent", "待读取"),
            crs=metadata.get("crs", "待识别"),
            status=_status_for(metadata),
            records=metadata.get("records", "-"),
            icon=icon,
            fields=metadata.get("fields", []),
            geometry_type=metadata.get("geometry_type", ""),
            warnings=metadata.get("warnings", []),
            reader=metadata.get("reader", ""),
        )
        self.sources.append(source)
        self._persist()
        return source

    def remove_source(self, path: str) -> bool:
        """按路径删除一个数据源，返回是否删除成功。"""
        before = len(self.sources)
        self.sources = [s for s in self.sources if s.path != path]
        if len(self.sources) != before:
            self._persist()
            return True
        return False

    def save_config(self, payload: dict) -> Path:
        target = self.runtime_dir / "last_project.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target
