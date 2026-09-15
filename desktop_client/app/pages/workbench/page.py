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
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from ...widgets import ChartWindow, DroppableTable, MapCanvas, clear_layout, fill_table, panel_box
from core.io.readers import read_attributes
from core.models import AnalysisParameters, AnalysisResult, RasterAnalysisParameters
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
        self.raster_reference_combo = None
        self.raster_comparison_combo = None
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
        right_widget.setFixedWidth(300)
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
        body.addWidget(self.map_canvas, 1)
        hint_row = QHBoxLayout()
        hint = QLabel("滚轮缩放 · 拖拽平移 · 双击复位 · 拖入 SHP 显示几何")
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
        body.setSpacing(10)

        self.y_combo = self._add_select(body, "因变量 Y")
        self.x_combo = self._add_select(body, "自变量 X")
        self.kernel_combo = self._add_select(body, "核函数", ["双平方核", "高斯核", "指数核"])

        label = QLabel("带宽")
        label.setObjectName("Muted")
        body.addWidget(label)
        bw_row = QHBoxLayout()
        self.bandwidth_input = QLineEdit("25")
        self.bandwidth_input.setFixedWidth(80)
        self.bandwidth_input.setFixedHeight(32)
        bw_unit = QLabel("近邻")
        bw_unit.setObjectName("Muted")
        bw_row.addWidget(self.bandwidth_input)
        bw_row.addWidget(bw_unit)
        self.auto_bandwidth = QCheckBox("自动（AIC）")
        bw_row.addWidget(self.auto_bandwidth)
        bw_row.addStretch()
        body.addLayout(bw_row)

        self.bandwidth_mode_combo = self._add_select(body, "带宽策略", ["自适应带宽", "固定带宽"])
        self.distance_combo = self._add_select(body, "距离度量", ["投影坐标距离（米）", "大圆距离（千米）"])
        self.backend_combo = self._add_select(
            body, "算法后端",
            ["Python 占位算法", "R 占位算法", "R 属性 GWR", "栅格 R / terra"],
        )
        self.raster_options = QWidget()
        raster_layout = QVBoxLayout(self.raster_options)
        raster_layout.setContentsMargins(0, 8, 0, 0)
        raster_layout.setSpacing(8)
        raster_layout.addWidget(QLabel("参考栅格"), 0, Qt.AlignmentFlag.AlignLeft)
        self.raster_reference_combo = QComboBox()
        self.raster_reference_combo.setFixedHeight(32)
        raster_layout.addWidget(self.raster_reference_combo)
        raster_layout.addWidget(QLabel("对比栅格"), 0, Qt.AlignmentFlag.AlignLeft)
        self.raster_comparison_combo = QComboBox()
        self.raster_comparison_combo.setFixedHeight(32)
        raster_layout.addWidget(self.raster_comparison_combo)
        raster_layout.addWidget(QLabel("局部窗口大小"), 0, Qt.AlignmentFlag.AlignLeft)
        self.raster_window_spin = QSpinBox()
        self.raster_window_spin.setRange(3, 99)
        self.raster_window_spin.setSingleStep(2)
        self.raster_window_spin.setValue(5)
        raster_layout.addWidget(self.raster_window_spin)
        raster_layout.addWidget(QLabel("重采样方法"), 0, Qt.AlignmentFlag.AlignLeft)
        self.raster_resampling_combo = QComboBox()
        self.raster_resampling_combo.addItems(["bilinear", "near", "cubic"])
        self.raster_resampling_combo.setFixedHeight(32)
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
        self.backend_combo.currentTextChanged.connect(self._toggle_raster_options)
        self._refresh_raster_options()
        self._toggle_raster_options(self.backend_combo.currentText())
        self.save_result_shp = QCheckBox("运行后生成结果 SHP")
        self.save_result_shp.setChecked(True)
        body.addWidget(self.save_result_shp)
        self._refresh_variable_options()

        # 运行按钮固定在滚动区外，始终可见
        run_button = QPushButton("▶ 运行")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(self.run)
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
        combo = QComboBox()
        combo.setFixedHeight(32)
        if items:
            combo.addItems(items)
        body.addWidget(combo)
        return combo

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
        if self.raster_reference_combo is None:
            return
        current_reference = self.raster_reference_combo.currentData()
        current_comparison = self.raster_comparison_combo.currentData()
        self.raster_reference_combo.clear()
        self.raster_comparison_combo.clear()
        raster_sources = [
            source for source in self.store.sources
            if "栅格" in source.data_type or Path(source.path).suffix.lower() in {".tif", ".tiff", ".img", ".asc"}
        ]
        for source in raster_sources:
            self.raster_reference_combo.addItem(source.name, source.path)
            self.raster_comparison_combo.addItem(source.name, source.path)
        if current_reference:
            index = self.raster_reference_combo.findData(current_reference)
            if index >= 0:
                self.raster_reference_combo.setCurrentIndex(index)
        if current_comparison:
            index = self.raster_comparison_combo.findData(current_comparison)
            if index >= 0:
                self.raster_comparison_combo.setCurrentIndex(index)
        if self.raster_comparison_combo.count() > 1 and self.raster_comparison_combo.currentIndex() == 0:
            self.raster_comparison_combo.setCurrentIndex(1)

    def _toggle_raster_options(self, backend):
        is_raster = backend.startswith("栅格")
        self.raster_options.setVisible(is_raster)
        save_result_shp = getattr(self, "save_result_shp", None)
        if save_result_shp is not None:
            save_result_shp.setVisible(not is_raster)

    def collect_parameters(self) -> dict:
        parameters = AnalysisParameters(
            dependent_variable=self.y_combo.currentText(),
            independent_variable=self.x_combo.currentText(),
            kernel=self.kernel_combo.currentText(),
            bandwidth=self.bandwidth_input.text(),
            bandwidth_mode=self.bandwidth_mode_combo.currentText(),
            distance_metric=self.distance_combo.currentText(),
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
            parameters["reference_path"] = self.raster_reference_combo.currentData() or ""
            parameters["comparison_path"] = self.raster_comparison_combo.currentData() or ""
        return parameters

    def run(self):
        self.runRequested.emit(self.collect_parameters())

    def load_shp(self, path):
        from core.io.readers import read_shapefile_geometry
        if Path(path).suffix.lower() != ".shp":
            self.statusMessage.emit("仅支持 SHP 几何显示")
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
        self._refresh_xy_from_map()
        self._refresh_chart_window()
        self.statusMessage.emit(f"已加载 {len(geometry['geometries']):,} 个几何要素到地图")

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
        self.latest_result = result
        self._result_output_shp = getattr(result, "output_shp", "") or ""
        if shp_path and result.status == "success" and result.local_columns:
            self._show_results(shp_path, result.local_columns)
            self.tabs.setCurrentIndex(1)
        self.statusMessage.emit(result.message)

    def update_after_data_change(self):
        self._refresh_raster_options()
