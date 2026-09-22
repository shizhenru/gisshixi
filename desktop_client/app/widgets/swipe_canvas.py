"""拉帘对比画布：在共享视图中绘制两侧图层（栅格或矢量），按分割线左右裁切。

两侧共用一套世界→屏幕变换，范围取两个图层的并集，因此天然同比例尺、同范围。
矢量图层与地图一样先光栅化为缓存图（按设备像素比出图），平移/小幅缩放时只贴图。
"""
from __future__ import annotations

from ..qt_compat import (
    QBrush,
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
    QTransform,
    QWidget,
    Signal,
    Slot,
)

from .swipe_layers import build_raster_layer, build_vector_layer


class SwipeLoadWorker(QObject):
    """后台线程准备两侧图层，避免重投影 / 大栅格解码阻塞界面。"""

    finished = Signal(object, object, str, int)  # (layer_a, layer_b, error, seq)

    def __init__(self, spec_a, spec_b, seq):
        super().__init__()
        self._spec_a, self._spec_b, self._seq = spec_a, spec_b, seq

    @Slot()
    def run(self):
        try:
            layer_a = self._build(self._spec_a)
            layer_b = self._build(self._spec_b)
            error = layer_a.error or layer_b.error
            self.finished.emit(layer_a, layer_b, error, self._seq)
        except Exception as exc:  # noqa: BLE001 - 失败以错误文本回传
            self.finished.emit(None, None, str(exc), self._seq)

    @staticmethod
    def _build(spec):
        """spec = {kind, path, target_crs, field, method, n_classes}。"""
        if spec["kind"] == "raster":
            return build_raster_layer(spec["path"], spec["target_crs"])
        return build_vector_layer(
            spec["path"], spec["target_crs"],
            field=spec.get("field", ""), method=spec.get("method", "自然间断点"),
            n_classes=spec.get("n_classes", 5),
        )


class SwipeCanvas(QWidget):
    """栅格 / 矢量通用的拉帘画布；两侧图层各自可渲染为单色或按字段设色。"""

    loadFinished = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._layers = [None, None]
        self._images = [QImage(), QImage()]
        self._cache_key = None
        self._split_ratio = 0.5
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._dragging_split = False
        self._panning = False
        self._pan_start = QPointF()
        self._offset_start = QPointF()
        self._fit_pending = True
        self._fit_mode = "intersection"
        self._loading = False
        self._error = ""
        self._load_seq = 0

    # ------------------------------------------------------------------ #
    # 加载
    # ------------------------------------------------------------------ #
    def load(self, spec_a, spec_b):
        """异步准备两侧图层；结果通过 loadFinished 回传（成功为空字符串）。"""
        self._layers = [None, None]
        self._images = [QImage(), QImage()]
        self._cache_key = None
        self._loading = True
        self._error = ""
        self._fit_pending = True
        self.update()
        self._load_seq += 1
        thread = QThread(self)
        worker = SwipeLoadWorker(spec_a, spec_b, self._load_seq)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_loaded)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # 持有引用，避免线程/工作对象被 GC 导致 started 信号不触发。
        self._load_thread = thread
        self._load_worker = worker
        thread.start()

    @Slot(object, object, str, int)
    def _on_loaded(self, layer_a, layer_b, error, seq):
        if seq != self._load_seq:
            return  # 过期结果，忽略
        self._loading = False
        if error:
            self._layers = [None, None]
            self._error = error
        else:
            self._layers = [layer_a, layer_b]
            self._error = ""
        self._images = [QImage(), QImage()]
        self._cache_key = None
        self._fit_pending = True
        self.update()
        self.loadFinished.emit(error)

    def clear(self):
        self._load_seq += 1
        self._loading = False
        self._error = ""
        self._layers = [None, None]
        self._images = [QImage(), QImage()]
        self._cache_key = None
        self._fit_pending = True
        self.update()

    def reset_view(self, mode="intersection"):
        """复位视图：默认对齐两层重叠区，mode="union" 时显示全部范围。"""
        self._fit_mode = mode
        self._fit_pending = True
        self._cache_key = None
        self.update()

    def is_stale(self):
        """当前没有图层，或上一次加载失败时返回 True（需要重新加载）。"""
        if self._loading or self._error:
            return True
        return any(layer is None for layer in self._layers)

    def layer_names(self):
        return [layer.name if layer else "" for layer in self._layers]

    # ------------------------------------------------------------------ #
    # 视图
    # ------------------------------------------------------------------ #
    def _world_bounds(self, mode="union"):
        """两侧范围。mode="intersection" 取重叠区，无重叠时返回 None。"""
        boxes = [layer.bounds for layer in self._layers if layer and layer.bounds]
        if not boxes:
            return None
        pick_low = max if mode == "intersection" else min
        pick_high = min if mode == "intersection" else max
        xmin, ymin = pick_low(b[0] for b in boxes), pick_low(b[1] for b in boxes)
        xmax, ymax = pick_high(b[2] for b in boxes), pick_high(b[3] for b in boxes)
        if xmax <= xmin or ymax <= ymin:
            return None
        return (xmin, ymin, xmax, ymax)

    def _fit(self, mode=None):
        """默认对齐到两层的重叠范围。

        取并集时，范围小的图层（比如省界矢量 vs 全国栅格）会被缩到不足一个像素、
        完全看不见，对比就失去意义；重叠区才是两侧真正能比的地方。无重叠时退回并集。
        """
        bounds = self._world_bounds(mode or "intersection") or self._world_bounds()
        if bounds is None:
            return
        xmin, ymin, xmax, ymax = bounds
        self._scale = min(self.width() / (xmax - xmin), self.height() / (ymax - ymin)) * 0.96
        self._center = QPointF((xmin + xmax) / 2, (ymin + ymax) / 2)
        self._offset = QPointF(0, 0)
        self._fit_pending = False

    def _view_transform(self):
        """世界坐标 → 屏幕像素（逻辑像素）。y 轴翻转为屏幕向下。"""
        center = self.rect().center()
        return QTransform(
            self._scale, 0, 0, -self._scale,
            center.x() + self._offset.x() - self._center.x() * self._scale,
            center.y() + self._offset.y() + self._center.y() * self._scale,
        )

    # ------------------------------------------------------------------ #
    # 绘制
    # ------------------------------------------------------------------ #
    def _render_layer_image(self, index, transform, pixel_scale):
        """把一个图层光栅化到与画布等大的物理像素图，供按分割线裁切贴图。"""
        layer = self._layers[index]
        image = QImage(pixel_scale.width(), pixel_scale.height(),
                       QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        if layer is None:
            return image
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 画布逻辑坐标 → 图像物理像素
        painter.scale(pixel_scale.device_ratio, pixel_scale.device_ratio)

        if layer.kind == "raster" and layer.image is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            xmin, ymin, xmax, ymax = layer.bounds
            top_left = transform.map(QPointF(xmin, ymax))
            bottom_right = transform.map(QPointF(xmax, ymin))
            painter.drawImage(QRectF(top_left, bottom_right), layer.image)
        else:
            painter.setTransform(transform, combine=True)
            # 细描边让相邻要素分层可辨；未设色时只描边不填色
            outline = QPen(QColor(0, 0, 0, 70))
            outline.setCosmetic(True)
            painter.setPen(outline)
            fills = layer.fills
            for order, path in enumerate(layer.paths):
                fid = layer.feature_ids[order] if order < len(layer.feature_ids) else -1
                color = fills[fid] if 0 <= fid < len(fills) else None
                painter.setBrush(QBrush(color) if color is not None else Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
        painter.end()
        return image

    def _ensure_cache(self, transform):
        """视图变化时重绘两侧缓存图；否则直接复用。"""
        ratio = self.devicePixelRatioF()
        size = (self.width(), self.height(), round(self._scale, 6),
                round(self._offset.x(), 3), round(self._offset.y(), 3), ratio)
        if self._cache_key == size and not self._images[0].isNull():
            return
        for index in (0, 1):
            if self._layers[index] is None:
                self._images[index] = QImage()
                continue
            holder = _PixelSize(self.width(), self.height(), ratio)
            self._images[index] = self._render_layer_image(index, transform, holder)
        self._cache_key = size

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#172326"))
        if self._loading:
            painter.setPen(QColor("#b8c9c5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "正在准备对比图层…")
            return
        if self._error:
            painter.setPen(QColor("#d86659"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"无法对比：{self._error}")
            return
        if any(layer is None for layer in self._layers):
            painter.setPen(QColor("#b8c9c5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "请选择两侧要对比的数据")
            return
        if self._fit_pending:
            self._fit(getattr(self, "_fit_mode", "intersection"))
        transform = self._view_transform()
        self._ensure_cache(transform)

        split_x = int(self.width() * self._split_ratio)
        names = self.layer_names()
        for index in (0, 1):
            image = self._images[index]
            if image.isNull():
                continue
            painter.save()
            image.setDevicePixelRatio(self.devicePixelRatioF())
            if index == 0:
                painter.setClipRect(0, 0, split_x, self.height())
            else:
                painter.setClipRect(split_x, 0, self.width() - split_x, self.height())
            painter.drawImage(0, 0, image)
            painter.restore()

        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(split_x, 0, split_x, self.height())
        painter.setBrush(QColor("#2d8c7c"))
        handle_y = int(self.height() / 2 - 17)
        painter.drawRoundedRect(split_x - 9, handle_y, 18, 34, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(split_x - 5, int(self.height() / 2 + 5), "↔")
        left_label = self._note_for(0)
        right_label = self._note_for(1)
        painter.drawText(14, 25, names[0] + left_label)
        painter.drawText(self.width() - 14 - painter.fontMetrics().horizontalAdvance(names[1] + right_label),
                         25, names[1] + right_label)

    def _note_for(self, index):
        layer = self._layers[index]
        return f"（{layer.note}）" if layer and layer.note else ""

    # ------------------------------------------------------------------ #
    # 交互
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event):
        split_x = self.width() * self._split_ratio
        if abs(event.position().x() - split_x) <= 14:
            self._dragging_split = True
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif event.button() == Qt.MouseButton.LeftButton:
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
            near = abs(event.position().x() - split_x) <= 14
            self.setCursor(Qt.CursorShape.SizeHorCursor if near else Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        del event
        self._dragging_split = False
        self._panning = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event):
        if any(layer is None for layer in self._layers):
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._scale = max(0.05, min(1e7, self._scale * factor))
        self.update()


class _PixelSize:
    """缓存图尺寸 + 设备像素比的小载体。"""

    def __init__(self, width, height, device_ratio):
        self.device_ratio = device_ratio
        self._width = max(1, int(round(width * device_ratio)))
        self._height = max(1, int(round(height * device_ratio)))

    def width(self):
        return self._width

    def height(self):
        return self._height
