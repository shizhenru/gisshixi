"""单画布栅格拉帘对比控件。"""
from ..qt_compat import (
    QColor,
    QImage,
    QObject,
    QPainter,
    QPen,
    QPointF,
    QRectF,
    QSizePolicy,
    Qt,
    QThread,
    QWidget,
    Signal,
    Slot,
)
from .raster_preview import read_raster_preview


class _SwipeLoadWorker(QObject):
    """后台线程读取左右两幅栅格，避免整幅解码阻塞 UI。"""

    finished = Signal(object, object, object, object, str, int)  # left, right, left_range, right_range, error, seq

    def __init__(self, left_path, right_path, seq):
        super().__init__()
        self._left_path = left_path
        self._right_path = right_path
        self._seq = seq

    @Slot()
    def run(self):
        try:
            left, _, left_range = read_raster_preview(self._left_path)
            right, _, right_range = read_raster_preview(self._right_path)
            self.finished.emit(left, right, left_range, right_range, "", self._seq)
        except Exception as exc:  # noqa: BLE001 - 失败以错误文本回传，不向上抛
            self.finished.emit(QImage(), QImage(), None, None, str(exc), self._seq)


class RasterSwipeCanvas(QWidget):
    """在共享视图中绘制两幅单波段栅格，并按分割线裁切显示。"""

    loadFinished = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._left_image = QImage()
        self._right_image = QImage()
        self._left_name = "数据 A"
        self._right_name = "数据 B"
        self._left_range = None
        self._right_range = None
        self._split_ratio = 0.5
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._dragging_split = False
        self._panning = False
        self._pan_start = QPointF()
        self._offset_start = QPointF()
        self._fit_pending = True
        self._loading = False
        self._error = ""
        self._load_seq = 0

    def set_images(self, left_path: str, right_path: str, left_name: str, right_name: str):
        """异步读取两幅栅格；结果通过 loadFinished 信号回传，成功回传空字符串。"""
        self._left_name = left_name
        self._right_name = right_name
        self._left_image = QImage()
        self._right_image = QImage()
        self._loading = True
        self._error = ""
        self._fit_pending = True
        self.update()
        self._load_seq += 1
        seq = self._load_seq
        thread = QThread(self)
        worker = _SwipeLoadWorker(left_path, right_path, seq)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_load_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # 持有引用，避免线程/工作对象被 GC 导致 started 信号不触发。
        self._load_thread = thread
        self._load_worker = worker
        thread.start()
        return ""

    @Slot(object, object, object, object, str, int)
    def _on_load_finished(self, left, right, left_range, right_range, error, seq):
        if seq != self._load_seq:
            return  # 过期结果，忽略
        self._loading = False
        if error:
            self._error = error
            self._left_image = QImage()
            self._right_image = QImage()
            self._left_range = None
            self._right_range = None
        else:
            self._left_image = left
            self._right_image = right
            self._left_range = left_range
            self._right_range = right_range
            self._error = ""
        self._fit_pending = True
        self.update()
        self.loadFinished.emit(error)

    def clear(self):
        self._load_seq += 1
        self._loading = False
        self._error = ""
        self._left_image = QImage()
        self._right_image = QImage()
        self._fit_pending = True
        self.update()

    def reset_view(self):
        self._fit_pending = True
        self.update()

    def _image_rect(self):
        if self._left_image.isNull():
            return None
        width = self._left_image.width() * self._scale
        height = self._left_image.height() * self._scale
        return QPointF(self.rect().center()) + self._offset - QPointF(width / 2, height / 2)

    def _fit(self):
        if self._left_image.isNull() or self._right_image.isNull():
            return
        scale_x = self.width() / self._left_image.width()
        scale_y = self.height() / self._left_image.height()
        self._scale = min(scale_x, scale_y) * 0.96
        self._offset = QPointF(0, 0)
        self._fit_pending = False

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#172326"))
        if self._loading:
            painter.setPen(QColor("#b8c9c5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "栅格加载中…")
            return
        if self._error:
            painter.setPen(QColor("#d86659"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"打开失败：{self._error}")
            return
        if self._left_image.isNull() or self._right_image.isNull():
            painter.setPen(QColor("#b8c9c5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "请选择两幅已对齐的栅格影像")
            return
        if self._fit_pending:
            self._fit()
        top_left = self._image_rect()
        target = self._scaled_rect(top_left)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        split_x = int(self.width() * self._split_ratio)
        # 左侧只画 A、右侧只画 B。两侧各自裁切，透明(nodata)区域露出底色，
        # 不会让另一幅图透出来形成「底图」错觉，A/B 互换后效果也对称一致。
        painter.save()
        painter.setClipRect(0, 0, split_x, self.height())
        painter.drawImage(target, self._left_image)
        painter.restore()
        painter.save()
        painter.setClipRect(split_x, 0, self.width() - split_x, self.height())
        painter.drawImage(target, self._right_image)
        painter.restore()

        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(split_x, 0, split_x, self.height())
        painter.setBrush(QColor("#2d8c7c"))
        handle_y = int(self.height() / 2 - 17)
        painter.drawRoundedRect(split_x - 9, handle_y, 18, 34, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(split_x - 5, int(self.height() / 2 + 5), "↔")
        painter.setPen(QColor("#ffffff"))
        left_label = self._left_name + self._format_range(self._left_range)
        right_label = self._right_name + self._format_range(self._right_range)
        painter.drawText(14, 25, left_label)
        painter.drawText(self.width() - 14 - painter.fontMetrics().horizontalAdvance(right_label), 25, right_label)

    @staticmethod
    def _format_range(value_range) -> str:
        if not value_range:
            return ""
        low, high = value_range
        return f"（{low:.3g} ~ {high:.3g}）"

    def _scaled_rect(self, top_left):
        return QRectF(top_left.x(), top_left.y(), self._left_image.width() * self._scale, self._left_image.height() * self._scale)

    def mousePressEvent(self, event):
        split_x = self.width() * self._split_ratio
        if abs(event.position().x() - split_x) <= 14:
            self._dragging_split = True
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif event.button() == Qt.MouseButton.LeftButton and not self._left_image.isNull():
            self._panning = True
            self._pan_start = event.position()
            self._offset_start = self._offset
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_split:
            self._split_ratio = max(0.02, min(0.98, event.position().x() / max(1, self.width())))
            self.update()
        elif self._panning:
            self._offset = self._offset_start + event.position() - self._pan_start
            self.update()
        else:
            split_x = self.width() * self._split_ratio
            self.setCursor(Qt.CursorShape.SizeHorCursor if abs(event.position().x() - split_x) <= 14 else Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        del event
        self._dragging_split = False
        self._panning = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event):
        if self._left_image.isNull():
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._scale = max(0.05, min(20.0, self._scale * factor))
        self.update()
