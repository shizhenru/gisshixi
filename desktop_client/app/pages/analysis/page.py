"""空间分析页：栅格拉帘式对比 + 带宽区间探索。"""
from pathlib import Path
from ...qt_compat import (
    QFrame,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QPushButton,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from ...widgets import RasterSwipeCanvas, panel_box
from core.raster_processing import RasterPreprocessor, collect_raster_sources


class AnalysisPage(QWidget):
    """拉帘式对比两个数据源，并通过带宽区间探索 GWR 结果变化。"""

    statusMessage = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.raster_canvas = None
        self.reference_combo = None
        self.comparison_combo = None
        self.compare_status = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(self._swipe_panel(), 1)
        root.addWidget(self._bandwidth_panel())

    def _swipe_panel(self):
        panel, body = panel_box("SWIPE COMPARE", "拉帘式对比", "同比例尺 · 同范围")
        selectors = QHBoxLayout()
        selectors.addWidget(QLabel("数据 A"))
        self.reference_combo = QComboBox()
        selectors.addWidget(self.reference_combo, 1)
        selectors.addWidget(QLabel("数据 B"))
        self.comparison_combo = QComboBox()
        selectors.addWidget(self.comparison_combo, 1)
        reset = QPushButton("复位视图")
        reset.setObjectName("OutlineButton")
        selectors.addWidget(reset)
        body.addLayout(selectors)

        self.raster_canvas = RasterSwipeCanvas()
        reset.clicked.connect(self.raster_canvas.reset_view)
        body.addWidget(self.raster_canvas, 1)
        self.compare_status = QLabel("请选择两幅栅格影像")
        self.compare_status.setObjectName("Muted")
        body.addWidget(self.compare_status)
        self.reference_combo.currentIndexChanged.connect(self._load_selected)
        self.comparison_combo.currentIndexChanged.connect(self._load_selected)
        self._refresh_raster_choices()
        return panel

    def update_after_data_change(self):
        """数据导入或删除后刷新两个栅格选择框。"""
        self._refresh_raster_choices()

    def _refresh_raster_choices(self):
        if self.reference_combo is None:
            return
        manifest = RasterPreprocessor(self.store.project_dir).latest_manifest() or {}
        processed = manifest.get("processed", [])
        processed_paths = {item.get("source_path") for item in processed}
        rasters = [source for source in collect_raster_sources(self.store.sources) if source.path in processed_paths]
        current_a = self.reference_combo.currentData()
        current_b = self.comparison_combo.currentData()
        for combo in (self.reference_combo, self.comparison_combo):
            combo.blockSignals(True)
            combo.clear()
            for source in rasters:
                combo.addItem(source.name, source.path)
            combo.blockSignals(False)
        if rasters:
            self.reference_combo.setCurrentIndex(next((i for i, s in enumerate(rasters) if s.path == current_a), 0))
            default_b = 1 if len(rasters) > 1 else 0
            self.comparison_combo.setCurrentIndex(next((i for i, s in enumerate(rasters) if s.path == current_b), default_b))
        else:
            self.raster_canvas.clear()
            self.compare_status.setText("请先在「预处理」中选择并运行至少两个栅格的对齐")
            return
        self._load_selected()

    def _load_selected(self):
        path_a = self.reference_combo.currentData()
        path_b = self.comparison_combo.currentData()
        if not path_a or not path_b or path_a == path_b:
            self.raster_canvas.clear()
            self.compare_status.setText("请选择两个不同的栅格数据集")
            return
        source_a = next(source for source in self.store.sources if source.path == path_a)
        source_b = next(source for source in self.store.sources if source.path == path_b)
        display_a = self._display_path(path_a)
        display_b = self._display_path(path_b)
        error = self._validate_grids(display_a, display_b)
        if error:
            self.raster_canvas.clear()
            self.compare_status.setText(error)
            return
        error = self.raster_canvas.set_images(display_a, display_b, source_a.name, source_b.name)
        self.compare_status.setText(error or "已加载，可拖动中央分割线进行左右对比")

    def _display_path(self, source_path):
        manifest = RasterPreprocessor(self.store.project_dir).latest_manifest() or {}
        for item in manifest.get("processed", []):
            if item.get("source_path") == source_path and Path(item.get("aligned_path", "")).exists():
                return item["aligned_path"]
        return source_path

    @staticmethod
    def _validate_grids(path_a, path_b):
        try:
            import rasterio
            with rasterio.open(path_a) as first, rasterio.open(path_b) as second:
                if first.count != 1 or second.count != 1:
                    return "拉帘对比仅支持单波段栅格"
                if not all((
                    first.crs == second.crs,
                    first.width == second.width and first.height == second.height,
                    first.transform == second.transform,
                    first.bounds == second.bounds,
                )):
                    return "两幅栅格网格不一致，请先到「预处理」执行栅格对齐"
        except ImportError:
            return "缺少 rasterio，无法读取栅格影像"
        except Exception as exc:
            return f"栅格读取失败：{exc}"
        return ""

    def _bandwidth_panel(self):
        panel, body = panel_box("BANDWIDTH", "带宽区间", "步长 100")
        row = QHBoxLayout()
        row.addWidget(QLabel("100"))
        self.bandwidth_slider = QSlider(Qt.Orientation.Horizontal)
        self.bandwidth_slider.setRange(100, 1000)
        self.bandwidth_slider.setSingleStep(100)
        self.bandwidth_slider.setPageStep(100)
        self.bandwidth_slider.setValue(500)
        self.bandwidth_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.bandwidth_slider.setTickInterval(100)
        row.addWidget(self.bandwidth_slider, 1)
        row.addWidget(QLabel("1000"))
        self.bandwidth_value = QLabel("500")
        self.bandwidth_value.setStyleSheet("color: #2d8c7c; font-weight: 700;")
        row.addWidget(self.bandwidth_value)
        body.addLayout(row)
        self.bandwidth_slider.valueChanged.connect(
            lambda value: self.bandwidth_value.setText(str(value))
        )
        self.bandwidth_slider.valueChanged.connect(
            lambda value: self.statusMessage.emit(f"带宽：{value}")
        )
        return panel
