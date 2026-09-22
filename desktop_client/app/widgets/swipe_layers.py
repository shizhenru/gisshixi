"""拉帘对比的图层准备：把栅格 / 矢量统一到同一坐标系，产出可直接绘制的中间结果。

两种图层最终都表达为「目标坐标系下的范围 + 可绘制内容」：
  栅格 → 目标坐标系下重投影后的 QImage + 其范围
  矢量 → 目标坐标系下重投影后的 QPainterPath 列表 + 每要素填充色 + 图例

准备过程可能很慢（十几万要素重投影、栅格重采样），统一放后台线程执行。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..qt_compat import QColor, QImage
from core.io.readers import read_attributes, read_shapefile_geometry
from core.raster_processing import UNIFIED_NODATA
from core.symbology import (
    auto_colors,
    categorical_colors,
    classify,
    classify_unique,
    FIELD_INFO,
)

from .vector_render import build_layer_paths

# 参与绘制的最大要素数（与工作台小地图一致）
MAX_FEATURES = 200000
# 栅格预览的降采样上限（长边像素）
RASTER_PREVIEW_MAX = 2048


@dataclass
class SwipeLayer:
    """一侧图层的准备结果；error 非空时其余字段无意义。"""

    kind: str = ""                      # "raster" | "vector"
    name: str = ""
    crs: str = ""                       # 目标坐标系（用于两侧一致性说明）
    bounds: tuple | None = None         # (xmin, ymin, xmax, ymax)
    image: QImage | None = None         # 栅格底图
    paths: list = field(default_factory=list)
    feature_ids: list = field(default_factory=list)
    fills: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    colors: list = field(default_factory=list)
    note: str = ""                      # 用于状态栏的补充说明（如重投影）
    error: str = ""


# --------------------------------------------------------------------------- #
# 坐标系
# --------------------------------------------------------------------------- #
def vector_crs(path) -> str:
    """从 .prj 读取矢量的坐标系（WKT 文本）；读不到返回空串。"""
    prj = Path(path).with_suffix(".prj")
    if not prj.exists():
        return ""
    return prj.read_text(encoding="utf-8", errors="replace").strip()


def _same_crs(source, target) -> bool:
    """判断两个 CRS 是否等价。

    ESRI 风格 .prj 与 EPSG 定义经常 equals() 判不等（WKT 方言、轴序不同），
    但实际是同一个坐标系，此时不该做重投影、更不该提示「已重投影」。
    """
    if source.equals(target):
        return True
    try:
        source_epsg, target_epsg = source.to_epsg(), target.to_epsg()
        return source_epsg is not None and source_epsg == target_epsg
    except Exception:  # noqa: BLE001 - 取不到 EPSG 码时按不等处理
        return False


def make_transformer(source_crs: str, target_crs: str):
    """构造坐标转换器；两侧等价或信息不足时返回 None（表示无需转换）。"""
    if not source_crs or not target_crs:
        return None
    try:
        from pyproj import CRS, Transformer
        source, target = CRS.from_user_input(source_crs), CRS.from_user_input(target_crs)
        if _same_crs(source, target):
            return None
        return Transformer.from_crs(source, target, always_xy=True)
    except Exception:  # noqa: BLE001 - 坐标系解析失败时按不转换处理，由上层提示
        return None


def _reproject_ring(ring, transform) -> list:
    """按环重投影：用 numpy 一次算完整环，比逐点 Python 循环快一个量级。"""
    if transform is None or len(ring) < 3:
        return ring
    array = np.asarray(ring, dtype="float64")
    xs, ys = transform.transform(array[:, 0], array[:, 1])
    return list(zip(xs.tolist(), ys.tolist()))


def reproject_geometries(geometries, transform):
    """就地重投影几何中的环 / 折线 / 点坐标。"""
    if transform is None:
        return geometries
    for shape in geometries:
        kind = shape.get("type")
        if kind == "polygon":
            shape["rings"] = [_reproject_ring(ring, transform) for ring in shape.get("rings", [])]
        elif kind == "polyline":
            shape["parts"] = [_reproject_ring(part, transform) for part in shape.get("parts", [])]
        elif kind == "point":
            x, y = shape.get("coords", (0.0, 0.0))
            shape["coords"] = transform.transform(x, y)
        elif kind == "multipoint":
            shape["points"] = [transform.transform(x, y) for x, y in shape.get("points", [])]
    return geometries


# --------------------------------------------------------------------------- #
# 矢量图层
# --------------------------------------------------------------------------- #
def _is_numeric_series(values) -> bool:
    sample = [v for v in values if v is not None][:500]
    return bool(sample) and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in sample
    )


def _classify_colors(values, method, n_classes):
    """按设色方法算每要素的颜色与图例，返回 (labels, colors, indices)。

    文本 / 混合类型字段无法做数值分级（classify 内部要算极差），一律按分类处理，
    否则会直接抛 TypeError。
    """
    if method == "唯一值" or not _is_numeric_series(values):
        labels, indices = classify_unique(values)
        return labels, categorical_colors(len(labels)), indices
    breaks, indices = classify(values, method, n_classes, None)
    count = len(breaks) - 1
    if count <= 0:
        return [], [], indices
    labels = [f"{breaks[i]:.4g}–{breaks[i + 1]:.4g}" for i in range(count)]
    return labels, auto_colors(values, count), indices


def build_vector_layer(path, target_crs, field="", method="自然间断点",
                       n_classes=5, max_features=MAX_FEATURES) -> SwipeLayer:
    """读取矢量、重投影到目标坐标系、建路径并按字段上色。"""
    name = Path(path).stem
    try:
        data = read_shapefile_geometry(str(path), max_records=max_features)
        geometries = data.get("geometries", [])
        if not geometries:
            return SwipeLayer(kind="vector", name=name, error="未解析到面要素（可能不是面数据）")

        source_crs = vector_crs(path)
        transform = make_transformer(source_crs, target_crs)
        note = ""
        if target_crs:
            if not source_crs:
                note = "缺少 .prj，按原坐标叠加"
            elif transform is not None:
                note = "已重投影"
        reproject_geometries(geometries, transform)

        paths, feature_ids = build_layer_paths(geometries, max_features)
        if not paths:
            return SwipeLayer(kind="vector", name=name, error="未解析到面要素（可能不是面数据）")

        rect = paths[0].boundingRect()
        for path_item in paths[1:]:
            rect = rect.united(path_item.boundingRect())
        bounds = (rect.left(), rect.top(), rect.right(), rect.bottom())

        attrs = read_attributes(str(path), limit=max_features)
        fills, labels, colors = _vector_fills(attrs, field, method, n_classes, feature_ids)

        return SwipeLayer(kind="vector", name=name, crs=target_crs, bounds=bounds,
                          paths=paths, feature_ids=feature_ids, fills=fills,
                          labels=labels, colors=colors, note=note)
    except Exception as exc:  # noqa: BLE001 - 失败以错误文本回传
        return SwipeLayer(kind="vector", name=name, error=str(exc))


def _vector_fills(attrs, field, method, n_classes, feature_ids):
    """按字段算每要素填充色；未指定字段或字段不存在时用统一色。"""
    default = QColor("#7fcdbb")
    fields = attrs.get("fields", [])
    if not field or field not in fields:
        return [default] * len(feature_ids), [], []
    index = fields.index(field)
    column = [row[index] if index < len(row) else None for row in attrs.get("rows", [])]
    series = [column[fid] if 0 <= fid < len(column) else None for fid in feature_ids]
    labels, colors, indices = _classify_colors(series, method, n_classes)
    if not colors:
        return [], labels, colors
    fills = [QColor(colors[cls]) if cls is not None and 0 <= cls < len(colors) else default
             for cls in indices]
    while len(fills) < len(feature_ids):
        fills.append(default)
    return fills, labels, [QColor(c) for c in colors]


def vector_fields(path, numeric_only=False, sample=200):
    """矢量的字段名列表（供界面下拉框）；numeric_only=True 时只返回数值字段。"""
    data = read_attributes(str(path), limit=sample)
    fields = data.get("fields", [])
    if not numeric_only:
        return fields
    rows = data.get("rows", [])
    numeric = []
    for index, name in enumerate(fields):
        column = [r[index] for r in rows if index < len(r) and r[index] is not None]
        if column and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in column):
            numeric.append(name)
    return numeric


# --------------------------------------------------------------------------- #
# 栅格图层
# --------------------------------------------------------------------------- #
def _resolve_raster_crs(text):
    """把界面上的坐标系文本转成 rasterio 的 CRS；解析失败返回 None。"""
    if not text:
        return None
    from rasterio.crs import CRS as RasterCRS
    try:
        return RasterCRS.from_string(str(text))
    except Exception:  # noqa: BLE001 - 退回用 pyproj 转 WKT 再构造
        try:
            from pyproj import CRS as PyprojCRS
            return RasterCRS.from_wkt(PyprojCRS.from_user_input(str(text)).to_wkt())
        except Exception:  # noqa: BLE001
            return None


def _raster_crs_equal(first, second) -> bool:
    try:
        from pyproj import CRS as PyprojCRS
        return _same_crs(PyprojCRS.from_user_input(first.to_wkt()),
                         PyprojCRS.from_user_input(second.to_wkt()))
    except Exception:  # noqa: BLE001 - 无法判断时按不等处理（多做一次重投影不影响正确性）
        return False


def _mask_nodata(data, declared):
    """把无效像元统一成 NaN。

    必须同时认三种无效值，否则无效区会被当成真实数据参与灰度拉伸：
      · 源文件声明的 nodata
      · 栅格对齐工具写出的统一 nodata（-9999）
      · 浮点型的 NaN / 无穷
    """
    invalid = ~np.isfinite(data)
    if declared is not None:
        invalid |= (data == declared)
    invalid |= (data == UNIFIED_NODATA)
    if not invalid.any():
        return data
    out = data.astype("float32", copy=True)
    out[invalid] = np.nan
    return out


def build_raster_layer(path, target_crs, max_dim=RASTER_PREVIEW_MAX) -> SwipeLayer:
    """读取栅格、统一无效像元、必要时重投影，最后降采样为显示用 QImage。

    无效像元一律转成 NaN 再参与后续处理，与栅格对齐工具的 UNIFIED_NODATA(-9999)
    约定保持一致，避免对齐结果里大片的 -9999 被当成 0 附近的真实值。
    """
    name = Path(path).stem
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.transform import Affine
        from rasterio.warp import calculate_default_transform, reproject
    except ImportError as exc:
        return SwipeLayer(kind="raster", name=name, error=f"缺少 rasterio：{exc}")

    try:
        with rasterio.open(path) as source:
            if source.count != 1:
                return SwipeLayer(kind="raster", name=name, error="拉帘对比仅支持单波段栅格")
            if source.crs is None:
                return SwipeLayer(kind="raster", name=name, error="栅格缺少坐标系，无法对齐")

            # 先按显示分辨率降采样再重投影：直接对源数据 reproject 会让 GDAL 读全分辨率，
            # 七万×四万的栅格要几十秒；这里只读显示需要的像素量。
            read_scale = min(1.0, max_dim / max(source.width, source.height))
            read_w = max(1, int(source.width * read_scale))
            read_h = max(1, int(source.height * read_scale))
            data = source.read(1, out_shape=(read_h, read_w),
                               resampling=Resampling.average).astype("float32")
            data = _mask_nodata(data, source.nodata)
            read_transform = source.transform * Affine.scale(source.width / read_w,
                                                             source.height / read_h)

            target = _resolve_raster_crs(target_crs) or source.crs
            if _raster_crs_equal(source.crs, target):
                out_data, out_transform, out_w, out_h = data, read_transform, read_w, read_h
                note = ""
            else:
                destination_transform, dst_w, dst_h = calculate_default_transform(
                    source.crs, target, source.width, source.height, *source.bounds)
                scale = min(1.0, max_dim / max(dst_w, dst_h))
                out_w, out_h = max(1, int(dst_w * scale)), max(1, int(dst_h * scale))
                out_transform = destination_transform * Affine.scale(dst_w / out_w, dst_h / out_h)
                # 用源栅格的 nodata 传入，避免把无效值当 0 参与拉伸
                out_data = np.full((out_h, out_w), np.nan, dtype="float32")
                reproject(
                    source=data,
                    destination=out_data,
                    src_transform=read_transform,
                    src_crs=source.crs,
                    src_nodata=float("nan"),
                    dst_transform=out_transform,
                    dst_crs=target,
                    dst_nodata=float("nan"),
                    # 重投影用 bilinear，与栅格对齐工具保持一致
                    resampling=Resampling.bilinear,
                )
                note = "已重投影"
            resolved_crs = target.to_string()

        out_data = _mask_nodata(out_data, None)
        valid = np.isfinite(out_data)
        if not valid.any():
            return SwipeLayer(kind="raster", name=name, error="栅格没有有效像元")
        low, high = np.nanpercentile(out_data[valid], [2, 98])
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            low, high = float(np.nanmin(out_data[valid])), float(np.nanmax(out_data[valid]))
        if high <= low:
            high = low + 1.0
        normalized = np.nan_to_num((out_data - low) / (high - low),
                                   nan=0.0, posinf=1.0, neginf=0.0)
        intensity = np.clip(normalized * 255, 0, 255).astype("uint8")
        alpha = np.where(valid, 255, 0).astype("uint8")
        rgba = np.empty((out_h, out_w, 4), dtype="uint8")
        rgba[..., 0] = intensity
        rgba[..., 1] = intensity
        rgba[..., 2] = intensity
        rgba[..., 3] = alpha
        image = QImage(rgba.data, out_w, out_h, rgba.strides[0],
                       QImage.Format.Format_RGBA8888).copy()

        left, top = out_transform * (0, 0)
        right, bottom = out_transform * (out_w, out_h)
        return SwipeLayer(kind="raster", name=name, crs=resolved_crs,
                          bounds=(left, bottom, right, top), image=image, note=note)
    except Exception as exc:  # noqa: BLE001 - 失败以错误文本回传
        return SwipeLayer(kind="raster", name=name, error=str(exc))


__all__ = [
    "SwipeLayer", "build_raster_layer", "build_vector_layer",
    "vector_crs", "vector_fields", "make_transformer", "reproject_geometries",
    "FIELD_INFO", "MAX_FEATURES",
]
