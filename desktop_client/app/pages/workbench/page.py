"""工作台页：模型参数设置 + 运行 + 结果地图/散点图 + 结果图层 + 属性表。"""
from ...qt_compat import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from ...widgets import MapCanvas, panel_box
from core.models import AnalysisParameters, AnalysisResult


class WorkbenchPage(QWidget):
    """设置 GWR 模型参数并运行，展示结果地图、散点图与属性表。"""

    runRequested = Signal(dict)
    statusMessage = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.latest_result = AnalysisResult()
        self.map_canvas = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(16)

        # 中：小地图 + 散点图
        center = QHBoxLayout()
        center.setSpacing(16)
        center.addWidget(self._map_panel(), 1)
        center.addWidget(self._scatter_panel(), 1)
        top.addLayout(center, 1)

        # 右：模型参数 + 结果图层
        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(self._parameter_panel())
        right.addWidget(self._layers_panel())
        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setFixedWidth(280)
        top.addWidget(right_widget)

        root.addLayout(top, 1)
        root.addWidget(self._attribute_panel())

    def _map_panel(self):
        panel, body = panel_box("RESULT MAP", "小地图", "局部 R²")
        self.map_canvas = MapCanvas()
        body.addWidget(self.map_canvas, 1)
        hint = QLabel("滚轮缩放 · 拖拽平移 · 双击复位")
        hint.setObjectName("Muted")
        body.addWidget(hint)
        return panel

    def _scatter_panel(self):
        panel, body = panel_box("SCATTER", "散点图", "X vs Y")
        placeholder = QLabel("散点图画布接口已预留\n后续接入 Matplotlib / PyQtGraph")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setObjectName("Muted")
        placeholder.setStyleSheet("background: #f7faf9; border: 1px solid #dfeae5; border-radius: 6px;")
        body.addWidget(placeholder, 1)
        return panel

    def _parameter_panel(self):
        panel, body = panel_box("GWR MODEL", "模型参数")
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
            ["Python 占位算法", "R 占位算法", "栅格 R / terra"],
        )
        self._refresh_variable_options()
        run_button = QPushButton("▶ 运行")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(self.run)
        body.addWidget(run_button)
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

    def _layers_panel(self):
        panel, body = panel_box("MAP LAYERS", "结果图层")
        body.setSpacing(8)
        self.layer_checks = {}
        for color, name in [("#2d8c7c", "局部 R²"), ("#e78338", "回归系数"),
                            ("#d86659", "残差 / LME"), ("#a8b7b4", "样本点")]:
            row = QHBoxLayout()
            swatch = QLabel(" ")
            swatch.setFixedSize(9, 9)
            swatch.setStyleSheet(f"background: {color}; border-radius: 2px;")
            row.addWidget(swatch)
            row.addWidget(QLabel(name), 1)
            check = QCheckBox()
            check.setChecked(True)
            row.addWidget(check)
            body.addLayout(row)
            self.layer_checks[name] = check
        return panel

    def _attribute_panel(self):
        panel, body = panel_box("ATTRIBUTE", "属性表", "分析结果")
        self.result_table = QTableWidget(0, 7)
        self.result_table.setHorizontalHeaderLabels(["FID", "名称", "Y", "X", "局部 R²", "系数", "显著性"])
        self.result_table.verticalHeader().setVisible(False)
        body.addWidget(self.result_table, 1)
        return panel

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
        parameters.update({
            "analysis_type": "raster" if self.backend_combo.currentText().startswith("栅格") else "attribute",
            "auto_bandwidth": self.auto_bandwidth.isChecked(),
        })
        return parameters

    def run(self):
        self.runRequested.emit(self.collect_parameters())

    def load_shp(self, path):
        from core.io.readers import read_shapefile_geometry
        geometry = read_shapefile_geometry(path)
        if geometry["geometries"]:
            self.map_canvas.load_shapes(geometry)
            self.statusMessage.emit(f"已加载 {len(geometry['geometries']):,} 个几何要素到地图")
        else:
            self.statusMessage.emit("未能解析 SHP 几何（可能是不支持的几何类型）")

    def update_result(self, result: AnalysisResult):
        self.latest_result = result
        self.statusMessage.emit(result.message)
