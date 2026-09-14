"""散点图画布：正方形等比例 X vs Y 散点 + y=x 线 + 回归线 + 统计标注。

约定与原算法一致：误差 = Y - X。点击某个点发出 pointClicked(点索引)。
"""
from ..qt_compat import (
    QBrush,
    QColor,
    QPainter,
    QPen,
    QPointF,
    QRectF,
    QSizePolicy,
    Qt,
    QWidget,
    Signal,
)


def _fmt(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.4g}"


class ScatterCanvas(QWidget):
    """自绘散点图，无第三方依赖。正方形等比例坐标，y=x 呈 45°。"""

    pointClicked = Signal(int)
    blankClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(340, 340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._xs = []
        self._ys = []
        self._x_label = "X"
        self._y_label = "Y"
        self._stats = None
        self._points_px = []
        self._highlight_point = None
        self._view_lo = None
        self._view_hi = None
        self._panning = False
        self._press_pos = None
        self._dragged = False
        self._eff_lo = None
        self._eff_hi = None
        self._plot_side = 0

    def set_data(self, xs, ys, x_label="X", y_label="Y"):
        self._xs = list(xs)
        self._ys = list(ys)
        self._x_label = x_label
        self._y_label = y_label
        self._stats = self._compute_stats(self._xs, self._ys)
        self._view_lo = None
        self._view_hi = None
        self.update()

    def clear(self):
        self._xs = []
        self._ys = []
        self._stats = None
        self._points_px = []
        self._highlight_point = None
        self._view_lo = None
        self._view_hi = None
        self.update()

    def highlight_point(self, index):
        """高亮指定索引的点（与散点数据对齐），None 表示取消。"""
        self._highlight_point = index
        self.update()

    @staticmethod
    def _compute_stats(x, y):
        n = len(x)
        if n < 2:
            return None
        mx = sum(x) / n
        my = sum(y) / n
        d = [yi - xi for xi, yi in zip(x, y)]
        me = sum(d) / n
        mae = sum(abs(v) for v in d) / n
        rmse = (sum(v * v for v in d) / n) ** 0.5
        cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        vx = sum((xi - mx) ** 2 for xi in x)
        vy = sum((yi - my) ** 2 for yi in y)
        r = cov / ((vx * vy) ** 0.5) if vx > 0 and vy > 0 else 0.0
        b = cov / vx if vx > 0 else 0.0
        a = my - b * mx
        return {"me": me, "mae": mae, "rmse": rmse, "r": r, "a": a, "b": b}

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setPen(QPen(QColor("#dce9e4"), 1))
        painter.setBrush(QBrush(QColor("#f7faf9")))
        painter.drawRoundedRect(rect, 6, 6)

        self._points_px = []

        if not self._xs or len(self._xs) < 2 or self._stats is None:
            painter.setPen(QPen(QColor("#a8b8b4")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "散点图\n加载数据后显示 X vs Y")
            return

        # 公共坐标范围（x/y 等比例，保证 y=x 呈 45°）
        data_lo = min(min(self._xs), min(self._ys))
        data_hi = max(max(self._xs), max(self._ys))
        if data_hi <= data_lo:
            data_hi = data_lo + 1.0
        if self._view_lo is None:
            pad = (data_hi - data_lo) * 0.06
            lo = data_lo - pad
            hi = data_hi + pad
        else:
            lo = self._view_lo
            hi = self._view_hi

        left, right, top, bottom = 50, 18, 18, 44
        avail_w = rect.width() - left - right
        avail_h = rect.height() - top - bottom
        side = max(60, min(avail_w, avail_h))
        plot = QRectF(rect.left() + left, rect.top() + top, side, side)
        self._eff_lo = lo
        self._eff_hi = hi
        self._plot_side = side

        def to_px(x, y):
            px = plot.left() + (x - lo) / (hi - lo) * plot.width()
            py = plot.bottom() - (y - lo) / (hi - lo) * plot.height()
            return QPointF(px, py)

        # 绘图区边框
        painter.setPen(QPen(QColor("#dfe8e6"), 1))
        painter.drawRect(plot)

        # y=x 线（45°）
        painter.setPen(QPen(QColor("#8a9a96"), 1.4, Qt.PenStyle.DashLine))
        p_line_hi = to_px(hi, hi)
        painter.drawLine(to_px(lo, lo), p_line_hi)
        painter.setPen(QPen(QColor("#8a9a96")))
        painter.drawText(QPointF(p_line_hi.x() - 28, p_line_hi.y() - 6), "y=x")

        # 回归红线
        a, b = self._stats["a"], self._stats["b"]
        painter.setPen(QPen(QColor("#c0392b"), 1.6))
        painter.drawLine(to_px(lo, a + b * lo), to_px(hi, a + b * hi))

        # 数据点 + 记录屏幕坐标用于命中检测
        painter.setPen(QPen(QColor("#2d8c7c"), 1))
        painter.setBrush(QBrush(QColor(45, 140, 124, 150)))
        for x, y in zip(self._xs, self._ys):
            p = to_px(x, y)
            self._points_px.append(p)
            if lo <= x <= hi and lo <= y <= hi:
                painter.drawEllipse(p, 3.0, 3.0)

        # 高亮点（由地图要素点击反向定位）
        if self._highlight_point is not None and 0 <= self._highlight_point < len(self._points_px):
            hp = self._points_px[self._highlight_point]
            painter.setPen(QPen(QColor("#f5a623"), 2))
            painter.setBrush(QBrush(QColor("#f5d08a")))
            painter.drawEllipse(hp, 6.0, 6.0)

        # 刻度（x/y 共享范围，端点值相同）
        fm = painter.fontMetrics()
        lo_text = _fmt(lo)
        hi_text = _fmt(hi)
        painter.setPen(QPen(QColor("#6b7f7b")))
        painter.drawText(QPointF(plot.left(), plot.bottom() + fm.height() + 4), lo_text)
        painter.drawText(QPointF(plot.right() - fm.horizontalAdvance(hi_text), plot.bottom() + fm.height() + 4), hi_text)
        painter.drawText(QPointF(plot.left() - fm.horizontalAdvance(lo_text) - 6, plot.bottom()), lo_text)
        painter.drawText(QPointF(plot.left() - fm.horizontalAdvance(hi_text) - 6, plot.top() + fm.ascent()), hi_text)

        # X 轴标题
        x_title = self._x_label
        painter.drawText(QPointF(plot.center().x() - fm.horizontalAdvance(x_title) / 2, rect.bottom() - 6), x_title)

        # Y 轴标题（旋转）
        painter.save()
        painter.translate(16, plot.center().y())
        painter.rotate(-90)
        y_title = self._y_label
        painter.drawText(QPointF(-fm.horizontalAdvance(y_title) / 2, 0), y_title)
        painter.restore()

        # 统计标注（左上角，白底）
        stats = self._stats
        lines = [
            f"R = {stats['r']:.3f}",
            f"RMSE = {_fmt(stats['rmse'])}",
            f"MAE = {_fmt(stats['mae'])}",
            f"ME = {_fmt(stats['me'])}",
        ]
        width = max(fm.horizontalAdvance(line) for line in lines) + 16
        height = fm.height() * len(lines) + 12
        label_rect = QRectF(plot.left() + 8, plot.top() + 8, width, height)
        painter.setPen(QPen(QColor("#dce9e4"), 1))
        painter.setBrush(QBrush(QColor(255, 255, 255, 215)))
        painter.drawRoundedRect(label_rect, 4, 4)
        painter.setPen(QPen(QColor("#2b3a36")))
        ty = label_rect.top() + fm.ascent() + 4
        for line in lines:
            painter.drawText(QPointF(label_rect.left() + 8, ty), line)
            ty += fm.height()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._press_pos = event.position()
            self._dragged = False
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._press_pos is not None:
            pos = event.position()
            dx = pos.x() - self._press_pos.x()
            dy = pos.y() - self._press_pos.y()
            if not self._dragged:
                if abs(dx) + abs(dy) < 4:
                    return
                self._dragged = True
            self._pan_incremental(dx, dy)
            self._press_pos = pos
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            if not self._dragged and self._points_px:
                self._handle_click(event.position())
            self._press_pos = None
            self._dragged = False
        else:
            super().mouseReleaseEvent(event)

    def _handle_click(self, pos):
        best_i, best_d = -1, 9.0
        for i, p in enumerate(self._points_px):
            d = ((pos.x() - p.x()) ** 2 + (pos.y() - p.y()) ** 2) ** 0.5
            if d < best_d:
                best_d = d
                best_i = i
        if best_i >= 0:
            self.pointClicked.emit(best_i)
        else:
            self.blankClicked.emit()

    def _pan_incremental(self, dx, dy):
        if self._eff_lo is None or self._plot_side <= 0:
            return
        if self._view_lo is None:
            self._view_lo = self._eff_lo
            self._view_hi = self._eff_hi
        span = self._view_hi - self._view_lo
        data_per_px = span / self._plot_side
        shift = -dx * data_per_px + dy * data_per_px
        self._view_lo += shift
        self._view_hi += shift
        self.update()

    def wheelEvent(self, event):
        if not self._xs or len(self._xs) < 2:
            super().wheelEvent(event)
            return
        data_lo = min(min(self._xs), min(self._ys))
        data_hi = max(max(self._xs), max(self._ys))
        if data_hi <= data_lo:
            super().wheelEvent(event)
            return
        lo = self._view_lo if self._view_lo is not None else data_lo
        hi = self._view_hi if self._view_hi is not None else data_hi
        center = (lo + hi) / 2
        span = hi - lo
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_span = span / factor
        new_span = max(new_span, (data_hi - data_lo) * 0.02)
        new_span = min(new_span, (data_hi - data_lo) * 8)
        self._view_lo = center - new_span / 2
        self._view_hi = center + new_span / 2
        self.update()

    def mouseDoubleClickEvent(self, event):
        self._view_lo = None
        self._view_hi = None
        self.update()
