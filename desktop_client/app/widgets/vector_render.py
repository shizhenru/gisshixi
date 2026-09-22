"""矢量几何的 Qt 绘制准备：把坐标转成 QPainterPath，并抽稀、按要素合并环。

小地图与拉帘画布共用这一套，避免两边各写一份、行为还不一致。
"""
from __future__ import annotations

import math

from ..qt_compat import QPainterPath, QPointF, QPolygonF, Qt

# 环抽稀：超过阈值顶点的环按步长取点，降低大面要素的渲染点密度
DECIMATE_MIN_POINTS = 300
DECIMATE_STEP = 2

# 单图层参与绘制的最大要素数（与工作台的显示上限一致）
DEFAULT_MAX_FEATURES = 200000


def decimate_ring(ring, step: int = DECIMATE_STEP, threshold: int = DECIMATE_MIN_POINTS):
    """每 step 个点取一个（保留首尾），降低大面要素的渲染点密度。"""
    count = len(ring)
    if count <= threshold:
        return ring
    indices = list(range(0, count, step))
    if indices[-1] != count - 1:
        indices.append(count - 1)
    return [ring[i] for i in indices]


def build_polygon_path(rings) -> QPainterPath | None:
    """把一个要素的所有环合成一条 QPainterPath（外环 + 洞各为独立子路径）。

    不能把环拼成一个 QPolygonF：顶点列表只有一条闭合边，环数一多，环与环之间的
    连接边就成了多余的边，奇偶计数紊乱、洞只挖掉一部分。QPainterPath 的子路径
    彼此独立，配合 OddEvenFill 能把任意多个洞正确镂空，且 contains() 与绘制一致。
    """
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    for ring in rings:
        points = decimate_ring(ring)
        if len(points) < 3:
            continue
        sub = QPainterPath()
        sub.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
        path.addPath(sub)
    return path if path.elementCount() else None


def build_layer_paths(geometries, max_features: int = DEFAULT_MAX_FEATURES):
    """把几何列表转成 (路径列表, 要素号列表)，供按要素填色绘制。

    一个要素一条路径；要素超过 max_features 时只取前若干个。
    点 / 线要素当前不参与面渲染，直接跳过。
    """
    paths, feature_ids = [], []
    for fid, shape in enumerate(geometries[:max_features]):
        if shape.get("type") != "polygon":
            continue
        path = build_polygon_path(shape.get("rings", []))
        if path is None:
            continue
        paths.append(path)
        feature_ids.append(fid)
    return paths, feature_ids


def paths_bounds(paths):
    """全部路径的总外接框 (xmin, ymin, xmax, ymax)；无有效路径返回 None。"""
    if not paths:
        return None
    rect = paths[0].boundingRect()
    for path in paths[1:]:
        rect = rect.united(path.boundingRect())
    if not math.isfinite(rect.width()) or rect.width() <= 0 or rect.height() <= 0:
        return None
    return (rect.left(), rect.top(), rect.right(), rect.bottom())
