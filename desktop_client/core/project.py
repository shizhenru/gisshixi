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
        # 启动时清理上次异常退出遗留的临时文件，避免体积膨胀。
        self.cleanup_runtime()

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
        # 已登记过同一路径则直接返回，避免重复登记（例如对齐结果被多次登记）。
        existing = next((s for s in self.sources if s.path == str(file_path)), None)
        if existing is not None:
            return existing
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
            geometry_checks=metadata.get("geometry_checks", {}),
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

    def cleanup_runtime(self) -> None:
        """清理运行时临时产物，避免软件体积随使用持续膨胀。

        删除 .runtime 下的一次性临时文件/目录，但保留：
        - sources.json、last_project.json（持久配置）
        - raster_preprocess/（栅格对齐结果，供空间分析复用，避免每次重新预处理）

        并移除 path 指向这些临时产物的数据源登记。
        """
        import shutil

        runtime = self.runtime_dir
        if not runtime.exists():
            return
        # 1) 移除指向 .runtime 一次性临时产物的数据源登记（保留 raster_preprocess 对齐结果）
        try:
            root = runtime.resolve()
        except OSError:
            root = runtime.absolute()
        keep_dir = root / "raster_preprocess"
        before = len(self.sources)
        self.sources = [
            s for s in self.sources
            if not (_is_under(Path(s.path), root) and not _is_under(Path(s.path), keep_dir))
        ]
        if len(self.sources) != before:
            self._persist()
        # 2) 删除临时文件，保留持久配置与栅格对齐结果
        keep = {"sources.json", "last_project.json", "raster_preprocess"}
        for child in runtime.iterdir():
            if child.name in keep:
                continue
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
            except OSError:
                continue


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except (OSError, ValueError):
        return False
