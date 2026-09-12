from pathlib import Path


SUPPORTED_FORMATS = {
    "属性数据": [".csv", ".xlsx", ".xls"],
    "栅格数据": [".tif", ".tiff", ".img", ".asc"],
    "几何数据": [".gpkg", ".shp", ".geojson", ".json"],
}


def describe_file(path: str) -> dict[str, str]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    data_type = "其他数据"
    for candidate, extensions in SUPPORTED_FORMATS.items():
        if suffix in extensions:
            data_type = candidate
            break
    return {
        "name": file_path.stem,
        "path": str(file_path),
        "suffix": suffix,
        "data_type": data_type,
    }
