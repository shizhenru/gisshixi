"""单画布栅格拉帘对比控件。"""
from pathlib import Path

from ..qt_compat import (
    QColor,
    QImage,
    QPainter,
    QPen,
    QPointF,
    QRectF,
    QSizePolicy,
    Qt,
    QWidget,
)


class RasterSwipeCanvas(QWidget):
    """在共享视图中绘制两幅单波段栅格，并按分割线裁切显示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._left_image = QImage()
        self._right_image = QImage()
        self._left_name = "数据 A"
        self._right_name = "数据 B"
        self._split_ratio = 0.5
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._dragging_split = False
        self._panning = False
        self._pan_start = QPointF()
        self._offset_start = QPointF()
        self._fit_pending = True

    def set_images(self, left_path: str, right_path: str, left_name: str, right_name: str):
        """读取两个栅格并准备显示；返回错误文本，成功时返回空字符串。"""
        try:
            self._left_image = self._read_raster(left_path)
            self._right_image = self._read_raster(right_path)
        except (ImportError, OSError, ValueError) as exc:
            self.clear()
            return str(exc)
        self._left_name = left_name
        self._right_name = right_name
        self._fit_pending = True
        self.update()
        return ""

    def clear(self):
        self._left_image = QImage()
        self._right_image = QImage()
        self._fit_pending = True
        self.update()

    @staticmethod
    def _read_raster(path: str) -> QImage:
        try:
            import numpy as np
            import rasterio
        except ImportError as exc:
            raise ImportError("缺少 rasterio 或 numpy，无法显示栅格影像") from exc

        raster_path = Path(path)
        if not raster_path.exists():
            raise OSError(f"栅格文件不存在：{raster_path.name}")
        with rasterio.open(raster_path) as dataset:
            if dataset.count != 1:
                raise ValueError(f"栅格必须是单波段：{raster_path.name}")
            values = dataset.read(1, masked=True)
            data = np.asarray(values.filled(np.nan), dtype="float32")
            valid = np.isfinite(data) & ~np.asarray(values.mask, dtype=bool)
            if not valid.any():
                raise ValueError(f"栅格没有有效像元：{raster_path.name}")
            low, high = np.nanpercentile(data[valid], [2, 98])
            if high <= low:
                low = float(np.nanmin(data[valid]))
                high = float(np.nanmax(data[valid]))
            if high <= low:
                high = low + 1.0
            normalized = np.nan_to_num((data - low) / (high - low), nan=0.0, posinf=1.0, neginf=0.0)
            intensity = np.clip(normalized * 255, 0, 255).astype("uint8")
            alpha = np.where(valid, 255, 0).astype("uint8")
            rgba = np.empty((data.shape[0], data.shape[1], 4), dtype="uint8")
            rgba[..., 0] = intensity
            rgba[..., 1] = intensity
            rgba[..., 2] = intensity
            rgba[..., 3] = alpha
            return QImage(
                rgba.data,
                rgba.shape[1],
                rgba.shape[0],
                rgba.strides[0],
                QImage.Format.Format_RGBA8888,
            ).copy()

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
        if self._left_image.isNull() or self._right_image.isNull():
            painter.setPen(QColor("#b8c9c5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "请选择两幅已对齐的栅格影像")
            return
        if self._fit_pending:
            self._fit()
        top_left = self._image_rect()
        target = self._scaled_rect(top_left)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self._right_image)
        split_x = int(self.width() * self._split_ratio)
        painter.save()
        painter.setClipRect(0, 0, split_x, self.height())
        painter.drawImage(target, self._left_image)
        painter.restore()

        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(split_x, 0, split_x, self.height())
        painter.setBrush(QColor("#2d8c7c"))
        handle_y = int(self.height() / 2 - 17)
        painter.drawRoundedRect(split_x - 9, handle_y, 18, 34, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(split_x - 5, int(self.height() / 2 + 5), "↔")
        painter.setPen(QColor("#ffffff"))
        painter.drawText(14, 25, self._left_name)
        painter.drawText(self.width() - 14 - painter.fontMetrics().horizontalAdvance(self._right_name), 25, self._right_name)

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
