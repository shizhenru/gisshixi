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
)


class MapCanvas(QWidget):
    """地图画布：加载真实几何数据时渲染矢量要素；未加载时显示空白占位。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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

    def load_shapes(self, geometry_data: dict):
        """加载真实几何数据用于渲染（shapefile 等）。"""
        self.shapes = geometry_data.get("geometries", [])
        self.data_bbox = geometry_data.get("bbox")
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
        self._view_init = False
        self.update()

    def _build_cache(self):
        """把世界坐标几何预转为 QPolygonF / QPointF，并对大面要素抽稀以加速渲染。"""
        self._polygons = []
        self._polylines = []
        self._points = []
        for shape in self.shapes:
            kind = shape.get("type")
            if kind == "polygon":
                for ring in shape.get("rings", []):
                    poly = QPolygonF([QPointF(x, y) for x, y in ring])
                    if poly.size() > 300:
                        poly = self._decimate(poly, 2)
                    self._polygons.append(poly)
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
        painter.setPen(outline)
        painter.setBrush(QBrush(QColor("#b0d5cc")))
        for poly in self._polygons:
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
            self._panning = False
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.shapes:
            self.reset_view()
        else:
            super().mouseDoubleClickEvent(event)
