"""直方图画布：单字段频率分布。"""
from ..qt_compat import QBrush, QColor, QPainter, QPen, QRectF, QSizePolicy, Qt, QWidget


def _fmt(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.4g}"


class HistogramCanvas(QWidget):
    """自绘直方图，无第三方依赖。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(340, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._values = []
        self._label = "字段"

    def set_data(self, values, label="字段"):
        self._values = [v for v in values if v is not None and isinstance(v, (int, float))]
        self._label = label
        self.update()

    def clear(self):
        self._values = []
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#dce9e4"), 1))
        painter.setBrush(QBrush(QColor("#f7faf9")))
        painter.drawRoundedRect(rect, 6, 6)

        if len(self._values) < 2:
            painter.setPen(QPen(QColor("#a8b8b4")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "直方图\n选择字段后显示分布")
            return

        lo, hi = min(self._values), max(self._values)
        if hi <= lo:
            hi = lo + 1.0
        n = len(self._values)
        nbins = max(5, min(30, int(n ** 0.5) * 2))
        bin_w = (hi - lo) / nbins
        counts = [0] * nbins
        for v in self._values:
            idx = int((v - lo) / bin_w)
            idx = max(0, min(idx, nbins - 1))
            counts[idx] += 1
        max_count = max(counts) or 1

        left, right, top, bottom = 46, 16, 16, 40
        plot = rect.adjusted(left, top, -right, -bottom)
        bar_w = plot.width() / nbins

        # 柱子
        painter.setPen(QPen(QColor("#2d8c7c"), 1))
        painter.setBrush(QBrush(QColor("#7fcdbb")))
        for i, c in enumerate(counts):
            if c == 0:
                continue
            bh = c / max_count * plot.height()
            x = plot.left() + i * bar_w
            y = plot.bottom() - bh
            painter.drawRect(QRectF(x, y, max(bar_w - 1, 1), bh))

        # 刻度 + 标题
        fm = painter.fontMetrics()
        painter.setPen(QPen(QColor("#6b7f7b")))
        lo_text, hi_text = _fmt(lo), _fmt(hi)
        painter.drawText(QRectF(plot.left(), plot.bottom() + 4, 70, 18), Qt.AlignmentFlag.AlignLeft, lo_text)
        painter.drawText(QRectF(plot.right() - 70, plot.bottom() + 4, 70, 18), Qt.AlignmentFlag.AlignRight, hi_text)
        painter.drawText(QRectF(plot.left(), rect.bottom() - 20, plot.width(), 16), Qt.AlignmentFlag.AlignCenter, self._label)
        painter.drawText(QRectF(rect.left(), plot.top() - 10, 40, 16), Qt.AlignmentFlag.AlignRight, str(max_count))
