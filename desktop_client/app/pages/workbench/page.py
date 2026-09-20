"""工作台页：模型参数设置 + 运行 + 结果地图/散点图 + 属性表。"""
import shutil
from pathlib import Path

from ...qt_compat import (
    QCheckBox,
    QColor,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPalette,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from ...widgets import ChartWindow, DroppableTable, MapCanvas, ScatterCanvas, clear_layout, fill_table, panel_box
from core.io.readers import read_attributes, read_unique_values
from core.models import AnalysisParameters, AnalysisResult, RasterAnalysisParameters
from core.raster_processing import RasterPreprocessor
from core.symbology import FIELD_INFO, auto_colors, classify


class InfoIcon(QLabel):
    """小问号图标：鼠标进入立即显示提示，移出立即隐藏。"""

    def __init__(self, parent=None):
        super().__init__("?", parent)
        self.setFixedSize(16, 16)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setStyleSheet(
            "border: 1px solid #9fb3ad; border-radius: 8px; color: #6b7f7b; font-weight: 700; font-size: 10px;"
        )
        self._info = ""

    def set_info(self, text):
        self._info = text

    def enterEvent(self, event):
        if self._info:
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self._info, self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class NoWheelComboBox(QComboBox):
    """工作台下拉框不因鼠标滚轮经过而切换选项。"""

    def wheelEvent(self, event):
        event.ignore()


class WorkbenchPage(QWidget):
    """设置 GWR 模型参数并运行；分析视图与属性表视图两个页签可随时切换。"""

    runRequested = Signal(dict)
    statusMessage = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.latest_result = AnalysisResult()
        self.map_canvas = None
        self.attr_hint = None
        self.result_table = None
        self.save_shp_button = None
        self._result_output_shp = ""
        self._map_path = None
        self._map_geometry = None
        self._map_fields = []
        self._map_values = {}
        self.field_info_label = None
        self._chart_window = None
        self.raster_list = None
        self.raster_options = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._analysis_view(), "分析")
        self.tabs.addTab(self._attribute_view(), "属性表")
        root.addWidget(self.tabs, 1)

    def _analysis_view(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(12)

        # 左：地图（占满整列）
        top.addWidget(self._map_panel(), 1)

        # 右：模型参数（滚动条）+ 分层设色
        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(self._parameter_panel(), 1)
        right.addWidget(self._symbology_panel())
        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setFixedWidth(360)
        top.addWidget(right_widget)

        layout.addLayout(top, 1)
        return container

    def _attribute_view(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.attr_hint = QLabel("拖动左侧数据到此处，查看对应属性表")
        self.attr_hint.setObjectName("Muted")
        header.addWidget(self.attr_hint, 1)
        self.save_shp_button = QPushButton("另存为 SHP…")
        self.save_shp_button.setObjectName("OutlineButton")
        self.save_shp_button.clicked.connect(self._save_result_shp)
        header.addWidget(self.save_shp_button)
        layout.addLayout(header)

        self.result_table = DroppableTable(0, 0)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.sourceDropped.connect(self._load_source_table)
        layout.addWidget(self.result_table, 1)
        return container

    def _map_panel(self):
        panel, body = panel_box("RESULT MAP", "小地图", "局部 R²")
        self.map_canvas = MapCanvas()
        self.map_canvas.sourceDropped.connect(self.load_shp)
        self.map_canvas.featureClicked.connect(self._on_map_feature_clicked)
        self.map_canvas.rasterLoaded.connect(self._on_map_raster_loaded)
        body.addWidget(self.map_canvas, 1)
        hint_row = QHBoxLayout()
        hint = QLabel("滚轮缩放 · 拖拽平移 · 双击复位 · 拖入 SHP/栅格显示")
        hint.setObjectName("Muted")
        hint_row.addWidget(hint, 1)
        chart_button = QPushButton("打开图表（散点 / 直方图）")
        chart_button.setObjectName("OutlineButton")
        chart_button.clicked.connect(self._open_chart_window)
        hint_row.addWidget(chart_button)
        body.addLayout(hint_row)
        return panel

    def _symbology_panel(self):
        panel, body = panel_box("SYMBOLOGY", "分层设色", "分级渲染")
        body.setSpacing(8)

        field_label_row = QHBoxLayout()
        label = QLabel("设色字段")
        label.setObjectName("Muted")
        field_label_row.addWidget(label)
        self.field_info_label = InfoIcon()
        self.field_info_label.set_info("鼠标悬停查看设色字段含义与分级配色说明")
        field_label_row.addWidget(self.field_info_label)
        field_label_row.addStretch()
        body.addLayout(field_label_row)

        self.symbology_field_combo = QComboBox()
        self.symbology_field_combo.setFixedHeight(32)
        self._style_combo(self.symbology_field_combo)
        body.addWidget(self.symbology_field_combo)

        self.symbology_method_combo = self._add_select(body, "分类方法", ["自然间断点", "等间隔", "分位数", "手动"])

        row = QHBoxLayout()
        label = QLabel("分级数")
        label.setObjectName("Muted")
        row.addWidget(label)
        self.symbology_classes_spin = QSpinBox()
        self.symbology_classes_spin.setRange(2, 10)
        self.symbology_classes_spin.setValue(5)
        self.symbology_classes_spin.setFixedHeight(32)
        row.addWidget(self.symbology_classes_spin)
        row.addStretch()
        body.addLayout(row)

        self.manual_breaks_input = QLineEdit()
        self.manual_breaks_input.setPlaceholderText("逗号分隔断点，如 0, 10, 50, 100")
        self.manual_breaks_input.hide()
        body.addWidget(self.manual_breaks_input)

        self.legend_layout = QVBoxLayout()
        self.legend_layout.setSpacing(4)
        body.addLayout(self.legend_layout)

        self.symbology_field_combo.currentTextChanged.connect(self._apply_symbology)
        self.symbology_field_combo.currentTextChanged.connect(self._update_field_tooltip)
        self.symbology_method_combo.currentTextChanged.connect(self._on_method_changed)
        self.symbology_classes_spin.valueChanged.connect(self._apply_symbology)
        self.manual_breaks_input.editingFinished.connect(self._apply_symbology)
        return panel

    def _parameter_panel(self):
        panel, body = panel_box("GWR MODEL", "模型参数", scrollable=True)
        for scroll in panel.findChildren(QScrollArea):
            scroll.setStyleSheet(
                "QScrollBar:vertical { width: 7px; margin: 2px 1px 2px 1px; }"
                "QScrollBar::handle:vertical { min-height: 28px; background: #b8c9c5; border-radius: 3px; }"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
                "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
            )
        body.setSpacing(10)

        self.attribute_options = QWidget()
        attribute_layout = QVBoxLayout(self.attribute_options)
        attribute_layout.setContentsMargins(0, 0, 0, 0)
        attribute_layout.setSpacing(10)
        self.y_combo = self._add_select(attribute_layout, "因变量 Y")
        self.x_combo = self._add_select(attribute_layout, "自变量 X")
        self.kernel_combo = self._add_select(attribute_layout, "核函数", ["双平方核", "高斯核", "指数核"])

        label = QLabel("带宽")
        label.setObjectName("Muted")
        attribute_layout.addWidget(label)
        bw_row = QHBoxLayout()
        self.bandwidth_input = QLineEdit("25")
        self.bandwidth_input.setFixedWidth(80)
        self.bandwidth_input.setFixedHeight(32)
        self.bw_unit = QLabel("近邻")
        self.bw_unit.setObjectName("Muted")
        bw_row.addWidget(self.bandwidth_input)
        bw_row.addWidget(self.bw_unit)
        self.auto_bandwidth = QCheckBox("自动（AIC）")
        bw_row.addWidget(self.auto_bandwidth)
        bw_row.addStretch()
        attribute_layout.addLayout(bw_row)

        self.bandwidth_mode_combo = self._add_select(attribute_layout, "带宽含义", ["最近邻个数", "距离（米）"])
        body.addWidget(self.attribute_options)
        self.backend_combo = self._add_select(
            body, "算法后端",
            ["R 属性 GWR", "栅格 R / terra"],
        )
        self.backend_combo.addItem("外接矩形法几何交叉验证")
        self.raster_options = QWidget()
        raster_layout = QVBoxLayout(self.raster_options)
        raster_layout.setContentsMargins(0, 8, 0, 0)
        raster_layout.setSpacing(8)
        raster_layout.addWidget(QLabel("分析栅格（至少选择两个）"), 0, Qt.AlignmentFlag.AlignLeft)
        self.raster_list = QListWidget()
        self.raster_list.setMinimumHeight(130)
        self.raster_list.setMaximumHeight(220)
        raster_layout.addWidget(self.raster_list)
        raster_layout.addWidget(QLabel("局部窗口大小"), 0, Qt.AlignmentFlag.AlignLeft)
        self.raster_window_spin = QSpinBox()
        self.raster_window_spin.setRange(3, 99)
        self.raster_window_spin.setSingleStep(2)
        self.raster_window_spin.setValue(5)
        raster_layout.addWidget(self.raster_window_spin)
        raster_layout.addWidget(QLabel("重采样方法"), 0, Qt.AlignmentFlag.AlignLeft)
        self.raster_resampling_combo = NoWheelComboBox()
        self.raster_resampling_combo.addItems(["bilinear", "near", "cubic"])
        self.raster_resampling_combo.setFixedHeight(32)
        self._style_combo(self.raster_resampling_combo)
        raster_layout.addWidget(self.raster_resampling_combo)
        raster_layout.addWidget(QLabel("相对误差零值阈值"), 0, Qt.AlignmentFlag.AlignLeft)
        self.raster_epsilon_spin = QDoubleSpinBox()
        self.raster_epsilon_spin.setDecimals(12)
        self.raster_epsilon_spin.setRange(0.0, 1.0)
        self.raster_epsilon_spin.setSingleStep(1e-12)
        self.raster_epsilon_spin.setValue(1e-12)
        raster_layout.addWidget(self.raster_epsilon_spin)
        self.raster_local_checkbox = QCheckBox("输出局部 GeoTIFF")
        self.raster_local_checkbox.setChecked(True)
        raster_layout.addWidget(self.raster_local_checkbox)
        self.raster_scatter_checkbox = QCheckBox("输出像元散点图")
        self.raster_scatter_checkbox.setChecked(True)
        raster_layout.addWidget(self.raster_scatter_checkbox)
        body.addWidget(self.raster_options)

        self.geometry_options = QWidget()
        geometry_layout = QVBoxLayout(self.geometry_options)
        geometry_layout.setContentsMargins(0, 8, 0, 0)
        geometry_layout.setSpacing(8)
        self.geometry_a_combo = self._add_select(geometry_layout, "几何数据 A")
        self.geometry_b_combo = self._add_select(geometry_layout, "几何数据 B")
        self.geometry_a_field_combo = self._add_select(geometry_layout, "A 类别字段")
        self.geometry_b_field_combo = self._add_select(geometry_layout, "B 类别字段")
        mapping_hint = QLabel("类别映射（双击单元格可修改；取消勾选可排除类别）")
        mapping_hint.setObjectName("Muted")
        mapping_hint.setWordWrap(True)
        geometry_layout.addWidget(mapping_hint)
        self.geometry_mapping_table = QTableWidget(0, 4)
        self.geometry_mapping_table.setHorizontalHeaderLabels(["使用", "A 值", "B 值", "显示名称"])
        self.geometry_mapping_table.verticalHeader().setVisible(False)
        self.geometry_mapping_table.setMinimumHeight(150)
        self.geometry_mapping_table.setColumnWidth(0, 48)
        self.geometry_mapping_table.setColumnWidth(1, 70)
        self.geometry_mapping_table.setColumnWidth(2, 70)
        self.geometry_mapping_table.setColumnWidth(3, 105)
        geometry_layout.addWidget(self.geometry_mapping_table)
        self.geometry_crs_input = QLineEdit("EPSG:32650")
        geometry_layout.addWidget(QLabel("计算投影 CRS"))
        geometry_layout.addWidget(self.geometry_crs_input)
        self.geometry_min_area_spin = QDoubleSpinBox()
        self.geometry_min_area_spin.setRange(0, 1_000_000_000)
        self.geometry_min_area_spin.setDecimals(2)
        self.geometry_min_area_spin.setSuffix(" m²")
        geometry_layout.addWidget(QLabel("最小面积阈值"))
        geometry_layout.addWidget(self.geometry_min_area_spin)
        self.geometry_thresholds_input = QLineEdit("0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9")
        geometry_layout.addWidget(QLabel("外接矩形 IoU 阈值"))
        geometry_layout.addWidget(self.geometry_thresholds_input)
        self.geometry_bandwidth_spin = QDoubleSpinBox()
        self.geometry_bandwidth_spin.setRange(1, 1_000_000)
        self.geometry_bandwidth_spin.setValue(5000)
        self.geometry_bandwidth_spin.setSuffix(" m")
        geometry_layout.addWidget(QLabel("地理加权带宽"))
        geometry_layout.addWidget(self.geometry_bandwidth_spin)
        geometry_layout.addWidget(QLabel("输出目录（留空则使用项目运行目录）"))
        output_row = QHBoxLayout()
        self.geometry_output_input = QLineEdit()
        output_row.addWidget(self.geometry_output_input, 1)
        output_button = QPushButton("浏览…")
        output_button.clicked.connect(self._browse_geometry_output)
        output_row.addWidget(output_button)
        geometry_layout.addLayout(output_row)
        self.geometry_report_checkbox = QCheckBox("生成综合报告")
        self.geometry_report_checkbox.setChecked(True)
        self.geometry_figures_checkbox = QCheckBox("生成 4 张 3×3 综合图")
        self.geometry_figures_checkbox.setChecked(True)
        geometry_layout.addWidget(self.geometry_report_checkbox)
        geometry_layout.addWidget(self.geometry_figures_checkbox)
        self.geometry_validation_label = QLabel("等待配置校验")
        self.geometry_validation_label.setWordWrap(True)
        self.geometry_validation_label.setObjectName("Muted")
        geometry_layout.addWidget(self.geometry_validation_label)
        body.addWidget(self.geometry_options)
        self.geometry_options.hide()

        self.geometry_a_combo.currentIndexChanged.connect(self._refresh_geometry_fields)
        self.geometry_b_combo.currentIndexChanged.connect(self._refresh_geometry_fields)
        self.geometry_a_field_combo.currentTextChanged.connect(self._refresh_geometry_mapping)
        self.geometry_b_field_combo.currentTextChanged.connect(self._refresh_geometry_mapping)
        self.backend_combo.currentTextChanged.connect(self._toggle_raster_options)
        self._refresh_raster_options()
        self._toggle_raster_options(self.backend_combo.currentText())
        self.save_result_shp = QCheckBox("运行后生成结果 SHP")
        self.save_result_shp.setChecked(True)
        body.addWidget(self.save_result_shp)
        self._refresh_variable_options()
        self.bandwidth_mode_combo.currentTextChanged.connect(self._update_bandwidth_unit)
        self._update_bandwidth_unit()

        # 运行按钮固定在滚动区外，始终可见
        run_button = QPushButton("▶ 运行")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(self.run)
        self.run_button = run_button
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 4, 18, 14)
        footer_layout.addWidget(run_button)
        panel.layout().addWidget(footer)
        return panel

    def _add_select(self, body, label_text, items=None):
        label = QLabel(label_text)
        label.setObjectName("Muted")
        body.addWidget(label)
        combo = NoWheelComboBox()
        combo.setFixedHeight(32)
        if items:
            combo.addItems(items)
        self._style_combo(combo)
        body.addWidget(combo)
        return combo

    @staticmethod
    def _style_combo(combo):
        palette = combo.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#26363c"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#26363c"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#e3f3ef"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1f695e"))
        combo.setPalette(palette)
        view = combo.view()
        view.setPalette(palette)
        view.setStyleSheet(
            "QAbstractItemView { background: #ffffff; color: #26363c; "
            "selection-background-color: #e3f3ef; selection-color: #1f695e; }"
        )

    def _update_bandwidth_unit(self, *_):
        if self.bandwidth_mode_combo.currentText() == "距离（米）":
            self.bw_unit.setText("米")
        else:
            self.bw_unit.setText("近邻")

    @staticmethod
    def _set_combo(combo, text):
        if text and combo.findText(text) >= 0:
            combo.setCurrentText(text)

    def get_symbology_state(self):
        return {
            "symbology_field": self.symbology_field_combo.currentText(),
            "symbology_method": self.symbology_method_combo.currentText(),
            "symbology_classes": self.symbology_classes_spin.value(),
        }

    def render_scatter_png(self, shp_path, x_field, y_field, out_path):
        """把 X vs Y 散点图渲染成 PNG 图片，返回是否成功。"""
        from core.io.readers import read_attributes
        data = read_attributes(shp_path, limit=0)
        fields = data["fields"]
        if x_field not in fields or y_field not in fields:
            return False
        ix, iy = fields.index(x_field), fields.index(y_field)
        xs, ys = [], []
        for row in data["rows"]:
            x, y = row[ix], row[iy]
            if x is not None and y is not None and isinstance(x, (int, float)) and isinstance(y, (int, float)):
                xs.append(x)
                ys.append(y)
        if len(xs) < 2:
            return False
        canvas = ScatterCanvas()
        canvas.setStyleSheet("font-size: 18px;")
        canvas.resize(1400, 1400)
        canvas.set_data(xs, ys, x_field, y_field)
        return canvas.grab().save(out_path, "PNG")

    def restore_run(self, run):
        p = run.parameters
        # 1. 加载结果 SHP（含结果列，方便分层设色），否则加载源 SHP
        result_shp = getattr(run.result, "output_shp", "") or ""
        load_path = result_shp if (result_shp and Path(result_shp).exists()) else run.shp_path
        if load_path:
            self.load_shp(load_path)
        # 2. 参数面板回填
        self._set_combo(self.x_combo, p.get("independent_variable", ""))
        self._set_combo(self.y_combo, p.get("dependent_variable", ""))
        self._set_combo(self.kernel_combo, p.get("kernel", "双平方核"))
        self.bandwidth_input.setText(str(p.get("bandwidth", "25")))
        self.auto_bandwidth.setChecked(bool(p.get("auto_bandwidth", False)))
        self._set_combo(self.bandwidth_mode_combo, p.get("bandwidth_mode", "最近邻个数"))
        self._set_combo(self.backend_combo, p.get("backend", "R 属性 GWR"))
        self.save_result_shp.setChecked(bool(p.get("write_shp", True)))
        self._update_bandwidth_unit()
        # 3. 设色还原
        if run.symbology_field:
            self._set_combo(self.symbology_field_combo, run.symbology_field)
        self._set_combo(self.symbology_method_combo, run.symbology_method)
        self.symbology_classes_spin.setValue(run.symbology_classes)
        self._apply_symbology()
        # 4. 结果回填属性表
        self.latest_result = run.result
        self._result_output_shp = getattr(run.result, "output_shp", "") or ""
        if run.result.local_columns and run.shp_path:
            self._show_results(run.shp_path, run.result.local_columns)
        self.tabs.setCurrentIndex(0)

    def _refresh_variable_options(self):
        """根据已导入数据的字段刷新 Y / X 变量下拉框。"""
        fields = []
        for source in self.store.sources:
            for field in source.fields:
                if field not in fields:
                    fields.append(field)
        if not fields:
            fields = ["pop2024", "worldpop"]
        for combo in (self.y_combo, self.x_combo):
            current = combo.currentText()
            combo.clear()
            combo.addItems(fields)
            if current:
                index = combo.findText(current)
                if index >= 0:
                    combo.setCurrentIndex(index)

    def _refresh_raster_options(self):
        if self.raster_list is None:
            return
        current_selected = self._selected_raster_paths()
        manifest = RasterPreprocessor(self.store.project_dir).latest_manifest() or {}
        if not current_selected:
            current_selected = set(manifest.get("selected_sources", []))
        raster_sources = [
            source for source in self.store.sources
            if "栅格" in source.data_type or Path(source.path).suffix.lower() in {".tif", ".tiff", ".img", ".asc"}
        ]
        if not current_selected:
            current_selected = {source.path for source in raster_sources}
        self.raster_list.blockSignals(True)
        self.raster_list.clear()
        for source in raster_sources:
            item = QListWidgetItem(f"{source.icon}  {source.name} · {source.records}")
            item.setData(Qt.ItemDataRole.UserRole, source.path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if source.path in current_selected else Qt.CheckState.Unchecked
            )
            self.raster_list.addItem(item)
        self.raster_list.blockSignals(False)

    def _selected_raster_paths(self):
        if self.raster_list is None:
            return []
        return [
            self.raster_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.raster_list.count())
            if self.raster_list.item(index).checkState() == Qt.CheckState.Checked
        ]

    def _refresh_geometry_sources(self):
        sources = [s for s in self.store.sources if Path(s.path).suffix.lower() == ".shp"]
        previous_a = self.geometry_a_combo.currentData()
        previous_b = self.geometry_b_combo.currentData()
        for combo in (self.geometry_a_combo, self.geometry_b_combo):
            combo.blockSignals(True)
            combo.clear()
            for source in sources:
                combo.addItem(source.name, source.path)
            combo.blockSignals(False)
        if previous_a and self.geometry_a_combo.findData(previous_a) >= 0:
            self.geometry_a_combo.setCurrentIndex(self.geometry_a_combo.findData(previous_a))
        if previous_b and self.geometry_b_combo.findData(previous_b) >= 0:
            self.geometry_b_combo.setCurrentIndex(self.geometry_b_combo.findData(previous_b))
        elif self.geometry_b_combo.count() > 1:
            self.geometry_b_combo.setCurrentIndex(1)
        self._refresh_geometry_fields()

    def _source_for_path(self, path):
        return next((source for source in self.store.sources if source.path == path), None)

    def _refresh_geometry_fields(self, *_):
        for source_combo, field_combo in (
            (self.geometry_a_combo, self.geometry_a_field_combo),
            (self.geometry_b_combo, self.geometry_b_field_combo),
        ):
            current = field_combo.currentText()
            source = self._source_for_path(source_combo.currentData())
            field_combo.blockSignals(True)
            field_combo.clear()
            if source:
                field_combo.addItems(source.fields)
            preferred = field_combo.findText("gridcode", Qt.MatchFlag.MatchFixedString)
            if current and field_combo.findText(current) >= 0:
                field_combo.setCurrentText(current)
            elif preferred >= 0:
                field_combo.setCurrentIndex(preferred)
            field_combo.blockSignals(False)
        self._refresh_geometry_mapping()

    @staticmethod
    def _value_sort_key(value):
        try:
            return (0, float(value))
        except (TypeError, ValueError):
            return (1, str(value))

    def _refresh_geometry_mapping(self, *_):
        path_a = self.geometry_a_combo.currentData()
        path_b = self.geometry_b_combo.currentData()
        field_a = self.geometry_a_field_combo.currentText()
        field_b = self.geometry_b_field_combo.currentText()
        values_a = sorted(read_unique_values(path_a, field_a), key=self._value_sort_key) if path_a and field_a else []
        values_b = sorted(read_unique_values(path_b, field_b), key=self._value_sort_key) if path_b and field_b else []
        common = sorted(set(values_a) & set(values_b), key=self._value_sort_key)
        rest_a = [value for value in values_a if value not in common]
        rest_b = [value for value in values_b if value not in common]
        pairs = [(value, value) for value in common]
        pairs.extend(
            (rest_a[index] if index < len(rest_a) else "", rest_b[index] if index < len(rest_b) else "")
            for index in range(max(len(rest_a), len(rest_b)))
        )
        self.geometry_mapping_table.setRowCount(len(pairs))
        for row, (value_a, value_b) in enumerate(pairs):
            enabled = QTableWidgetItem()
            enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            enabled.setCheckState(Qt.CheckState.Checked if value_a and value_b else Qt.CheckState.Unchecked)
            self.geometry_mapping_table.setItem(row, 0, enabled)
            self.geometry_mapping_table.setItem(row, 1, QTableWidgetItem(value_a))
            self.geometry_mapping_table.setItem(row, 2, QTableWidgetItem(value_b))
            label = value_a if value_a == value_b else f"{value_a} ↔ {value_b}".strip()
            self.geometry_mapping_table.setItem(row, 3, QTableWidgetItem(label))

    def _browse_geometry_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择几何分析输出目录")
        if path:
            self.geometry_output_input.setText(path)

    def _geometry_parameters(self):
        path_a = self.geometry_a_combo.currentData() or ""
        path_b = self.geometry_b_combo.currentData() or ""
        if not path_a or not path_b:
            return None, "请先导入并选择两个 SHP 数据"
        if path_a == path_b:
            return None, "几何数据 A 和 B 不能是同一个文件"
        field_a = self.geometry_a_field_combo.currentText().strip()
        field_b = self.geometry_b_field_combo.currentText().strip()
        if not field_a or not field_b:
            return None, "请分别选择 A 和 B 的类别字段"
        mappings = []
        for row in range(self.geometry_mapping_table.rowCount()):
            enabled = self.geometry_mapping_table.item(row, 0)
            if enabled is None or enabled.checkState() != Qt.CheckState.Checked:
                continue
            value_a = (self.geometry_mapping_table.item(row, 1).text() if self.geometry_mapping_table.item(row, 1) else "").strip()
            value_b = (self.geometry_mapping_table.item(row, 2).text() if self.geometry_mapping_table.item(row, 2) else "").strip()
            label = (self.geometry_mapping_table.item(row, 3).text() if self.geometry_mapping_table.item(row, 3) else "").strip()
            if not value_a or not value_b:
                return None, f"第 {row + 1} 行已启用，但 A/B 类别值不完整"
            mappings.append({"a_value": value_a, "b_value": value_b, "label": label or f"{value_a}-{value_b}"})
        if not mappings:
            return None, "至少需要启用一组类别映射"
        if len({m["a_value"] for m in mappings}) != len(mappings) or len({m["b_value"] for m in mappings}) != len(mappings):
            return None, "启用的类别映射中存在重复的 A 值或 B 值"
        try:
            thresholds = [float(value.strip()) for value in self.geometry_thresholds_input.text().split(",") if value.strip()]
        except ValueError:
            return None, "IoU 阈值必须是用英文逗号分隔的数字"
        if len(thresholds) != 9 or len(set(thresholds)) != 9 or any(value <= 0 or value > 1 for value in thresholds):
            return None, "3×3 图要求填写 9 个不重复且位于 (0, 1] 的 IoU 阈值"
        crs = self.geometry_crs_input.text().strip()
        if not crs:
            return None, "计算投影 CRS 不能为空"
        return {
            "analysis_type": "geometry",
            "backend": "外接矩形法几何交叉验证",
            "geometry_a": path_a,
            "geometry_b": path_b,
            "category_field_a": field_a,
            "category_field_b": field_b,
            "category_mappings": mappings,
            "projected_crs": crs,
            "min_area_m2": self.geometry_min_area_spin.value(),
            "thresholds": sorted(thresholds),
            "bandwidth_m": self.geometry_bandwidth_spin.value(),
            "output_dir": self.geometry_output_input.text().strip(),
            "write_report": self.geometry_report_checkbox.isChecked(),
            "write_figures": self.geometry_figures_checkbox.isChecked(),
        }, ""

    def _toggle_raster_options(self, backend):
        is_raster = backend.startswith("栅格")
        is_geometry = backend == "外接矩形法几何交叉验证"
        self.raster_options.setVisible(is_raster)
        self.geometry_options.setVisible(is_geometry)
        self.attribute_options.setVisible(not is_raster and not is_geometry)
        if is_geometry:
            self._refresh_geometry_sources()
        save_result_shp = getattr(self, "save_result_shp", None)
        if save_result_shp is not None:
            save_result_shp.setVisible(not is_raster and not is_geometry)

    def collect_parameters(self) -> dict:
        if self.backend_combo.currentText() == "外接矩形法几何交叉验证":
            parameters, _ = self._geometry_parameters()
            return parameters or {}
        parameters = AnalysisParameters(
            dependent_variable=self.y_combo.currentText(),
            independent_variable=self.x_combo.currentText(),
            kernel=self.kernel_combo.currentText(),
            bandwidth=self.bandwidth_input.text(),
            bandwidth_mode=self.bandwidth_mode_combo.currentText(),
            backend=self.backend_combo.currentText(),
        ).to_dict()
        is_raster = self.backend_combo.currentText().startswith("栅格")
        parameters.update({
            "analysis_type": "raster" if is_raster else "attribute",
            "auto_bandwidth": self.auto_bandwidth.isChecked(),
            "write_shp": self.save_result_shp.isChecked(),
        })
        if is_raster:
            parameters.update(RasterAnalysisParameters(
                window_size=self.raster_window_spin.value(),
                resampling=self.raster_resampling_combo.currentText(),
                zero_epsilon=self.raster_epsilon_spin.value(),
                write_local_rasters=self.raster_local_checkbox.isChecked(),
                write_scatter_plot=self.raster_scatter_checkbox.isChecked(),
            ).to_dict())
            parameters["raster_paths"] = list(self._selected_raster_paths())
        return parameters

    def run(self):
        if not self.run_button.isEnabled():
            return
        if self.backend_combo.currentText() == "外接矩形法几何交叉验证":
            parameters, error = self._geometry_parameters()
            if error:
                self.geometry_validation_label.setText("配置错误：" + error)
                self.geometry_validation_label.setStyleSheet(
                    "padding: 7px; color: #a23b32; background: #fdecea; border-radius: 4px;"
                )
                self.statusMessage.emit(error)
                QMessageBox.warning(self, "几何配置检查", error)
            else:
                message = f"配置校验通过，正在提交 {len(parameters['category_mappings'])} 组类别进行计算…"
                self.geometry_validation_label.setText(message)
                self.geometry_validation_label.setStyleSheet(
                    "padding: 7px; color: #1f695e; background: #e3f3ef; border-radius: 4px;"
                )
                self.statusMessage.emit(message)
                self.set_run_busy(True)
                self.runRequested.emit(parameters)
            return
        self.set_run_busy(True)
        self.runRequested.emit(self.collect_parameters())

    def set_run_busy(self, busy):
        self.run_button.setEnabled(not busy)
        self.run_button.setText("⏳ 运行中…" if busy else "▶ 运行")
        self.run_button.setStyleSheet(
            "QPushButton { background: #9aa9a6; color: #ffffff; border: 0; }" if busy else ""
        )

    def load_shp(self, path, reset_xy=True):
        from core.io.readers import read_shapefile_geometry
        suffix = Path(path).suffix.lower()
        if suffix in {".tif", ".tiff", ".img", ".asc"}:
            self.map_canvas.load_raster(path)
            self.statusMessage.emit(f"正在加载栅格：{Path(path).name}")
            return
        if suffix != ".shp":
            self.statusMessage.emit("仅支持 SHP 或栅格（TIF/IMG/ASC）显示")
            return
        geometry = read_shapefile_geometry(path)
        if not geometry["geometries"]:
            self.statusMessage.emit("未能解析 SHP 几何（可能是不支持的几何类型）")
            return
        attrs = read_attributes(path, limit=0)
        self._map_path = path
        self._map_geometry = geometry
        self._map_fields = attrs["fields"]
        self._map_values = {f: [] for f in self._map_fields}
        for row in attrs["rows"]:
            for c, f in enumerate(self._map_fields):
                self._map_values[f].append(row[c] if c < len(row) else None)
        self.map_canvas.load_shapes(geometry)
        self._refresh_symbology_fields()
        if reset_xy:
            self._refresh_xy_from_map()
        self._refresh_chart_window()
        self.statusMessage.emit(f"已加载 {len(geometry['geometries']):,} 个几何要素到地图")

    def _on_map_raster_loaded(self, error):
        if error:
            self.statusMessage.emit(f"栅格打开失败：{error}")
        else:
            self.statusMessage.emit("栅格已加载到小地图")

    def _on_map_feature_clicked(self, fid):
        self.map_canvas.highlight_feature(fid)
        if self._chart_window is not None:
            self._chart_window.highlight_feature(fid)
        name = self._map_values.get("name", [])
        info = f"要素 #{fid}"
        if name and fid < len(name):
            info += f"（{name[fid]}）"
        self.statusMessage.emit(f"已高亮 {info}")

    def _on_chart_feature_selected(self, fid):
        self.map_canvas.highlight_feature(fid)
        name = self._map_values.get("name", [])
        info = f"要素 #{fid}"
        if name and fid < len(name):
            info += f"（{name[fid]}）"
        self.statusMessage.emit(f"已高亮 {info}")

    def _on_chart_selection_cleared(self):
        self.map_canvas.highlight_feature(None)
        self.statusMessage.emit("已取消高亮")

    def _open_chart_window(self):
        if self._chart_window is None:
            self._chart_window = ChartWindow()
            self._chart_window.featureSelected.connect(self._on_chart_feature_selected)
            self._chart_window.selectionCleared.connect(self._on_chart_selection_cleared)
        self._chart_window.update_data(self._map_fields, self._map_values)
        self._chart_window.show()
        self._chart_window.raise_()
        self._chart_window.activateWindow()

    def _refresh_chart_window(self):
        if self._chart_window is not None:
            self._chart_window.update_data(self._map_fields, self._map_values)

    def _refresh_xy_from_map(self):
        """拖入 SHP 后，把 X/Y 下拉框刷新为该文件的数值字段并自动选择。"""
        numeric = self._numeric_fields()
        if not numeric:
            return
        current_y = self.y_combo.currentText()
        current_x = self.x_combo.currentText()
        for combo in (self.y_combo, self.x_combo):
            combo.blockSignals(True)
        self.y_combo.clear()
        self.y_combo.addItems(numeric)
        self.x_combo.clear()
        self.x_combo.addItems(numeric)
        self.y_combo.setCurrentText(current_y if current_y in numeric else numeric[0])
        self.x_combo.setCurrentText(current_x if current_x in numeric else numeric[min(1, len(numeric) - 1)])
        for combo in (self.y_combo, self.x_combo):
            combo.blockSignals(False)

    def _numeric_fields(self):
        numeric = []
        for f in self._map_fields:
            vals = [v for v in self._map_values.get(f, []) if v is not None]
            if vals and all(isinstance(v, (int, float)) for v in vals):
                numeric.append(f)
        return numeric

    def _refresh_symbology_fields(self):
        numeric = self._numeric_fields()
        current = self.symbology_field_combo.currentText()
        self.symbology_field_combo.blockSignals(True)
        self.symbology_field_combo.clear()
        self.symbology_field_combo.addItems(numeric)
        self.symbology_field_combo.blockSignals(False)
        if current and current in numeric:
            self.symbology_field_combo.setCurrentText(current)
        self._update_field_tooltip()
        self._apply_symbology()

    def _apply_symbology(self):
        field = self.symbology_field_combo.currentText()
        if not field or field not in self._map_values:
            self.map_canvas.set_feature_colors([])
            self._clear_legend()
            return
        values = self._map_values[field]
        method = self.symbology_method_combo.currentText()
        n_classes = self.symbology_classes_spin.value()
        manual = self._parse_manual_breaks() if method == "手动" else None
        breaks, indices = classify(values, method, n_classes, manual)
        nc = len(breaks) - 1
        if nc <= 0:
            self.map_canvas.set_feature_colors([])
            self._clear_legend()
            return
        colors = auto_colors(values, nc)
        feature_colors = [None] * len(indices)
        for i, idx in enumerate(indices):
            if idx is not None and 0 <= idx < nc:
                feature_colors[i] = QColor(colors[idx])
        self.map_canvas.set_feature_colors(feature_colors)
        self._update_legend(breaks, colors)

    def _on_method_changed(self, method):
        self.manual_breaks_input.setVisible(method == "手动")
        self.symbology_classes_spin.setEnabled(method != "手动")
        self._apply_symbology()

    def _update_field_tooltip(self, field=None):
        if field is None:
            field = self.symbology_field_combo.currentText()
        if not field or field not in self._map_values:
            self.field_info_label.set_info("鼠标悬停查看设色字段含义与分级配色说明")
            return
        meaning, level_hint = FIELD_INFO.get(field, ("该字段暂无说明", "颜色越深代表数值越大"))
        vals = [v for v in self._map_values[field] if v is not None]
        if vals and min(vals) < 0:
            ramp_hint = "发散色带：蓝色=负值，白色≈0，红色=正值"
        else:
            ramp_hint = "单色渐变：颜色越深，数值越大"
        self.field_info_label.set_info(
            f"字段：{field}\n含义：{meaning}\n分级解读：{level_hint}\n配色：{ramp_hint}"
        )

    def _parse_manual_breaks(self):
        text = self.manual_breaks_input.text().strip()
        if not text:
            return None
        parts = [p.strip() for p in text.replace("，", ",").split(",") if p.strip()]
        try:
            return [float(p) for p in parts]
        except ValueError:
            return None

    def _update_legend(self, breaks, colors):
        clear_layout(self.legend_layout)
        for i in range(len(breaks) - 1):
            row = QHBoxLayout()
            swatch = QLabel(" ")
            swatch.setFixedSize(18, 14)
            swatch.setStyleSheet(f"background: {colors[i]}; border: 1px solid #cbd5d2; border-radius: 2px;")
            row.addWidget(swatch)
            label = QLabel(f"{self._fmt_number(breaks[i])} – {self._fmt_number(breaks[i + 1])}")
            label.setObjectName("Muted")
            row.addWidget(label, 1)
            self.legend_layout.addLayout(row)

    def _clear_legend(self):
        clear_layout(self.legend_layout)

    @staticmethod
    def _fmt_number(v):
        if isinstance(v, float):
            if abs(v - round(v)) < 1e-9:
                return str(int(round(v)))
            return f"{v:.4g}"
        return str(v)

    def _load_source_table(self, path):
        data = read_attributes(path, limit=20000)
        fields = data["fields"]
        rows = data["rows"]
        name = Path(path).stem
        if not fields:
            self.result_table.clear()
            self.result_table.setRowCount(0)
            self.result_table.setColumnCount(0)
            self.attr_hint.setText(f"无法读取属性表：{path}")
            self.statusMessage.emit(f"无法读取属性表：{path}")
            return
        note = f"{name}：{len(rows)} 行 · {len(fields)} 字段"
        if data["truncated"]:
            note += "（已截断）"
        fill_table(self.result_table, fields, rows)
        self.attr_hint.setText(note)
        self.statusMessage.emit(f"已加载属性表：{note}")

    def _show_results(self, shp_path, columns):
        """把 GWR 结果列追加到原始属性表后展示。"""
        data = read_attributes(shp_path, limit=20000)
        fields = data["fields"]
        rows = data["rows"]
        name = Path(shp_path).stem
        specs = [
            ("local_r2", "局部 R²"),
            ("coefficient", "系数"),
            ("local_corr", "局部相关系数"),
            ("lme", "LME"),
            ("lmae", "LMAE"),
            ("lmre", "LMRE"),
            ("lrmse", "LRMSE"),
        ]
        for key, label in specs:
            values = columns.get(key)
            if values is None:
                continue
            fields.append(label)
            for i, row in enumerate(rows):
                row.append(values[i] if i < len(values) else None)
        fill_table(self.result_table, fields, rows)
        self.attr_hint.setText(f"{name}：{len(rows)} 行 · {len(fields)} 字段（含 GWR 结果列）")

    def _save_result_shp(self):
        src = self._result_output_shp
        if not src or not Path(src).exists():
            self.statusMessage.emit("没有可保存的结果 SHP（请先运行分析并勾选“运行后生成结果 SHP”）")
            return
        dest, _ = QFileDialog.getSaveFileName(self, "保存结果 Shapefile", "", "Shapefile (*.shp)")
        if not dest:
            return
        dest = Path(dest)
        if dest.suffix.lower() != ".shp":
            dest = dest.with_suffix(".shp")
        src_path = Path(src)
        try:
            for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                s = src_path.with_suffix(ext)
                if s.exists():
                    shutil.copy2(s, dest.with_suffix(ext))
            self.statusMessage.emit(f"结果已保存：{dest}")
        except OSError as exc:
            self.statusMessage.emit(f"保存失败：{exc}")

    def update_result(self, result: AnalysisResult, shp_path=None):
        self.set_run_busy(False)
        self.latest_result = result
        if self.backend_combo.currentText() == "外接矩形法几何交叉验证":
            if result.status == "error":
                self.geometry_validation_label.setText("计算失败：" + result.message)
                self.geometry_validation_label.setStyleSheet(
                    "padding: 7px; color: #a23b32; background: #fdecea; border-radius: 4px;"
                )
            else:
                self.geometry_validation_label.setText(result.message)
                self.geometry_validation_label.setStyleSheet(
                    "padding: 7px; color: #1f695e; background: #e3f3ef; border-radius: 4px;"
                )
        self._result_output_shp = getattr(result, "output_shp", "") or ""
        if shp_path and result.status == "success" and result.local_columns:
            self._show_results(shp_path, result.local_columns)
            self.tabs.setCurrentIndex(1)
        self.statusMessage.emit(result.message)

    def update_after_data_change(self):
        self._refresh_raster_options()
        if hasattr(self, "geometry_a_combo"):
            self._refresh_geometry_sources()
