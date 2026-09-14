"""真实数据读取器（零依赖渐进式）。

每个格式优先用标准库实现真实元数据读取；可选的重依赖（openpyxl / rasterio / geopandas）
在已安装时自动启用，未安装时返回清晰提示而不是抛异常，做到「不装包也能跑，装了包读得更全」。

read_metadata(path) 统一返回：
    extent       空间范围或表格描述（字符串）
    crs          坐标系描述
    records      记录数 / 分辨率（人可读字符串）
    fields       字段（列）名列表
    row_count    数值记录数（表格/要素）
    geometry_type 矢量几何类型（点/线/面…，表格为空）
    preview      前几行样例（list[dict]）
    warnings     提示（如「未安装 rasterio」）
    reader       实际使用的读取器标识
"""
from __future__ import annotations

import csv as _csv
import io
import json as _json
import re
import sqlite3
import struct
import zipfile
from pathlib import Path
from typing import Any

PREVIEW_ROWS = 5

# 常见坐标字段名，用于在表格中推断经纬度并计算范围。
_X_NAMES = {"x", "lon", "lng", "long", "longitude", "经度", "easting", "east", "coordx"}
_Y_NAMES = {"y", "lat", "latitude", "纬度", "northing", "north", "coordy"}

# ESRI Shapefile 几何类型码。
_SHAPE_TYPES = {
    0: "空",
    1: "点",
    3: "线",
    5: "面",
    8: "多点",
    11: "点Z",
    13: "线Z",
    15: "面Z",
    18: "多点Z",
    21: "点M",
    23: "线M",
    25: "面M",
    28: "多点M",
}

# DBF 字段类型码 → 可读说明。
_DBF_TYPES = {
    "C": "字符", "N": "数值", "F": "浮点", "D": "日期",
    "L": "逻辑", "M": "备注", "I": "整数", "B": "双精度",
}


def read_metadata(path: str) -> dict[str, Any]:
    """读取数据文件的真实元数据。任何异常都降级为 fallback，不向上抛。"""
    file_path = Path(path)
    if not file_path.exists():
        return _base("文件不存在", "待识别", "-", "fallback", warnings=["文件不存在"])
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".csv":
            return _read_csv(file_path)
        if suffix in {".json", ".geojson"}:
            return _read_geojson(file_path)
        if suffix in {".xlsx", ".xlsm"}:
            return _read_excel(file_path)
        if suffix == ".xls":
            return _base("表格数据", "属性数据无 CRS", "-", "xls",
                         warnings=["旧版 .xls 需安装 xlrd 或 pandas 后读取"])
        if suffix == ".shp":
            return _read_shapefile(file_path)
        if suffix == ".gpkg":
            return _read_geopackage(file_path)
        if suffix in {".tif", ".tiff"}:
            return _read_raster(file_path)
        if suffix in {".img"}:
            return _base("待读取栅格范围", "待读取", "待读取分辨率", "img",
                         warnings=["ERDAS IMAGINE(.img) 需安装 rasterio 后读取"])
        if suffix == ".asc":
            return _read_esri_ascii(file_path)
    except Exception as exc:  # noqa: BLE001 - 读取失败不应拖垮导入流程
        return _base("待读取", "待识别", "-", "fallback", warnings=[f"读取失败：{exc}"])
    return _base("待识别", "待识别", "-", "fallback", warnings=["暂不支持的文件格式"])


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _base(extent, crs, records, reader, fields=None, row_count=0,
          geometry_type="", preview=None, warnings=None) -> dict[str, Any]:
    return {
        "extent": extent,
        "crs": crs,
        "records": records,
        "fields": fields or [],
        "row_count": row_count,
        "geometry_type": geometry_type,
        "preview": preview or [],
        "warnings": warnings or [],
        "reader": reader,
    }


def _truncate(value, limit: int = 50) -> str:
    if value is None:
        return ""
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _pad(row: list, width: int) -> list:
    return row + [""] * (width - len(row)) if len(row) < width else row


def _missing_warnings(missing: dict[str, int], total: int) -> list[str]:
    if not total:
        return []
    bad = {f: c for f, c in missing.items() if c > 0}
    if not bad:
        return []
    top = sorted(bad.items(), key=lambda kv: -kv[1])[:3]
    return [f"字段「{f}」缺失 {c} 条" for f, c in top]


def _detect_encoding(path: Path) -> str:
    head = path.read_bytes()[:4096]
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
        return "utf-16"
    for enc in ("utf-8", "gb18030"):
        try:
            head.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def _detect_coord_columns(fields: list[str]):
    xi = yi = None
    for i, f in enumerate(fields):
        key = f.strip().lower()
        if key in _X_NAMES and xi is None:
            xi = i
        elif key in _Y_NAMES and yi is None:
            yi = i
    return (xi, yi) if xi is not None and yi is not None else None


def _collect_rows(reader, fields: list[str]) -> tuple[int, dict[str, int], list[dict]]:
    """单趟流式统计：记录数、每字段缺失数、前 PREVIEW_ROWS 行样例。"""
    rows = 0
    missing = {f: 0 for f in fields}
    preview: list[dict] = []
    for line in reader:
        if not line or (len(line) == 1 and line[0] == ""):
            continue
        rows += 1
        row = _pad(list(line), len(fields))
        for i, f in enumerate(fields):
            if _is_missing(row[i]):
                missing[f] += 1
        if len(preview) < PREVIEW_ROWS:
            preview.append({f: _truncate(row[i]) for i, f in enumerate(fields)})
    return rows, missing, preview


# --------------------------------------------------------------------------- #
# CSV（标准库）
# --------------------------------------------------------------------------- #
def _read_csv(path: Path) -> dict[str, Any]:
    encoding = _detect_encoding(path)
    with path.open("r", encoding=encoding, newline="", errors="replace") as stream:
        reader = _csv.reader(stream)
        header = next(reader, None)
        if header is None:
            return _base("空文件", "属性数据无 CRS", "0 条", "csv")
        fields = [h.strip() for h in header if h is not None]
        rows, missing, preview = _collect_rows(reader, fields)

    result = _base("表格数据", "属性数据无 CRS", f"{rows:,} 条", "csv",
                   fields=fields, row_count=rows, preview=preview,
                   warnings=_missing_warnings(missing, rows))
    coord = _detect_coord_columns(fields)
    if coord:
        xs, ys = _extract_coords(path, fields, coord, encoding)
        if xs:
            result["extent"] = (f"经度 {min(xs):.4f}~{max(xs):.4f}"
                                f" · 纬度 {min(ys):.4f}~{max(ys):.4f}")
            result["crs"] = "WGS 84（按经纬度字段推断）"
    return result


def _extract_coords(path: Path, fields: list[str], coord, encoding: str):
    xs, ys = [], []
    with path.open("r", encoding=encoding, newline="", errors="replace") as stream:
        reader = _csv.reader(stream)
        next(reader, None)  # 跳过表头
        for line in reader:
            row = _pad(list(line), len(fields))
            try:
                xs.append(float(row[coord[0]]))
                ys.append(float(row[coord[1]]))
            except (ValueError, TypeError, IndexError):
                continue
    return xs, ys


# --------------------------------------------------------------------------- #
# GeoJSON（标准库）
# --------------------------------------------------------------------------- #
def _read_geojson(path: Path) -> dict[str, Any]:
    data = _json.loads(path.read_text(encoding="utf-8"))
    features: list[dict] = []
    crs = "WGS 84（GeoJSON 默认）"
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        features = data.get("features", []) or []
        crs_member = data.get("crs")
        if crs_member:
            crs = _describe_crs_member(crs_member)
    elif isinstance(data, dict) and data.get("type") == "Feature":
        features = [data]

    if not features:
        return _base("无要素", crs, "0 要素", "geojson")

    fields, preview = _collect_properties(features)
    geom_types = _collect_geometry_types(features)
    extent = _features_bbox(features)
    return _base(extent, crs, f"{len(features):,} 要素", "geojson",
                 fields=fields, row_count=len(features),
                 geometry_type="、".join(geom_types), preview=preview)


def _describe_crs_member(crs_member) -> str:
    name = ""
    if isinstance(crs_member, dict) and "properties" in crs_member:
        props = crs_member["properties"] or {}
        name = props.get("name") or ""
    if isinstance(crs_member, str):
        name = crs_member
    return name or "自定义 CRS"


def _collect_properties(features: list[dict]) -> tuple[list[str], list[dict]]:
    fields: list[str] = []
    seen: set[str] = set()
    preview: list[dict] = []
    for feat in features[:200]:
        props = (feat.get("properties") or {}) if isinstance(feat, dict) else {}
        if not isinstance(props, dict):
            continue
        for key in props:
            if key not in seen:
                seen.add(key)
                fields.append(key)
        if len(preview) < PREVIEW_ROWS:
            preview.append({k: _truncate(v) for k, v in props.items()})
    return fields, preview


def _collect_geometry_types(features: list[dict]) -> list[str]:
    types: list[str] = []
    seen: set[str] = set()
    for feat in features:
        geom = (feat.get("geometry") or {}) if isinstance(feat, dict) else {}
        gtype = geom.get("type") if isinstance(geom, dict) else ""
        if gtype and gtype not in seen:
            seen.add(gtype)
            types.append(gtype)
    return types


def _features_bbox(features: list[dict]) -> str:
    bbox = features[0].get("bbox") if features and isinstance(features[0], dict) else None
    if bbox and len(bbox) >= 4:
        return f"{bbox[0]:.4f}, {bbox[1]:.4f} ~ {bbox[2]:.4f}, {bbox[3]:.4f}"
    acc = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    for feat in features[:500]:
        geom = (feat.get("geometry") or {}) if isinstance(feat, dict) else {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        _geom_bounds(coords, acc)
    if acc[0] == float("inf"):
        return "待计算范围"
    return f"{acc[0]:.4f}, {acc[1]:.4f} ~ {acc[2]:.4f}, {acc[3]:.4f}"


def _geom_bounds(coords, acc) -> None:
    if not coords:
        return
    if isinstance(coords[0], (int, float)):
        x, y = coords[0], coords[1]
        acc[0] = min(acc[0], x)
        acc[1] = min(acc[1], y)
        acc[2] = max(acc[2], x)
        acc[3] = max(acc[3], y)
        return
    for item in coords:
        _geom_bounds(item, acc)


# --------------------------------------------------------------------------- #
# Excel（openpyxl 可选，标准库 zipfile 兜底）
# --------------------------------------------------------------------------- #
def _read_excel(path: Path) -> dict[str, Any]:
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return _read_xlsx_zip(path)
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        iterator = ws.iter_rows(values_only=True)
        header = next(iterator, None)
        if header is None:
            wb.close()
            return _base("空工作表", "属性数据无 CRS", "0 条", "excel")
        fields = [str(h) if h is not None else "" for h in header]
        rows, missing, preview = _collect_rows(iterator, fields)
        wb.close()
        return _base("表格数据", "属性数据无 CRS", f"{rows:,} 条", "excel",
                     fields=fields, row_count=rows, preview=preview,
                     warnings=_missing_warnings(missing, rows))
    except Exception as exc:  # noqa: BLE001
        return _read_xlsx_zip(path, fallback_reason=str(exc))


def _read_xlsx_zip(path: Path, fallback_reason: str = "") -> dict[str, Any]:
    """无 openpyxl 时，按工作簿 XML 的 dimension 读取行列数。"""
    try:
        with zipfile.ZipFile(path) as zf:
            sheet = next((n for n in zf.namelist()
                          if re.match(r"xl/worksheets/sheet\d+\.xml$", n)), None)
            if sheet is None:
                return _base("表格数据", "属性数据无 CRS", "-", "xlsx-zip",
                             warnings=["无法解析工作表；请安装 openpyxl 获取完整信息"])
            xml = zf.read(sheet).decode("utf-8", "replace")
            match = re.search(r'<dimension ref="([^"]+)"', xml)
            rows, cols = _parse_excel_dimension(match.group(1) if match else "A1")
            warnings = ["未安装 openpyxl，仅按工作簿维度读取行列数（不含字段名）"]
            if fallback_reason:
                warnings.append(f"openpyxl 读取失败：{fallback_reason}")
            return _base("表格数据", "属性数据无 CRS", f"{rows:,} 行 · {cols} 列",
                         "xlsx-zip", row_count=rows, warnings=warnings)
    except (zipfile.BadZipFile, KeyError, OSError):
        return _base("表格数据", "属性数据无 CRS", "-", "xlsx-zip",
                     warnings=["无法解析 XLSX 文件"])


def _parse_excel_dimension(ref: str) -> tuple[int, int]:
    match = re.match(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$", ref.strip())
    if not match:
        return 0, 0
    c1 = _col_letters_to_index(match.group(1))
    r1 = int(match.group(2))
    if match.group(3):
        return int(match.group(4)), _col_letters_to_index(match.group(3))
    return r1, c1


def _col_letters_to_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


# --------------------------------------------------------------------------- #
# Shapefile（标准库：.shp 头 + .dbf 属性表 + .prj 投影）
# --------------------------------------------------------------------------- #
def _read_shapefile(path: Path) -> dict[str, Any]:
    shp = path.read_bytes()
    if len(shp) < 100 or struct.unpack_from(">i", shp, 0)[0] != 9994:
        return _base("待读取矢量范围", "待识别", "-", "shapefile",
                     warnings=["无效的 Shapefile 主文件"])

    shape_type = struct.unpack_from("<i", shp, 32)[0]
    xmin, ymin, xmax, ymax = struct.unpack_from("<4d", shp, 36)
    extent = f"{xmin:.4f}, {ymin:.4f} ~ {xmax:.4f}, {ymax:.4f}"
    geometry_type = _SHAPE_TYPES.get(shape_type, f"类型{shape_type}")

    fields, row_count = _read_dbf(path)
    crs = _read_prj(path)

    warnings = []
    if not fields:
        warnings.append("未找到 .dbf 属性表，无法读取字段与记录数")
    result = _base(extent, crs, f"{row_count:,} 要素" if row_count else "-",
                   "shapefile", fields=fields, row_count=row_count,
                   geometry_type=geometry_type, warnings=warnings)
    return result


def _read_dbf(shp_path: Path) -> tuple[list[str], int]:
    dbf = shp_path.with_suffix(".dbf")
    if not dbf.exists():
        return [], 0
    raw = dbf.read_bytes()
    if len(raw) < 33:
        return [], 0
    row_count = struct.unpack_from("<i", raw, 4)[0]
    header_size = struct.unpack_from("<H", raw, 8)[0]
    fields: list[str] = []
    offset = 32
    while offset + 32 <= header_size and raw[offset] != 0x0D:
        name = raw[offset:offset + 11].split(b"\x00")[0].decode("ascii", "replace").strip()
        ftype = chr(raw[offset + 11]) if 0 <= raw[offset + 11] < 256 else "?"
        if name:
            fields.append(name)
        offset += 32
    return fields, row_count


def _read_prj(shp_path: Path) -> str:
    prj = shp_path.with_suffix(".prj")
    if not prj.exists():
        return "无 .prj（未定义坐标系）"
    text = prj.read_text(encoding="utf-8", errors="replace").strip()
    match = re.search(r'(?:PROJCS|GEOGCS|GEOCCS)\[\s*"([^"]+)"', text)
    return match.group(1) if match else "自定义投影（见 .prj）"


# --------------------------------------------------------------------------- #
# Shapefile 几何读取（标准库，供地图可视化）
# --------------------------------------------------------------------------- #
_BASE_SHAPE = {1: 1, 11: 1, 21: 1, 3: 3, 13: 3, 23: 3, 5: 5, 15: 5, 25: 5, 8: 8, 18: 8, 28: 8}


def read_shapefile_geometry(path: str, max_records: int = 20000) -> dict:
    """解析 .shp 的几何坐标，供地图画布渲染。

    返回 {"bbox": (xmin, ymin, xmax, ymax), "shape_type": int,
          "geometries": [{"type": "polygon"/"polyline"/"point"/"multipoint", ...}]}
    仅读取 2D X/Y 坐标，Z/M 数组被忽略。
    """
    file_path = Path(path)
    raw = file_path.read_bytes()
    if len(raw) < 100 or struct.unpack_from(">i", raw, 0)[0] != 9994:
        return {"bbox": None, "shape_type": 0, "geometries": []}
    shape_type = struct.unpack_from("<i", raw, 32)[0]
    bbox = struct.unpack_from("<4d", raw, 36)
    geometries = []
    offset = 100
    while offset + 8 <= len(raw) and len(geometries) < max_records:
        content_len = struct.unpack_from(">i", raw, offset + 4)[0]
        start = offset + 8
        end = start + content_len * 2
        if content_len <= 0 or end > len(raw):
            break
        geom = _parse_record_geometry(raw[start:end])
        if geom:
            geometries.append(geom)
        offset = end
    return {"bbox": bbox, "shape_type": shape_type, "geometries": geometries}


def _parse_record_geometry(content: bytes):
    if len(content) < 4:
        return None
    rec_type = struct.unpack_from("<i", content, 0)[0]
    base = _BASE_SHAPE.get(rec_type)
    if base is None:
        return None
    if base == 1:  # Point
        if len(content) < 20:
            return None
        x, y = struct.unpack_from("<2d", content, 4)
        return {"type": "point", "coords": (x, y)}
    if base == 8:  # MultiPoint
        if len(content) < 40:
            return None
        num_points = struct.unpack_from("<i", content, 36)[0]
        points = []
        off = 40
        for _ in range(num_points):
            if off + 16 > len(content):
                break
            points.append(struct.unpack_from("<2d", content, off))
            off += 16
        return {"type": "multipoint", "points": points}
    # PolyLine (3) / Polygon (5)
    if len(content) < 44:
        return None
    num_parts = struct.unpack_from("<i", content, 36)[0]
    num_points = struct.unpack_from("<i", content, 40)[0]
    parts_off = 44
    points_off = parts_off + 4 * num_parts
    parts = [struct.unpack_from("<i", content, parts_off + 4 * i)[0] for i in range(num_parts)]
    points = []
    for i in range(num_points):
        off = points_off + 16 * i
        if off + 16 > len(content):
            break
        points.append(struct.unpack_from("<2d", content, off))
    rings = _split_parts(points, parts, num_points)
    if base == 5:
        return {"type": "polygon", "rings": rings}
    return {"type": "polyline", "parts": rings}


def _split_parts(points: list, parts: list, num_points: int) -> list:
    """按 parts 索引把连续点集切成多个 ring / part。"""
    indices = list(parts) + [num_points]
    rings = []
    for i in range(len(indices) - 1):
        a, b = indices[i], indices[i + 1]
        if a < b and a < len(points):
            rings.append(points[a:b])
    return rings


# --------------------------------------------------------------------------- #
# GeoPackage（标准库 sqlite3）
# --------------------------------------------------------------------------- #
def _read_geopackage(path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name, srs_id, min_x, min_y, max_x, max_y "
            "FROM gpkg_contents WHERE data_type = 'features' LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return _base("待读取矢量范围", "待识别", "-", "geopackage",
                         warnings=["非 GeoPackage 或缺少 gpkg_contents 表"])
        table_name, srs_id, min_x, min_y, max_x, max_y = row

        geom_col, geometry_type = _gpkg_geometry(cur, table_name)
        crs = _gpkg_crs(cur, srs_id)
        row_count, fields = _gpkg_table(cur, table_name, geom_col)

        extent = "待读取矢量范围"
        if None not in (min_x, min_y, max_x, max_y):
            extent = f"{min_x:.4f}, {min_y:.4f} ~ {max_x:.4f}, {max_y:.4f}"

        warnings = []
        if not fields:
            warnings.append("未读取到字段信息")
        return _base(extent, crs, f"{row_count:,} 要素", "geopackage",
                     fields=fields, row_count=row_count,
                     geometry_type=geometry_type, warnings=warnings)
    except sqlite3.Error as exc:
        return _base("待读取矢量范围", "待识别", "-", "geopackage",
                     warnings=[f"GeoPackage 读取失败：{exc}"])
    finally:
        conn.close()


def _gpkg_geometry(cur, table_name: str) -> tuple[str, str]:
    try:
        cur.execute(
            "SELECT column_name, geometry_type_name FROM gpkg_geometry_columns "
            "WHERE table_name = ?", (table_name,)
        )
        row = cur.fetchone()
        if row:
            return row[0], row[1] or ""
    except sqlite3.Error:
        pass
    return "geom", ""


def _gpkg_crs(cur, srs_id) -> str:
    if srs_id is None:
        return "未定义坐标系"
    try:
        cur.execute(
            "SELECT organization, organization_coordsys_id, srs_name "
            "FROM gpkg_spatial_ref_sys WHERE srs_id = ?", (srs_id,)
        )
        row = cur.fetchone()
        if row:
            return f"{row[0]}:{row[1]} · {row[2]}"
    except sqlite3.Error:
        pass
    return f"EPSG:{srs_id}"


def _gpkg_table(cur, table_name: str, geom_col: str) -> tuple[int, list[str]]:
    try:
        quoted = f'"{table_name}"'
        cur.execute(f"SELECT COUNT(*) FROM {quoted}")
        row_count = cur.fetchone()[0]
        cur.execute(f"SELECT * FROM {quoted} LIMIT 1")
        fields = [d[0] for d in (cur.description or []) if d[0] != geom_col]
        return row_count, fields
    except sqlite3.Error:
        return 0, []


# --------------------------------------------------------------------------- #
# 栅格（rasterio 可选，标准库 TIFF 头兜底）
# --------------------------------------------------------------------------- #
def _read_raster(path: Path) -> dict[str, Any]:
    try:
        import rasterio  # noqa: F401
    except ImportError:
        return _read_tiff_header(path)
    try:
        with rasterio.open(path) as src:
            b = src.bounds
            extent = f"{b.left:.4f}, {b.bottom:.4f} ~ {b.right:.4f}, {b.top:.4f}"
            crs = src.crs.to_string() if src.crs else "无 CRS"
            records = f"{src.width}×{src.height} · {src.count} 波段"
            return _base(extent, crs, records, "rasterio",
                         warnings=[f"分辨率 {src.res[0]:.2f} × {src.res[1]:.2f} m"])
    except Exception as exc:  # noqa: BLE001
        result = _read_tiff_header(path)
        result["warnings"].append(f"rasterio 读取失败：{exc}")
        return result


def _read_tiff_header(path: Path) -> dict[str, Any]:
    """标准库解析 TIFF IFD，得到宽/高/波段；CRS 与范围需 rasterio。"""
    raw = path.read_bytes()
    if len(raw) < 8:
        return _base("待读取栅格范围", "待读取", "-", "tiff", warnings=["无效 TIFF"])
    if raw[:2] == b"II":
        endian = "<"
    elif raw[:2] == b"MM":
        endian = ">"
    else:
        return _base("待读取栅格范围", "待读取", "-", "tiff", warnings=["非 TIFF 文件"])
    if struct.unpack_from(endian + "H", raw, 2)[0] != 42:
        return _base("待读取栅格范围", "待读取", "-", "tiff", warnings=["非 TIFF 文件"])

    width = height = samples = 1
    try:
        ifd_offset = struct.unpack_from(endian + "I", raw, 4)[0]
        n_entries = struct.unpack_from(endian + "H", raw, ifd_offset)[0]
        for i in range(n_entries):
            entry = ifd_offset + 2 + i * 12
            tag, typ, count, value = struct.unpack_from(endian + "HHII", raw, entry)
            if tag == 256:  # ImageWidth
                width = value & 0xFFFF if typ == 3 else value
            elif tag == 257:  # ImageLength
                height = value & 0xFFFF if typ == 3 else value
            elif tag == 277:  # SamplesPerPixel
                samples = value & 0xFFFF if typ == 3 else value
    except (struct.error, IndexError):
        return _base("待读取栅格范围", "待读取", "-", "tiff", warnings=["TIFF 头解析失败"])

    return _base("待读取栅格范围", "待读取", f"{width}×{height} · {samples} 波段", "tiff",
                 warnings=["未安装 rasterio，无法读取 CRS 与真实空间范围/分辨率"])


# --------------------------------------------------------------------------- #
# ESRI ASCII Grid（标准库）
# --------------------------------------------------------------------------- #
def _read_esri_ascii(path: Path) -> dict[str, Any]:
    header: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
        for _ in range(6):
            line = stream.readline()
            if not line:
                break
            key, _, val = line.partition(" ")
            header[key.strip().lower()] = val.strip()
    try:
        ncols = int(header.get("ncols", 0))
        nrows = int(header.get("nrows", 0))
        cellsize = float(header.get("cellsize", 0))
        xll = float(header.get("xllcorner", header.get("xllcenter", 0)))
        yll = float(header.get("yllcorner", header.get("yllcenter", 0)))
        if "xllcenter" in header:
            xll -= cellsize / 2
        if "yllcenter" in header:
            yll -= cellsize / 2
    except ValueError:
        return _base("待读取栅格范围", "待识别", "-", "asc", warnings=["ASCII Grid 头解析失败"])
    extent = f"{xll:.4f}, {yll:.4f} ~ {xll + ncols * cellsize:.4f}, {yll + nrows * cellsize:.4f}"
    return _base(extent, "投影坐标（见 .prj 或用户定义）", f"{ncols}×{nrows} · {cellsize:g} m", "asc")
