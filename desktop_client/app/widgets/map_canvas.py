"""地图画布：加载真实几何数据时渲染矢量要素，支持缩放、平移、复位。"""
from ..qt_compat import (
    QColor,
    QBrush,
    QImage,
    QObject,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
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
from .data_select import MIME_SOURCE_PATH
from .raster_preview import RasterLoadWorker
from .vector_render import build_polygon_path, decimate_ring

# 矢量缓存图长边上限（物理像素）：过大既费内存又拖慢光栅化
_VECTOR_CACHE_MAX = 6000

# 缓存超采样倍数：按当前视图的 1.5 倍出图，缩小显示时是降采样（更锐），
# 放大到 1.5 倍以内也不必重绘，把「中间缩放档会发糊」的区间从 1~2 倍压到 1.5~2 倍
_VECTOR_CACHE_HEADROOM = 1.5


class MapCanvas(QWidget):
    """地图画布：加载真实几何数据时渲染矢量要素；未加载时显示空白占位。"""

    sourceDropped = Signal(str)
    featureClicked = Signal(int)
    rasterLoaded = Signal(str)

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
        self._highlight_indices = frozenset()
        self._press_pos = None
        self._raster_image = QImage()
        self._raster_loading = False
        self._raster_error = ""
        self._raster_seq = 0
        self._vector_image = QImage()
        self._vector_cache_scale = 0.0
        self._loading_text = ""

    def set_loading(self, loading: bool, text: str = ""):
        """显示 / 清除「加载中」占位：后台解析矢量期间给用户反馈，避免看起来像卡死。"""
        self._loading_text = text if loading else ""
        self.update()

    def load_shapes(self, geometry_data: dict):
        """加载真实几何数据用于渲染（shapefile 等）。"""
        self.shapes = geometry_data.get("geometries", [])
        self.data_bbox = geometry_data.get("bbox")
        self._feature_fills = []
        self._highlight_indices = frozenset()
        self._raster_image = QImage()
        self._raster_loading = False
        self._raster_error = ""
        self._vector_image = QImage()
        self._vector_cache_scale = 0.0
        self._build_cache()
        self._view_init = False
        self.update()

    def load_raster(self, path):
        """后台读取单波段栅格并显示为地图底图。"""
        self.shapes = []
        self._polygons = []
        self._polylines = []
        self._points = []
        self._polygon_feature_ids = []
        self._feature_fills = []
        self._highlight_indices = frozenset()
        self._raster_image = QImage()
        self._vector_image = QImage()
        self._vector_cache_scale = 0.0
        self._raster_loading = True
        self._raster_error = ""
        self.data_bbox = None
        self._view_init = False
        self.update()
        self._raster_seq += 1
        thread = QThread(self)
        worker = RasterLoadWorker(path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_raster_loaded)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # 持有引用，避免线程/工作对象被 GC 导致 started 信号不触发。
        self._raster_thread = thread
        self._raster_worker = worker
        thread.start()

    @Slot(object)
    def _on_raster_loaded(self, payload):
        self._raster_loading = False
        error = payload.get("error", "")
        if error:
            self._raster_error = error
            self._raster_image = QImage()
            self.data_bbox = None
        else:
            self._raster_image = payload.get("image", QImage())
            self.data_bbox = payload.get("bounds")
            self._raster_error = ""
        self._view_init = False
        self.update()
        self.rasterLoaded.emit(error)

    def clear(self):
        """清空已加载的数据（矢量与栅格），回到空白占位状态。"""
        self._raster_seq += 1
        self._loading_text = ""
        self.shapes = []
        self.data_bbox = None
        self._polygons = []
        self._polylines = []
        self._points = []
        self._polygon_feature_ids = []
        self._feature_fills = []
        self._highlight_indices = frozenset()
        self._raster_image = QImage()
        self._vector_image = QImage()
        self._vector_cache_scale = 0.0
        self._raster_loading = False
        self._raster_error = ""
        self._view_init = False
        self.update()

    def set_feature_colors(self, colors):
        """设置每个要素的填充色（与 self.shapes 对齐，元素为 QColor 或 None）。"""
        self._feature_fills = list(colors) if colors else []
        self._vector_image = QImage()
        self._vector_cache_scale = 0.0
        self.update()

    def highlight_features(self, indices):
        """高亮若干要素（索引与 self.shapes 对齐）。传 None / 空表示取消高亮。

        支持多要素是为了与属性表多选联动：属性表里选中几行，地图上对应的区域一起高亮。
        """
        if indices is None:
            self._highlight_indices = frozenset()
        elif isinstance(indices, int):
            self._highlight_indices = frozenset((indices,))
        else:
            self._highlight_indices = frozenset(indices)
        self.update()

    def _build_cache(self):
        """把世界坐标几何预转为 QPolygonF / QPointF，并对大面要素抽稀以加速渲染。

        同一要素的所有环（外环 + 若干洞）拼进同一个 QPolygonF，配合奇偶填充规则镂空：
        逐环单独绘制会把洞一起填实，使带洞的大面（栅格转面数据常见）盖住洞里的小块。
        """
        self._polygons = []
        self._polylines = []
        self._points = []
        self._polygon_feature_ids = []
        for fid, shape in enumerate(self.shapes):
            kind = shape.get("type")
            if kind == "polygon":
                path = build_polygon_path(shape.get("rings", []))
                if path is None:
                    continue
                # 一个要素一条路径：外环 + 各洞是独立子路径，按奇偶规则镂空，不依赖环的绕向
                self._polygons.append(path)
                self._polygon_feature_ids.append(fid)
            elif kind == "polyline":
                for part in shape.get("parts", []):
                    self._polylines.append(QPolygonF([QPointF(x, y) for x, y in part]))
            elif kind == "point":
                self._points.append(QPointF(*shape.get("coords", (0.0, 0.0))))
            elif kind == "multipoint":
                for p in shape.get("points", []):
                    self._points.append(QPointF(*p))

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
        # 倒序取最后一个命中的：绘制是正序、后画的盖在上面，这样点到的才是看到的那块。
        # 洞已按奇偶规则镂空，落在洞里的点不会被外层大面误判命中。
        for i in range(len(self._polygons) - 1, -1, -1):
            if self._polygons[i].contains(wp):
                if i < len(self._polygon_feature_ids):
                    return self._polygon_feature_ids[i]
                return None
        return None

    def _render_vector_cache(self):
        """把矢量图层一次性光栅化为世界坐标 QImage，paint 时只贴图。

        大图层（数万要素）逐要素重绘代价高；光栅化后平移 / 小幅缩放只做一次
        drawImage，仅当放大超过缓存分辨率 2 倍时才按更高分辨率重绘。
        """
        self._vector_image = QImage()
        self._vector_cache_scale = 0.0
        if not self.data_bbox or not (self._polygons or self._polylines or self._points):
            return
        xmin, ymin, xmax, ymax = self.data_bbox
        world_w = xmax - xmin
        world_h = ymax - ymin
        if world_w <= 0 or world_h <= 0:
            return
        # 分辨率以当前视图比例为准，长边最多 _VECTOR_CACHE_MAX 像素，避免深缩放生成超大图。
        # 必须乘以设备像素比：rect() 是逻辑像素，实际帧缓冲是 dpr 倍物理像素，
        # 按逻辑像素渲染会被系统放大，HiDPI（如 150% 缩放）下小地图一开就是糊的。
        scale = self._scale * self.devicePixelRatioF() * _VECTOR_CACHE_HEADROOM
        max_scale = _VECTOR_CACHE_MAX / max(world_w, world_h)
        if scale > max_scale:
            scale = max_scale
        if scale <= 0:
            return
        img_w = max(1, int(round(world_w * scale)))
        img_h = max(1, int(round(world_h * scale)))
        image = QImage(img_w, img_h, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # world -> image（y 翻转）：xmin→0、ymax→0
        painter.setTransform(QTransform(scale, 0, 0, -scale, -xmin * scale, ymax * scale))

        outline = QPen(QColor("#2d8c7c"))
        outline.setCosmetic(True)
        default_fill = QColor("#b0d5cc")
        for i, poly in enumerate(self._polygons):
            fid = self._polygon_feature_ids[i] if i < len(self._polygon_feature_ids) else -1
            color = default_fill
            if self._feature_fills and 0 <= fid < len(self._feature_fills):
                color = self._feature_fills[fid] or default_fill
            painter.setPen(outline)
            painter.setBrush(QBrush(color))
            # 路径按奇偶规则镂空洞：逐环填实会让带洞的大面盖住洞里的小块
            painter.drawPath(poly)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        line_pen = QPen(QColor("#e78338"))
        line_pen.setCosmetic(True)
        line_pen.setWidth(2)
        painter.setPen(line_pen)
        for line in self._polylines:
            painter.drawPolyline(line)
        painter.setPen(QPen(QColor("#d86659"), 1))
        painter.setBrush(QBrush(QColor("#d86659")))
        for point in self._points:
            painter.drawEllipse(point, 4, 4)
        painter.end()

        self._vector_image = image
        self._vector_cache_scale = scale

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

        # 光栅化缓存失效（未渲染 / 颜色变化 / 放大超过 2 倍）时重绘，否则直接贴图。
        # 比较用物理像素密度，与 _render_vector_cache 内部口径一致。
        pixel_scale = scale * self.devicePixelRatioF() * _VECTOR_CACHE_HEADROOM
        if (self._vector_image.isNull() or self._vector_cache_scale <= 0
                or pixel_scale > self._vector_cache_scale * 2.0):
            self._render_vector_cache()

        if not self._vector_image.isNull():
            xmin, ymin, xmax, ymax = self.data_bbox
            top_left = transform.map(QPointF(xmin, ymax))
            bottom_right = transform.map(QPointF(xmax, ymin))
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(QRectF(top_left, bottom_right), self._vector_image)

        # 高亮要素叠加绘制：不重绘整层，只画命中要素。
        if self._highlight_indices:
            painter.save()
            painter.setTransform(transform)
            hl = QPen(QColor("#f5a623"))
            hl.setCosmetic(True)
            hl.setWidthF(2.5)
            painter.setPen(hl)
            painter.setBrush(QBrush(QColor("#f5d08a")))
            for i, poly in enumerate(self._polygons):
                fid = self._polygon_feature_ids[i] if i < len(self._polygon_feature_ids) else -1
                if fid in self._highlight_indices:
                    painter.drawPath(poly)
            painter.restore()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if self._loading_text:
            self._paint_placeholder(painter, rect, self._loading_text)
        elif self._raster_loading:
            self._paint_placeholder(painter, rect, "栅格加载中…")
        elif self._raster_error:
            self._paint_placeholder(painter, rect, f"栅格打开失败：{self._raster_error}", error=True)
        elif not self._raster_image.isNull():
            self._paint_raster(painter, rect)
        elif self.shapes:
            self._paint_data(painter, rect)
        else:
            self._paint_placeholder(painter, rect, "未导入空间数据")

    def _paint_placeholder(self, painter, rect, text, error=False):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#dce9e4"), 1))
        painter.setBrush(QBrush(QColor("#f7faf9")))
        painter.drawRoundedRect(rect, 6, 6)
        color = QColor("#d86659") if error else QColor("#a8b8b4")
        painter.setPen(QPen(color, 1))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_raster(self, painter, rect):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.data_bbox:
            return
        if not self._view_init:
            self._fit(rect)
        cx = rect.center().x()
        cy = rect.center().y()
        scale = self._scale
        transform = QTransform(scale, 0, 0, -scale, cx - self._center_x * scale, cy + self._center_y * scale)
        xmin, ymin, xmax, ymax = self.data_bbox
        top_left = transform.map(QPointF(xmin, ymax))
        bottom_right = transform.map(QPointF(xmax, ymin))
        painter.drawImage(QRectF(top_left, bottom_right), self._raster_image)

    def zoom_in(self):
        self._zoom(1.25)

    def zoom_out(self):
        self._zoom(1 / 1.25)

    def reset_view(self):
        self._view_init = False
        self.update()

    def _zoom(self, factor):
        if not self.data_bbox:
            return
        rect = self.rect().adjusted(1, 1, -1, -1)
        if not self._view_init:
            self._fit(rect)
        self._scale *= factor
        self.update()

    def wheelEvent(self, event):
        if not self.data_bbox:
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
        if self.data_bbox and event.button() == Qt.MouseButton.LeftButton:
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
        if self.data_bbox:
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
