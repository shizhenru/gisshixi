"""空间分析页：栅格 / 矢量的拉帘式对比。

两侧各自可选「栅格」或「矢量」，因此栅格↔栅格、矢量↔矢量、栅格↔矢量混合都能比。
两侧坐标系不一致时自动重投影到同一目标坐标系（默认取 A 侧），再按分割线左右裁切。
"""
from pathlib import Path

from ...qt_compat import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTimer,
    QVBoxLayout,
    QWidget,
    Signal,
)
from ...widgets import SwipeCanvas, panel_box, vector_fields
from core.raster_processing import RasterPreprocessor, collect_raster_sources

KINDS = ["栅格", "矢量"]
# 没有可选项时下拉框显示的占位符
NO_CHOICE = "-"
# 矢量设色方法（与工作台分层设色保持一致）
VECTOR_METHODS = ["自然间断点", "等间隔", "分位数", "唯一值"]


def collect_vector_sources(sources) -> list:
    """已导入的矢量数据源（SHP / GeoPackage / GeoJSON）。"""
    suffixes = {".shp", ".gpkg", ".geojson"}
    return [source for source in sources if Path(source.path).suffix.lower() in suffixes]


class AnalysisPage(QWidget):
    """拉帘式对比两个数据源，支持栅格与矢量的任意组合。"""

    statusMessage = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.raster_canvas = None
        self._last_specs = None
        # 防抖：改一个下拉框往往连带触发多次刷新，攒一下再真正加载，
        # 否则会同时跑好几份「解析 + 重投影 + 建路径」（十几万要素时每份约 7 秒）互相抢 CPU
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(250)
        self._load_timer.timeout.connect(self._start_load)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(self._swipe_panel(), 1)

    # ------------------------------------------------------------------ #
    # 界面
    # ------------------------------------------------------------------ #
    def _swipe_panel(self):
        panel, body = panel_box("SWIPE COMPARE", "拉帘式对比", "同比例尺 · 同范围")

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(4, 1)

        grid.addWidget(self._field_label("A 类型"), 0, 0)
        self.kind_a = QComboBox()
        self.kind_a.addItems(KINDS)
        grid.addWidget(self.kind_a, 0, 1)
        grid.addWidget(self._field_label("B 类型"), 0, 3)
        self.kind_b = QComboBox()
        self.kind_b.addItems(KINDS)
        grid.addWidget(self.kind_b, 0, 4)

        grid.addWidget(self._field_label("A 数据"), 1, 0)
        self.combo_a = QComboBox()
        grid.addWidget(self.combo_a, 1, 1)
        grid.addWidget(self._field_label("B 数据"), 1, 3)
        self.combo_b = QComboBox()
        grid.addWidget(self.combo_b, 1, 4)

        grid.addWidget(self._field_label("A 设色字段"), 2, 0)
        self.field_a = QComboBox()
        grid.addWidget(self.field_a, 2, 1)
        grid.addWidget(self._field_label("B 设色字段"), 2, 3)
        self.field_b = QComboBox()
        grid.addWidget(self.field_b, 2, 4)

        grid.addWidget(self._field_label("A 分级方法"), 3, 0)
        self.method_a = QComboBox()
        self.method_a.addItems(VECTOR_METHODS)
        grid.addWidget(self.method_a, 3, 1)
        grid.addWidget(self._field_label("B 分级方法"), 3, 3)
        self.method_b = QComboBox()
        self.method_b.addItems(VECTOR_METHODS)
        grid.addWidget(self.method_b, 3, 4)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        reset = QPushButton("复位视图（重叠区）")
        reset.setObjectName("OutlineButton")
        buttons.addWidget(reset)
        show_all = QPushButton("显示全部范围")
        show_all.setObjectName("OutlineButton")
        buttons.addWidget(show_all)
        buttons.addStretch()
        grid.addLayout(buttons, 0, 5, 4, 1)
        body.addLayout(grid)

        self.raster_canvas = SwipeCanvas()
        self.raster_canvas.loadFinished.connect(self._on_loaded)
        reset.clicked.connect(lambda: self.raster_canvas.reset_view("intersection"))
        show_all.clicked.connect(lambda: self.raster_canvas.reset_view("union"))
        body.addWidget(self.raster_canvas, 1)

        self.compare_status = QLabel("请选择两侧要对比的数据")
        self.compare_status.setObjectName("Muted")
        body.addWidget(self.compare_status)

        for combo in (self.kind_a, self.kind_b):
            combo.currentIndexChanged.connect(self._refresh_data_choices)
        for combo in (self.combo_a, self.combo_b):
            combo.currentIndexChanged.connect(self._on_data_changed)
        for combo in (self.field_a, self.field_b, self.method_a, self.method_b):
            combo.currentIndexChanged.connect(self._load_selected)
        self._refresh_data_choices()
        return panel

    @staticmethod
    def _field_label(text):
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    # ------------------------------------------------------------------ #
    # 数据选择
    # ------------------------------------------------------------------ #
    def update_after_data_change(self):
        """数据导入或删除后刷新两侧的选择框。"""
        self._refresh_data_choices()

    def _sources_for(self, kind):
        if kind == "栅格":
            return collect_raster_sources(self.store.sources)
        return collect_vector_sources(self.store.sources)

    def _refresh_data_choices(self):
        if self.combo_a is None:
            return
        # 栅格默认走对齐结果（若存在），保证两幅网格一致
        for index_in_pair, (kind_combo, data_combo) in enumerate((
            (self.kind_a, self.combo_a),
            (self.kind_b, self.combo_b),
        )):
            sources = self._sources_for(kind_combo.currentText())
            current = data_combo.currentData()
            data_combo.blockSignals(True)
            data_combo.clear()
            for source in sources:
                data_combo.addItem(source.name, source.path)
            data_combo.blockSignals(False)
            index = next((i for i, s in enumerate(sources) if s.path == current), None)
            if index is None and sources:
                # B 侧默认选第二个，避免两侧一上来就是同一份数据
                index = 1 if (index_in_pair and len(sources) > 1) else 0
            if index is not None:
                data_combo.setCurrentIndex(index)
        self._refresh_field_choices()
        self._load_selected()

    def _refresh_field_choices(self):
        """矢量侧才需要设色字段与分级方法；栅格侧没有可选内容，显示「-」并置灰。"""
        for kind_combo, field_combo, method_combo, data_combo in (
            (self.kind_a, self.field_a, self.method_a, self.combo_a),
            (self.kind_b, self.field_b, self.method_b, self.combo_b),
        ):
            if kind_combo.currentText() != "矢量":
                self._set_single_choice(field_combo)
                self._set_single_choice(method_combo)
                continue
            self._set_choices(method_combo, VECTOR_METHODS)
            path = self._display_path(data_combo.currentData())
            names = vector_fields(path) if path else []
            self._set_choices(field_combo,
                              [("（不设色）", "")] + [(name, name) for name in names],
                              prefer=field_combo.currentData())
        self._suggest_same_source_fields()

    def _suggest_same_source_fields(self):
        """两侧选了同一份数据、又都没指定字段时，给 B 侧自动换一个字段。

        同源同字段比出来两边一模一样，等于没比；自动错开一个能让用户直接看到差别。
        """
        if self.kind_a.currentText() != "矢量" or self.kind_b.currentText() != "矢量":
            return
        if self.combo_a.currentData() != self.combo_b.currentData():
            return
        if self.field_a.currentData() or self.field_b.currentData():
            return
        # 只挑数值字段：文本字段比出来没有数值意义
        path = self._display_path(self.combo_a.currentData())
        numeric = vector_fields(path, numeric_only=True) if path else []
        if len(numeric) < 2:
            return
        for combo, value in ((self.field_a, numeric[0]), (self.field_b, numeric[1])):
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(value))
            combo.blockSignals(False)

    @staticmethod
    def _set_single_choice(combo):
        """没有可选项：只留一个「-」占位并置灰，避免看着像能选。"""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(NO_CHOICE, "")
        combo.blockSignals(False)
        combo.setEnabled(False)

    @staticmethod
    def _set_choices(combo, items, prefer=None):
        """重新填充下拉项并尽量保留原选择；items 元素为 str 或 (显示名, 数据)。"""
        combo.blockSignals(True)
        combo.clear()
        for item in items:
            if isinstance(item, tuple):
                combo.addItem(item[0], item[1])
            else:
                combo.addItem(item, item)
        combo.blockSignals(False)
        index = combo.findData(prefer) if prefer is not None else -1
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.setEnabled(True)

    def _on_data_changed(self):
        self._refresh_field_choices()
        self._load_selected()

    def _display_path(self, source_path):
        """栅格若有预处理对齐结果，优先用对齐后的文件。"""
        if not source_path:
            return ""
        if Path(source_path).suffix.lower() not in {".tif", ".tiff", ".img", ".asc"}:
            return source_path
        manifest = RasterPreprocessor(self.store.project_dir).latest_manifest() or {}
        for item in manifest.get("processed", []):
            if (item.get("source_path") == source_path
                    and Path(item.get("aligned_path", "")).exists()):
                return item["aligned_path"]
        return source_path

    # ------------------------------------------------------------------ #
    # 加载
    # ------------------------------------------------------------------ #
    def _target_crs(self, path_a, kind_a):
        """对比统一用的目标坐标系：优先取 A 侧的坐标系。"""
        try:
            if kind_a == "矢量":
                from ...widgets.swipe_layers import vector_crs
                return vector_crs(path_a)
            import rasterio
            with rasterio.open(path_a) as source:
                return source.crs.to_string() if source.crs else ""
        except Exception:  # noqa: BLE001 - 读不到就交给下面按各自坐标系处理
            return ""

    def _spec(self, kind_combo, data_combo, field_combo, method_combo, target_crs):
        path = self._display_path(data_combo.currentData())
        return {
            "kind": "raster" if kind_combo.currentText() == "栅格" else "vector",
            "path": path,
            "target_crs": target_crs,
            "field": field_combo.currentData() or "",
            "method": method_combo.currentText(),
            "n_classes": 5,
        }

    def _load_selected(self):
        """参数变化：延迟合并后再真正加载。"""
        self._load_timer.start()

    def _start_load(self):
        data_a, data_b = self.combo_a.currentData(), self.combo_b.currentData()
        if not data_a or not data_b:
            self.raster_canvas.clear()
            self.compare_status.setText("请先在「数据管理」导入要对比的数据")
            return
        path_a = self._display_path(data_a)
        target_crs = self._target_crs(path_a, self.kind_a.currentText())
        spec_a = self._spec(self.kind_a, self.combo_a, self.field_a, self.method_a, target_crs)
        spec_b = self._spec(self.kind_b, self.combo_b, self.field_b, self.method_b, target_crs)

        # 允许同一份数据的不同字段互比（如同一批多边形上的两个人口字段）。
        # 真正要比的是两份「图层配置」，配置完全一样才没有可比内容。
        if spec_a == spec_b:
            self.raster_canvas.clear()
            if data_a == data_b:
                self.compare_status.setText(
                    "两侧选择完全相同；同一份数据请为两侧指定不同的字段"
                    if spec_a["kind"] == "vector" else
                    "同一幅栅格是单波段数据，没有可对比的字段"
                )
            else:
                self.compare_status.setText("请选择两个不同的数据集")
            return
        specs = (tuple(sorted(spec_a.items())), tuple(sorted(spec_b.items())))
        if specs == self._last_specs and not self.raster_canvas.is_stale():
            return  # 参数没变，不重复跑一遍完整准备
        self._last_specs = specs
        self.compare_status.setText("正在准备对比图层（十几万要素需要数秒）…")
        self.raster_canvas.load(spec_a, spec_b)

    def _on_loaded(self, error):
        if error:
            self.compare_status.setText(f"无法对比：{error}")
            return
        names = self.raster_canvas.layer_names()
        self.compare_status.setText(
            f"已加载：左 {names[0]} ｜ 右 {names[1]}　拖动中央分割线左右对比，可滚轮缩放、拖拽平移"
        )
