"""带宽—指标折线图：横轴带宽、纵轴指标，高亮当前带宽。"""
from ..qt_compat import QBrush, QColor, QPainter, QPen, QPointF, QRectF, QSizePolicy, Qt, QWidget


def _fmt(v):
    if v is None:
        return "—"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.4g}"


class BandwidthCurveCanvas(QWidget):
    """自绘带宽曲线，无第三方依赖。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._points = []          # [(bandwidth, value), ...]
        self._metric_name = "指标"
        self._current_index = None

    def set_data(self, points, metric_name="指标"):
        """points 为 [(bandwidth, value), ...]，value 为 None 表示缺失。"""
        self._points = list(points)
        self._metric_name = metric_name
        self._current_index = None
        self.update()

    def set_current_index(self, index):
        self._current_index = index
        self.update()

    def clear(self):
        self._points = []
        self._current_index = None
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#dce9e4"), 1))
        painter.setBrush(QBrush(QColor("#f7faf9")))
        painter.drawRoundedRect(rect, 6, 6)

        valid = [(b, v) for b, v in self._points if v is not None]
        if not valid:
            painter.setPen(QPen(QColor("#a8b8b4")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "带宽曲线\n生成带宽快照后显示")
            return

        xs = [b for b, _ in valid]
        ys = [v for _, v in valid]
        x_lo, x_hi = min(xs), max(xs)
        y_lo, y_hi = min(ys), max(ys)
        if x_hi <= x_lo:
            x_hi = x_lo + 1.0
        if y_hi <= y_lo:
            y_hi = y_lo + 1.0
        x_pad = (x_hi - x_lo) * 0.05
        y_pad = (y_hi - y_lo) * 0.12
        x_lo -= x_pad
        x_hi += x_pad
        y_lo -= y_pad
        y_hi += y_pad

        left, right, top, bottom = 56, 16, 16, 40
        plot = rect.adjusted(left, top, -right, -bottom)

        def to_px(b, v):
            px = plot.left() + (b - x_lo) / (x_hi - x_lo) * plot.width()
            py = plot.bottom() - (v - y_lo) / (y_hi - y_lo) * plot.height()
            return QPointF(px, py)

        # 边框
        painter.setPen(QPen(QColor("#dfe8e6"), 1))
        painter.drawRect(plot)

        # 折线
        painter.setPen(QPen(QColor("#2d8c7c"), 2))
        pts = [to_px(b, v) for b, v in valid]
        for i in range(1, len(pts)):
            painter.drawLine(pts[i - 1], pts[i])

        # 数据点
        painter.setBrush(QBrush(QColor("#2d8c7c")))
        painter.setPen(QPen(QColor("#ffffff"), 1))
        for i, p in enumerate(pts):
            painter.drawEllipse(p, 3.5, 3.5)

        # 高亮当前带宽
        if self._current_index is not None and 0 <= self._current_index < len(self._points):
            b, v = self._points[self._current_index]
            if v is not None:
                hp = to_px(b, v)
                painter.setPen(QPen(QColor("#f5a623"), 2))
                painter.setBrush(QBrush(QColor("#f5d08a")))
                painter.drawEllipse(hp, 6.0, 6.0)

        # 坐标刻度
        fm = painter.fontMetrics()
        painter.setPen(QPen(QColor("#6b7f7b")))
        painter.drawText(QRectF(plot.left(), plot.bottom() + 4, 70, 18), Qt.AlignmentFlag.AlignLeft, _fmt(x_lo))
        painter.drawText(QRectF(plot.right() - 70, plot.bottom() + 4, 70, 18), Qt.AlignmentFlag.AlignRight, _fmt(x_hi))
        painter.drawText(QRectF(rect.left(), plot.top() - 4, left - 8, 16), Qt.AlignmentFlag.AlignRight, _fmt(y_hi))
        painter.drawText(QRectF(rect.left(), plot.bottom() - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight, _fmt(y_lo))

        # 标题
        painter.setPen(QPen(QColor("#4a5a56")))
        painter.drawText(QRectF(plot.left(), rect.bottom() - 20, plot.width(), 16), Qt.AlignmentFlag.AlignCenter, self._metric_name)
