"""空间分析页：栅格拉帘式对比。"""
from pathlib import Path
from ...qt_compat import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    Signal,
)
from ...widgets import RasterSwipeCanvas, panel_box
from core.raster_processing import RasterPreprocessor, collect_raster_sources


class AnalysisPage(QWidget):
    """拉帘式对比两个数据源。"""

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
        self.raster_canvas.loadFinished.connect(self._on_compare_loaded)
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
        # 列出所有已导入的栅格（含对齐后的结果文件），用户可直接选择对齐结果进行对比；
        # 若选择的是原始栅格且存在对齐结果，则自动用对齐后路径显示；两幅网格不一致时才提示需要预处理。
        rasters = collect_raster_sources(self.store.sources)
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
            self.compare_status.setText("请先在「数据管理」导入至少两个栅格数据集")
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
        self.compare_status.setText("栅格加载中…")
        self.raster_canvas.set_images(display_a, display_b, source_a.name, source_b.name)

    def _on_compare_loaded(self, error):
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
