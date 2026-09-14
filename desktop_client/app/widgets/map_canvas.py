"""地图画布：加载真实几何数据时渲染矢量要素，支持缩放、平移、复位。"""
from ..qt_compat import (
    QColor,
    QBrush,
    QPainter,
    QPen,
    QPolygonF,
    QPointF,
    QSizePolicy,
    Qt,
    QTransform,
    QWidget,
    Signal,
)
from .data_select import MIME_SOURCE_PATH


class MapCanvas(QWidget):
    """地图画布：加载真实几何数据时渲染矢量要素；未加载时显示空白占位。"""

    sourceDropped = Signal(str)
    featureClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(True)
        self.shapes = []
        self.data_bbox = None
        self._view_init = False
        self._center_x = 0.0
        self._center_y = 0.0
        self._scale = 1.0
        self._panning = False
        self._pan_start = None
        self._polygons = []
        self._polylines = []
        self._points = []
        self._polygon_feature_ids = []
        self._feature_fills = []
        self._highlight_index = None
        self._press_pos = None

    def load_shapes(self, geometry_data: dict):
        """加载真实几何数据用于渲染（shapefile 等）。"""
        self.shapes = geometry_data.get("geometries", [])
        self.data_bbox = geometry_data.get("bbox")
        self._feature_fills = []
        self._highlight_index = None
        self._build_cache()
        self._view_init = False
        self.update()

    def clear(self):
        """清空已加载的几何数据，回到空白占位状态。"""
        self.shapes = []
        self.data_bbox = None
        self._polygons = []
        self._polylines = []
        self._points = []
        self._polygon_feature_ids = []
        self._feature_fills = []
        self._highlight_index = None
        self._view_init = False
        self.update()

    def set_feature_colors(self, colors):
        """设置每个要素的填充色（与 self.shapes 对齐，元素为 QColor 或 None）。"""
        self._feature_fills = list(colors) if colors else []
        self.update()

    def highlight_feature(self, index):
        """高亮指定要素索引（index 与 self.shapes 对齐），None 表示取消。"""
        self._highlight_index = index
        self.update()

    def _build_cache(self):
        """把世界坐标几何预转为 QPolygonF / QPointF，并对大面要素抽稀以加速渲染。"""
        self._polygons = []
        self._polylines = []
        self._points = []
        self._polygon_feature_ids = []
        for fid, shape in enumerate(self.shapes):
            kind = shape.get("type")
            if kind == "polygon":
                for ring in shape.get("rings", []):
                    poly = QPolygonF([QPointF(x, y) for x, y in ring])
                    if poly.size() > 300:
                        poly = self._decimate(poly, 2)
                    self._polygons.append(poly)
                    self._polygon_feature_ids.append(fid)
            elif kind == "polyline":
                for part in shape.get("parts", []):
                    self._polylines.append(QPolygonF([QPointF(x, y) for x, y in part]))
            elif kind == "point":
                self._points.append(QPointF(*shape.get("coords", (0.0, 0.0))))
            elif kind == "multipoint":
                for p in shape.get("points", []):
                    self._points.append(QPointF(*p))

    @staticmethod
    def _decimate(poly: QPolygonF, step: int) -> QPolygonF:
        """每 step 个点取一个（保留首尾），降低大面要素的渲染点密度。"""
        n = poly.size()
        if n <= step:
            return poly
        indices = list(range(0, n, step))
        if indices[-1] != n - 1:
            indices.append(n - 1)
        return QPolygonF([poly[i] for i in indices])

    def _fit(self, rect):
        xmin, ymin, xmax, ymax = self.data_bbox
        if xmax <= xmin or ymax <= ymin:
            return
        self._scale = min(rect.width() / (xmax - xmin), rect.height() / (ymax - ymin))
        self._center_x = (xmin + xmax) / 2
        self._center_y = (ymin + ymax) / 2
        self._view_init = True

    def _screen_to_world(self, pos):
        rect = self.rect().adjusted(1, 1, -1, -1)
        if not self._view_init:
            self._fit(rect)
        cx = rect.center().x()
        cy = rect.center().y()
        scale = self._scale
        wx = (pos.x() - cx) / scale + self._center_x
        wy = (cy - pos.y()) / scale + self._center_y
        return QPointF(wx, wy)

    def _feature_at(self, pos):
        if not self.shapes or not self.data_bbox:
            return None
        wp = self._screen_to_world(pos)
        for i, poly in enumerate(self._polygons):
            if poly.containsPoint(wp, Qt.FillRule.OddEvenFill):
                if i < len(self._polygon_feature_ids):
                    return self._polygon_feature_ids[i]
                return None
        return None

    def _paint_data(self, painter, rect):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#dce9e4"), 1))
        painter.setBrush(QBrush(QColor("#eef5f1")))
        painter.drawRoundedRect(rect, 6, 6)
        if not self.data_bbox:
            return
        if not self._view_init:
            self._fit(rect)
        cx = rect.center().x()
        cy = rect.center().y()
        scale = self._scale
        # world -> screen：先缩放（y 翻转），再平移。用 QTransform 一次性完成。
        transform = QTransform(scale, 0, 0, -scale, cx - self._center_x * scale, cy + self._center_y * scale)

        painter.save()
        painter.setTransform(transform)
        outline = QPen(QColor("#2d8c7c"))
        outline.setCosmetic(True)
        default_fill = QColor("#b0d5cc")
        for i, poly in enumerate(self._polygons):
            fid = self._polygon_feature_ids[i] if i < len(self._polygon_feature_ids) else -1
            if self._highlight_index is not None and fid == self._highlight_index:
                hl = QPen(QColor("#f5a623"))
                hl.setCosmetic(True)
                hl.setWidthF(2.5)
                painter.setPen(hl)
                painter.setBrush(QBrush(QColor("#f5d08a")))
            else:
                painter.setPen(outline)
                color = default_fill
                if self._feature_fills and 0 <= fid < len(self._feature_fills):
                    color = self._feature_fills[fid] or default_fill
                painter.setBrush(QBrush(color))
            painter.drawPolygon(poly)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        line_pen = QPen(QColor("#e78338"))
        line_pen.setCosmetic(True)
        line_pen.setWidth(2)
        painter.setPen(line_pen)
        for line in self._polylines:
            painter.drawPolyline(line)
        painter.restore()

        painter.setPen(QPen(QColor("#d86659"), 1))
        painter.setBrush(QBrush(QColor("#d86659")))
        for point in self._points:
            sp = transform.map(point)
            painter.drawEllipse(sp, 4, 4)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if self.shapes:
            self._paint_data(painter, rect)
        else:
            self._paint_empty(painter, rect)

    def _paint_empty(self, painter, rect):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#dce9e4"), 1))
        painter.setBrush(QBrush(QColor("#f7faf9")))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QPen(QColor("#a8b8b4")))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "未导入空间数据")

    def zoom_in(self):
        self._zoom(1.25)

    def zoom_out(self):
        self._zoom(1 / 1.25)

    def reset_view(self):
        self._view_init = False
        self.update()

    def _zoom(self, factor):
        if not self.shapes or not self.data_bbox:
            return
        rect = self.rect().adjusted(1, 1, -1, -1)
        if not self._view_init:
            self._fit(rect)
        self._scale *= factor
        self.update()

    def wheelEvent(self, event):
        if not self.shapes or not self.data_bbox:
            return
        rect = self.rect().adjusted(1, 1, -1, -1)
        if not self._view_init:
            self._fit(rect)
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        cx = rect.center().x()
        cy = rect.center().y()
        sx = event.position().x()
        sy = event.position().y()
        wx = self._center_x + (sx - cx) / self._scale
        wy = self._center_y - (sy - cy) / self._scale
        self._scale *= factor
        self._center_x = wx - (sx - cx) / self._scale
        self._center_y = wy + (sy - cy) / self._scale
        self.update()

    def mousePressEvent(self, event):
        if self.shapes and event.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_start = event.position()
            self._press_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            pos = event.position()
            self._center_x -= (pos.x() - self._pan_start.x()) / self._scale
            self._center_y += (pos.y() - self._pan_start.y()) / self._scale
            self._pan_start = pos
            self.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning:
            clicked = False
            if self._press_pos is not None:
                delta = event.position() - self._press_pos
                if delta.manhattanLength() < 4:
                    clicked = True
            self._panning = False
            self._pan_start = None
            self._press_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if clicked:
                fid = self._feature_at(event.position())
                if fid is not None:
                    self.featureClicked.emit(fid)
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.shapes:
            self.reset_view()
        else:
            super().mouseDoubleClickEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_SOURCE_PATH):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_SOURCE_PATH):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME_SOURCE_PATH):
            path = bytes(event.mimeData().data(MIME_SOURCE_PATH)).decode("utf-8")
            self.sourceDropped.emit(path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
