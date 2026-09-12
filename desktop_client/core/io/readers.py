from pathlib import Path


def read_metadata(path: str) -> dict[str, str]:
    """Return lightweight metadata. Replace branches with real GIS readers later."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        try:
            with file_path.open("r", encoding="utf-8-sig") as stream:
                records = max(0, sum(1 for _ in stream) - 1)
            return {"extent": "待计算", "crs": "属性数据无 CRS", "records": f"{records:,} 条"}
        except (OSError, UnicodeError):
            return {"extent": "待计算", "crs": "待识别", "records": "读取失败"}
    if suffix in {".tif", ".tiff", ".img", ".asc"}:
        return {"extent": "待读取栅格范围", "crs": "待读取", "records": "待读取分辨率"}
    if suffix in {".gpkg", ".shp", ".geojson", ".json"}:
        return {"extent": "待读取矢量范围", "crs": "待读取", "records": "待读取要素数"}
    return {"extent": "待识别", "crs": "待识别", "records": "-"}
