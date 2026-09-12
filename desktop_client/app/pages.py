from pathlib import Path

from .qt_compat import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QProgressBar,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from core.io.exporters import export_data_catalog
from core.models import AnalysisParameters, AnalysisResult
from core.project import ProjectStore

from .widgets import MapCanvas, MetricCard


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget:
            widget.deleteLater()
        elif child_layout:
            clear_layout(child_layout)


def panel_box(kicker: str, title: str, right_text: str = ""):
    frame = QFrame()
    frame.setObjectName("Panel")
    root = QVBoxLayout(frame)
    root.setContentsMargins(0, 0, 0, 0)
    header = QHBoxLayout()
    header.setContentsMargins(18, 14, 18, 12)
    labels = QVBoxLayout()
    labels.setSpacing(3)
    kicker_label = QLabel(kicker)
    kicker_label.setObjectName("Kicker")
    title_label = QLabel(title)
    title_label.setObjectName("PanelTitle")
    labels.addWidget(kicker_label)
    labels.addWidget(title_label)
    header.addLayout(labels)
    header.addStretch()
    if right_text:
        right = QLabel(right_text)
        right.setObjectName("Muted")
        header.addWidget(right)
    root.addLayout(header)
    separator = QFrame()
    separator.setFrameShape(QFrame.Shape.HLine)
    separator.setStyleSheet("color: #edf1f1;")
    root.addWidget(separator)
    body = QVBoxLayout()
    body.setContentsMargins(18, 12, 18, 17)
    body.setSpacing(10)
    root.addLayout(body)
    return frame, body


def page_heading(kicker: str, title: str, description: str, action_text: str = ""):
    wrapper = QHBoxLayout()
    wrapper.setContentsMargins(0, 0, 0, 12)
    titles = QVBoxLayout()
    titles.setSpacing(4)
    kicker_label = QLabel(kicker)
    kicker_label.setObjectName("Kicker")
    title_label = QLabel(title)
    title_label.setObjectName("PageTitle")
    description_label = QLabel(description)
    description_label.setObjectName("Muted")
    titles.addWidget(kicker_label)
    titles.addWidget(title_label)
    titles.addWidget(description_label)
    wrapper.addLayout(titles)
    wrapper.addStretch()
    action = None
    if action_text:
        action = QPushButton(action_text)
        action.setObjectName("PrimaryButton")
        action.setMinimumWidth(118)
        wrapper.addWidget(action, alignment=Qt.AlignmentFlag.AlignBottom)
    return wrapper, action


class FlowStep(QFrame):
    def __init__(self, number, title, note, state="pending", parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(10)
        circle = QLabel("✓" if state == "done" else number)
        circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        circle.setFixedSize(27, 27)
        if state == "done":
            circle.setStyleSheet("background: #2d8c7c; color: #ffffff; border-radius: 13px; font-weight: 700;")
        elif state == "current":
            circle.setStyleSheet("background: #fff0e3; color: #e78338; border-radius: 13px; font-weight: 700;")
        else:
            circle.setStyleSheet("background: #edf4f2; color: #839194; border-radius: 13px; font-weight: 700;")
        layout.addWidget(circle)
        labels = QVBoxLayout()
        labels.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 700;")
        note_label = QLabel(note)
        note_label.setObjectName("Muted")
        labels.addWidget(title_label)
        labels.addWidget(note_label)
        layout.addLayout(labels)


class WorkbenchPage(QWidget):
    runRequested = Signal(dict)
    statusMessage = Signal(str)

    def __init__(self, store: ProjectStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.latest_result = AnalysisResult()
        self.source_body = None
        self.selection_label = None
        self.bandwidth_value = None
        self.backend_combo = None
        self.x_combo = None
        self.y_combo = None
        self.map_canvas = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        heading, run_button = page_heading(
            "PROJECT WORKSPACE",
            "空间分析工作台",
            "对齐数据、构建空间权重，并快速定位多源数据的局部差异。",
            "▶ 运行分析",
        )
        root.addLayout(heading)
        run_button.clicked.connect(lambda: self.runRequested.emit(self.collect_parameters()))

        flow = QHBoxLayout()
        flow.setSpacing(0)
        for number, title, note, state in [
            ("01", "数据准备", "3 个数据源已加载", "done"),
            ("02", "空间配准", "坐标与尺度已统一", "done"),
            ("03", "局部建模", "GWR 参数待运行", "current"),
            ("04", "结果输出", "等待分析完成", "pending"),
        ]:
            step = FlowStep(number, title, note, state)
            flow.addWidget(step, 1)
        root.addLayout(flow)

        grid = QGridLayout()
        grid.setContentsMargins(0, 18, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 4)
        grid.setColumnStretch(2, 2)
        grid.addWidget(self._data_panel(), 0, 0)
        grid.addWidget(self._analysis_panel(), 0, 1)
        right_stack = QVBoxLayout()
        right_stack.setSpacing(16)
        right_stack.addWidget(self._parameter_panel())
        right_stack.addWidget(self._layers_panel())
        right_widget = QWidget()
        right_widget.setLayout(right_stack)
        grid.addWidget(right_widget, 0, 2)
        grid.addWidget(self._metrics_panel(), 1, 0)
        root.addLayout(grid)

    def _data_panel(self):
        panel, body = panel_box("数据源", "多源数据集", "3 类")
        self.source_body = body
        self.refresh_sources()
        import_button = QPushButton("↥  导入新数据")
        import_button.setObjectName("OutlineButton")
        import_button.clicked.connect(self._import_data)
        body.addWidget(import_button)
        return panel

    def refresh_sources(self):
        if not self.source_body:
            return
        while self.source_body.count():
            item = self.source_body.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for source in self.store.sources:
            row = QHBoxLayout()
            row.setSpacing(9)
            icon = QLabel(source.icon)
            icon.setFixedSize(29, 29)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setStyleSheet("color: #2d8c7c; background: #e3f3ef; border-radius: 6px; font-size: 15px;")
            row.addWidget(icon)
            labels = QVBoxLayout()
            labels.setSpacing(2)
            name = QLabel(source.data_type)
            name.setStyleSheet("font-weight: 700;")
            details = QLabel(f"{source.name} · {Path(source.path).name}")
            details.setObjectName("Muted")
            details.setWordWrap(True)
            labels.addWidget(name)
            labels.addWidget(details)
            row.addLayout(labels, 1)
            toggle = QCheckBox()
            toggle.setChecked(source.status != "待检查")
            row.addWidget(toggle)
            self.source_body.addLayout(row)
            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setStyleSheet("color: #edf1f1;")
            self.source_body.addWidget(separator)

    def _import_data(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择空间数据",
            "",
            "空间数据 (*.csv *.xlsx *.xls *.tif *.tiff *.gpkg *.shp *.geojson);;所有文件 (*.*)",
        )
        if path:
            self.store.add_source(path)
            self.refresh_sources()
            self.statusMessage.emit(f"已登记数据：{Path(path).name}")

    def _metrics_panel(self):
        panel, body = panel_box("评价指标", "全局一致性", "演示结果")
        metrics = [("MAE", "平均绝对误差", "较上次 ↓ 12.4%", "8.42"),
                   ("R", "相关系数", "显著正相关", "0.82"),
                   ("RMSE", "均方根误差", "较上次 ↓ 6.8%", "13.67")]
        for code, title, note, value in metrics:
            row = QHBoxLayout()
            badge = QLabel(code)
            badge.setFixedSize(32, 25)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet("color: #4977b8; background: #eef3fa; border-radius: 4px; font-size: 10px; font-weight: 700;")
            row.addWidget(badge)
            labels = QVBoxLayout()
            labels.setSpacing(2)
            labels.addWidget(QLabel(title))
            note_label = QLabel(note)
            note_label.setObjectName("Muted")
            labels.addWidget(note_label)
            row.addLayout(labels, 1)
            value_label = QLabel(value)
            value_label.setStyleSheet("color: #2d8c7c; font-size: 16px; font-weight: 700;")
            row.addWidget(value_label)
            body.addLayout(row)
        return panel

    def _analysis_panel(self):
        panel, body = panel_box("局部精细尺度分析", "空间差异分布")
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("横轴"))
        self.x_combo = QComboBox()
        self.x_combo.addItems(["人口密度", "夜光遥感", "人均 GDP"])
        toolbar.addWidget(self.x_combo)
        toolbar.addWidget(QLabel("与"))
        toolbar.addWidget(QLabel("纵轴"))
        self.y_combo = QComboBox()
        self.y_combo.addItems(["夜光遥感", "人口密度", "人均 GDP"])
        toolbar.addWidget(self.y_combo)
        toolbar.addStretch()
        reset = QPushButton("⚙ 重置视图")
        reset.setObjectName("GhostButton")
        reset.clicked.connect(self._reset_view)
        toolbar.addWidget(reset)
        body.addLayout(toolbar)
        mode_row = QHBoxLayout()
        mode_row.addStretch()
        map_button = QPushButton("◫ 地图")
        map_button.setObjectName("OutlineButton")
        scatter_button = QPushButton("⌁ 散点图")
        scatter_button.setObjectName("GhostButton")
        mode_row.addWidget(map_button)
        mode_row.addWidget(scatter_button)
        body.addLayout(mode_row)
        self.preview_stack = QStackedWidget()
        self.map_canvas = MapCanvas()
        self.map_canvas.selectedChanged.connect(self._update_selection)
        self.preview_stack.addWidget(self.map_canvas)
        scatter = QLabel("散点图画布接口已预留\n后续接入 Matplotlib / PyQtGraph")
        scatter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scatter.setObjectName("Muted")
        scatter.setStyleSheet("background: #f7faf9; border: 1px solid #dfeae5; border-radius: 6px;")
        self.preview_stack.addWidget(scatter)
        body.addWidget(self.preview_stack, 1)
        map_button.clicked.connect(lambda: self.preview_stack.setCurrentIndex(0))
        scatter_button.clicked.connect(lambda: self.preview_stack.setCurrentIndex(1))
        legend = QLabel("● 高一致性　　● 中等差异　　● 显著差异")
        legend.setObjectName("Muted")
        body.addWidget(legend)
        self.selection_label = QLabel("当前选中样本 · ID 0018　江汉区 / 唐家墩街道　人口 65　夜光 85　局部 R² 0.86")
        self.selection_label.setStyleSheet("padding: 10px; color: #356d63; background: #f1f8f5; border: 1px solid #dbece7; border-radius: 5px;")
        body.addWidget(self.selection_label)
        return panel

    def _parameter_panel(self):
        panel, body = panel_box("GWR MODEL", "模型参数", "可扩展")
        form = QGridLayout()
        form.setHorizontalSpacing(9)
        form.setVerticalSpacing(8)
        form.addWidget(QLabel("算法后端"), 0, 0)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["Python 占位算法", "R 占位算法", "混合调度（预留）"])
        form.addWidget(self.backend_combo, 0, 1)
        form.addWidget(QLabel("核函数"), 1, 0)
        kernel = QComboBox()
        kernel.addItems(["双平方核", "高斯核", "指数核"])
        kernel.setObjectName("KernelCombo")
        self.kernel_combo = kernel
        form.addWidget(kernel, 1, 1)
        form.addWidget(QLabel("带宽"), 2, 0)
        bandwidth_row = QHBoxLayout()
        self.bandwidth_slider = QSlider(Qt.Orientation.Horizontal)
        self.bandwidth_slider.setRange(10, 100)
        self.bandwidth_slider.setValue(62)
        self.bandwidth_value = QLabel("0.62")
        self.bandwidth_value.setStyleSheet("color: #2d8c7c; font-weight: 700;")
        self.bandwidth_slider.valueChanged.connect(lambda value: self.bandwidth_value.setText(f"{value / 100:.2f}"))
        bandwidth_row.addWidget(self.bandwidth_slider, 1)
        bandwidth_row.addWidget(self.bandwidth_value)
        form.addLayout(bandwidth_row, 2, 1)
        form.addWidget(QLabel("带宽策略"), 3, 0)
        mode = QComboBox()
        mode.addItems(["自适应带宽", "固定带宽"])
        self.bandwidth_mode_combo = mode
        form.addWidget(mode, 3, 1)
        form.addWidget(QLabel("距离度量"), 4, 0)
        distance = QComboBox()
        distance.addItems(["投影坐标距离（米）", "大圆距离（千米）"])
        self.distance_combo = distance
        form.addWidget(distance, 4, 1)
        body.addLayout(form)
        note = QLabel("● 建议：当前样本量适合使用自适应带宽")
        note.setStyleSheet("padding: 9px; color: #6f8f88; background: #eff8f5; border-radius: 4px;")
        body.addWidget(note)
        return panel

    def _layers_panel(self):
        panel, body = panel_box("MAP LAYERS", "图层显示", "4 / 4")
        for color, name in [("#2d8c7c", "人口密度差异"), ("#e78338", "夜光遥感强度"),
                            ("#a8b7b4", "行政区边界"), ("#d86659", "样本点")]:
            row = QHBoxLayout()
            swatch = QLabel(" ")
            swatch.setFixedSize(9, 9)
            swatch.setStyleSheet(f"background: {color}; border-radius: 2px;")
            row.addWidget(swatch)
            row.addWidget(QLabel(name), 1)
            toggle = QCheckBox()
            toggle.setChecked(True)
            row.addWidget(toggle)
            body.addLayout(row)
        return panel

    def _update_selection(self, index):
        self.selection_label.setText(
            f"当前选中样本 · ID {index + 1:04d}　江汉区 / 唐家墩街道　人口 65　夜光 85　局部 R² 0.86"
        )

    def _reset_view(self):
        self.x_combo.setCurrentIndex(0)
        self.y_combo.setCurrentIndex(0)
        self.bandwidth_slider.setValue(62)
        self.statusMessage.emit("已重置地图与模型参数")

    def collect_parameters(self):
        return AnalysisParameters(
            dependent_variable=self.y_combo.currentText(),
            independent_variable=self.x_combo.currentText(),
            kernel=self.kernel_combo.currentText(),
            bandwidth=self.bandwidth_slider.value() / 100,
            bandwidth_mode=self.bandwidth_mode_combo.currentText(),
            distance_metric=self.distance_combo.currentText(),
            backend=self.backend_combo.currentText(),
        ).to_dict()

    def set_running(self, running: bool):
        self.sender_button_enabled = not running

    def update_result(self, result: AnalysisResult):
        self.latest_result = result
        self.statusMessage.emit(result.message)


class DataPage(QWidget):
    statusMessage = Signal(str)

    def __init__(self, store: ProjectStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.table = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        heading, import_button = page_heading("DATA CATALOG", "数据管理", "统一登记多源数据的来源、空间范围、坐标系与质量状态。", "↥ 导入数据")
        root.addLayout(heading)
        import_button.clicked.connect(self.import_data)
        panel, body = panel_box("DATASETS · 03", "项目数据目录", "可导出")
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["数据集", "类型", "空间范围", "坐标系", "记录 / 分辨率", "状态", "路径"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(310)
        body.addWidget(self.table)
        export_button = QPushButton("↓ 导出数据清单")
        export_button.setObjectName("OutlineButton")
        export_button.clicked.connect(self.export_data)
        body.addWidget(export_button, alignment=Qt.AlignmentFlag.AlignRight)
        root.addWidget(panel)
        note = QLabel("ⓘ  数据质量检查接口已预留。真实导入后可在 core/io 中补充缺失值、坐标系和空间范围检查。")
        note.setStyleSheet("padding: 13px; color: #6f8f88; background: #eef6f4; border: 1px solid #d7eae5; border-radius: 7px;")
        root.addWidget(note)
        root.addStretch()
        self.refresh()

    def refresh(self):
        self.table.setRowCount(0)
        for source in self.store.sources:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [source.name, source.data_type, source.extent, source.crs, source.records, source.status, source.path]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                self.table.setItem(row, column, item)
        widths = [145, 85, 120, 100, 105, 85, 280]
        for index, width in enumerate(widths):
            self.table.setColumnWidth(index, width)

    def import_data(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择空间数据", "", "空间数据 (*.csv *.xlsx *.xls *.tif *.tiff *.gpkg *.shp *.geojson);;所有文件 (*.*)")
        if path:
            self.store.add_source(path)
            self.refresh()
            self.statusMessage.emit(f"已登记数据：{Path(path).name}")

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出数据清单", "data_catalog.csv", "CSV 文件 (*.csv)")
        if path:
            export_data_catalog(path, self.store.sources)
            self.statusMessage.emit(f"数据清单已导出：{Path(path).name}")


class PreprocessPage(QWidget):
    statusMessage = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        heading, _ = page_heading("DATA PREPARATION", "预处理与空间配准", "将不同来源的数据统一到同一空间参考、尺度与分析单元。")
        root.addLayout(heading)
        grid = QGridLayout()
        grid.setSpacing(16)
        left, left_body = panel_box("PIPELINE", "标准化处理流程", "3 / 5 已完成")
        steps = [
            ("01", "数据质量检查", "缺失值、异常值、重复记录", "已完成", True),
            ("02", "空间参考统一", "转换至 CGCS2000 / 3°分带", "已完成", True),
            ("03", "空间范围裁剪", "按武汉市研究区边界裁剪", "已完成", True),
            ("04", "空间尺度协调", "栅格重采样至 500 m 分辨率", "待处理", False),
            ("05", "数据格式标准化", "输出统一 GeoPackage 数据集", "待处理", False),
        ]
        for number, title, note, status, done in steps:
            row = QHBoxLayout()
            badge = QLabel("✓" if done else number)
            badge.setFixedSize(27, 27)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet("background: #2d8c7c; color: white; border-radius: 14px; font-weight: 700;" if done else "background: #f4f7f6; color: #839194; border-radius: 14px;")
            row.addWidget(badge)
            labels = QVBoxLayout()
            labels.setSpacing(2)
            labels.addWidget(QLabel(title))
            note_label = QLabel(note)
            note_label.setObjectName("Muted")
            labels.addWidget(note_label)
            row.addLayout(labels, 1)
            status_label = QLabel(status)
            status_label.setObjectName("Muted")
            row.addWidget(status_label)
            left_body.addLayout(row)
        progress = QProgressBar()
        progress.setValue(60)
        left_body.addWidget(progress)
        run = QPushButton("▶  执行待处理步骤")
        run.setObjectName("PrimaryButton")
        run.clicked.connect(lambda: self.statusMessage.emit("预处理任务已加入队列，等待真实数据处理器接入"))
        left_body.addWidget(run)
        grid.addWidget(left, 0, 0)
        right, right_body = panel_box("PREVIEW", "配准预览", "500 m")
        canvas = MapCanvas()
        right_body.addWidget(canvas, 1)
        preview_info = QLabel("目标坐标系　CGCS2000 / 3°分带\n统一分析单元　500 m 网格\n研究区　武汉市域 · 8,221 km²")
        preview_info.setObjectName("Muted")
        preview_info.setStyleSheet("line-height: 1.7;")
        right_body.addWidget(preview_info)
        grid.addWidget(right, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        root.addStretch()


class AnalysisPage(QWidget):
    runRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        heading, run_button = page_heading("ANALYSIS CENTER", "空间分析任务中心", "集中管理分析任务、算法后端与运行日志。", "▶ 新建任务")
        root.addLayout(heading)
        run_button.clicked.connect(lambda: self.runRequested.emit(AnalysisParameters().to_dict()))
        panel, body = panel_box("TASK QUEUE", "任务队列", "接口已预留")
        task_list = QListWidget()
        for title, detail, status in [
            ("局部 GWR 交叉验证", "人口密度 × 夜光遥感 · 自适应带宽 0.62", "待运行"),
            ("全局一致性指标", "MAE / RMSE / 相关系数", "可复用"),
            ("几何对象差异分析", "道路、建筑物与行政边界", "待接入"),
        ]:
            item = QListWidgetItem(f"{title}\n{detail}　　　　　　　　　{status}")
            task_list.addItem(item)
        body.addWidget(task_list)
        log = QTextEdit()
        log.setReadOnly(True)
        log.setPlainText("分析控制台已就绪。\nPython / R 算法统一通过 JSON 配置和 JSON 结果通信。\n请在 core/algorithms 中替换占位脚本。")
        body.addWidget(log)
        root.addWidget(panel)
        root.addStretch()


class ResultsPage(QWidget):
    exportRequested = Signal()

    def __init__(self, result: AnalysisResult | None = None, parent=None):
        super().__init__(parent)
        self.result = result or AnalysisResult()
        self.metric_layout = None
        self.report_text = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        heading, export_button = page_heading("RESULTS & REPORT", "结果与报告", "查看全局评价、局部空间差异，并生成可复现的分析摘要。", "↓ 生成报告")
        root.addLayout(heading)
        export_button.clicked.connect(self.exportRequested.emit)
        self.metric_layout = QGridLayout()
        self.metric_layout.setSpacing(14)
        root.addLayout(self.metric_layout)
        panel, body = panel_box("ANALYSIS LOG", "分析报告摘要", "可导出")
        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        body.addWidget(self.report_text)
        root.addWidget(panel, 1)
        self.refresh()

    def refresh(self):
        clear_layout(self.metric_layout)
        metrics = self.result.metrics
        cards = [
            ("全局相关系数", metrics.get("correlation", "0.82"), "显著正相关", "#2d8c7c"),
            ("局部 R² 均值", metrics.get("local_r2", "0.74"), "较全局提升 9.2%", "#2d8c7c"),
            ("显著差异区域", metrics.get("difference_area", "18.6%"), "城市边缘偏高", "#e78338"),
            ("模型运行耗时", metrics.get("duration", "02:41"), "12,486 个空间单元", "#4977b8"),
        ]
        for index, values in enumerate(cards):
            self.metric_layout.addWidget(MetricCard(*values), 0, index)
        report = (
            "异源同质空间数据精细尺度交叉验证\n\n"
            "本次分析以人口密度与夜光遥感强度为主要变量，采用自适应双平方核进行局部空间建模。"
            "当前界面和任务调度已经完成，真实数据读取、空间权重和 GWR 计算可以替换 core/algorithms 中的占位脚本。\n\n"
            f"执行引擎：{self.result.engine}\n"
            f"任务状态：{self.result.status}\n"
            f"运行信息：{self.result.message}\n\n"
            "建议：将江夏区、东西湖区边缘作为下一轮局部核查重点，结合几何数据检查空间对象偏移和边界差异。"
        )
        self.report_text.setPlainText(report)

    def update_result(self, result: AnalysisResult):
        self.result = result
        self.refresh()


class SettingsPage(QWidget):
    rscriptChanged = Signal(str)
    statusMessage = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rscript_input = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        heading, _ = page_heading("SYSTEM SETTINGS", "系统设置", "管理桌面客户端、算法运行环境和结果输出偏好。")
        root.addLayout(heading)
        panel, body = panel_box("RUNTIME", "多语言运行环境", "Python + R")
        row = QHBoxLayout()
        row.addWidget(QLabel("Rscript.exe 路径"))
        self.rscript_input = QLineEdit()
        self.rscript_input.setPlaceholderText("未配置时使用系统 PATH 中的 Rscript")
        row.addWidget(self.rscript_input, 1)
        browse = QPushButton("浏览")
        browse.setObjectName("OutlineButton")
        browse.clicked.connect(self._browse_rscript)
        row.addWidget(browse)
        body.addLayout(row)
        test = QPushButton("测试 R 环境")
        test.setObjectName("PrimaryButton")
        test.clicked.connect(lambda: self.statusMessage.emit("R 环境测试接口已预留，请配置后接入真实检查"))
        body.addWidget(test, alignment=Qt.AlignmentFlag.AlignLeft)
        note = QLabel("Python 算法直接由当前解释器运行；R 算法通过 Rscript 子进程运行。两者使用统一 JSON 输入和 JSON 输出格式。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        body.addWidget(note)
        root.addWidget(panel)
        display, display_body = panel_box("DISPLAY", "显示与输出", "本地")
        for name, description, checked in [
            ("自动保存分析参数", "每次调整模型参数后保存当前配置", True),
            ("显示实验性图层", "允许显示局部误差和样本密度", False),
        ]:
            row = QHBoxLayout()
            labels = QVBoxLayout()
            labels.addWidget(QLabel(name))
            sub = QLabel(description)
            sub.setObjectName("Muted")
            labels.addWidget(sub)
            row.addLayout(labels, 1)
            checkbox = QCheckBox()
            checkbox.setChecked(checked)
            row.addWidget(checkbox)
            display_body.addLayout(row)
        root.addWidget(display)
        root.addStretch()

    def _browse_rscript(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Rscript.exe", "", "Rscript (Rscript.exe);;所有文件 (*.*)")
        if path:
            self.rscript_input.setText(path)
            self.rscriptChanged.emit(path)
