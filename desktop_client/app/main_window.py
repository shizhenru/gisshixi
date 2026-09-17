"""主窗口：顶部导航 + 左侧数据选择 + 页面堆栈 + 状态栏。"""
from pathlib import Path

from .pages import (
    AnalysisPage,
    DataPage,
    PreprocessPage,
    ResultsPage,
    SettingsPage,
    WorkbenchPage,
)
from .qt_compat import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QProgressBar,
    QSettings,
    QStackedWidget,
    QThread,
    QVBoxLayout,
    QWidget,
    QObject,
    Signal,
    Slot,
    Qt,
)
from .theme import APP_STYLE
from .widgets import DataSelectionPanel
from core.engine import AnalysisEngine
from core.io.exporters import export_report
from core.models import AnalysisResult, AnalysisRun
from core.project import ProjectStore
from core.raster_processing import RasterPreprocessor

NAV_ITEMS = [
    ("workspace", "工作台"),
    ("data", "数据管理"),
    ("preprocess", "预处理"),
    ("analysis", "空间分析"),
    ("results", "结果与报告"),
]


class AnalysisWorker(QObject):
    """后台线程工作对象，把子进程执行移出 UI 线程。"""

    finished = Signal(object)
    progress = Signal(str)

    def __init__(self, engine, parameters):
        super().__init__()
        self.engine = engine
        self.parameters = parameters

    @Slot()
    def run(self):
        self.progress.emit("正在准备分析任务...")
        result = self.engine.run(self.parameters)
        self.finished.emit(result)


class SpatialValidationWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("空间数据交叉验证工作台")
        self.resize(1440, 900)
        self.setMinimumSize(1180, 720)
        self.setStyleSheet(APP_STYLE)
        self.settings = QSettings("GIS-Internship", "SpatialValidationClient")
        self.store = ProjectStore()
        self.engine = AnalysisEngine(self.store.project_dir, self.settings.value("rscript_path", ""))
        self.latest_result = AnalysisResult()
        self.latest_parameters = {}
        self._analysis_thread = None
        self._analysis_worker = None
        self._last_analysis_shp_path = None
        self.runs = []
        self.nav_buttons = {}
        self._build()

    def closeEvent(self, event):
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            self._analysis_thread.quit()
            self._analysis_thread.wait(2000)
        event.accept()

    def _build(self):
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._top_nav())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self.data_panel = DataSelectionPanel(self.store)
        body_layout.addWidget(self.data_panel)

        self.stack = QStackedWidget()
        self.workbench_page = WorkbenchPage(self.store)
        self.data_page = DataPage(self.store)
        self.preprocess_page = PreprocessPage(self.store)
        self.analysis_page = AnalysisPage(self.store)
        self.results_page = ResultsPage(self.latest_result)
        self.settings_page = SettingsPage(rscript_path=self.settings.value("rscript_path", ""))
        self.pages = {
            "workspace": self.workbench_page,
            "data": self.data_page,
            "preprocess": self.preprocess_page,
            "analysis": self.analysis_page,
            "results": self.results_page,
            "settings": self.settings_page,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        body_layout.addWidget(self.stack, 1)
        root_layout.addWidget(body, 1)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("Muted")
        self.status_label.setStyleSheet("padding: 7px 28px; background: #ffffff; border-top: 1px solid #dfe8e6;")
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(self.status_label, 1)
        self.analysis_progress = QProgressBar()
        self.analysis_progress.setRange(0, 0)
        self.analysis_progress.setFixedWidth(220)
        self.analysis_progress.setVisible(False)
        status_row.addWidget(self.analysis_progress)
        status_widget = QWidget()
        status_widget.setLayout(status_row)
        status_widget.setStyleSheet("background: #ffffff; border-top: 1px solid #dfe8e6;")
        root_layout.addWidget(status_widget)
        self.setCentralWidget(root)
        self._connect_signals()
        self.navigate("workspace")

    def _top_nav(self):
        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(52)
        layout = QHBoxLayout(top)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(6)
        for key, title in NAV_ITEMS:
            button = QPushButton(title)
            button.setObjectName("NavButton")
            button.setProperty("active", False)
            button.clicked.connect(lambda checked=False, name=key: self.navigate(name))
            layout.addWidget(button)
            self.nav_buttons[key] = button
        layout.addStretch()
        settings_button = QPushButton("⚙ 设置")
        settings_button.setObjectName("NavButton")
        settings_button.setProperty("active", False)
        settings_button.clicked.connect(lambda: self.navigate("settings"))
        layout.addWidget(settings_button)
        self.nav_buttons["settings"] = settings_button
        return top

    def _connect_signals(self):
        self.workbench_page.runRequested.connect(self.run_analysis)
        self.data_panel.statusMessage.connect(self.set_status)
        self.data_page.statusMessage.connect(self.set_status)
        self.preprocess_page.statusMessage.connect(self.set_status)
        self.analysis_page.statusMessage.connect(self.set_status)
        self.results_page.statusMessage.connect(self.set_status)
        self.settings_page.statusMessage.connect(self.set_status)
        self.settings_page.rscriptChanged.connect(self._set_rscript_path)
        self.results_page.exportRequested.connect(self.export_current_report)
        self.data_panel.runSelected.connect(self._switch_run)
        self.data_panel.runDeleteRequested.connect(self._delete_run)
        self.data_panel.runRenameRequested.connect(self._rename_run)

    def navigate(self, key):
        self.stack.setCurrentWidget(self.pages[key])
        self.data_panel.refresh()
        if key == "workspace":
            self.workbench_page._refresh_variable_options()
            self.workbench_page.update_after_data_change()
        elif key == "preprocess":
            self.preprocess_page.update_after_data_change()
        elif key == "analysis":
            self.analysis_page.update_after_data_change()
        for name, button in self.nav_buttons.items():
            button.setProperty("active", name == key)
            button.style().unpolish(button)
            button.style().polish(button)

    def set_status(self, message):
        self.status_label.setText(message)
        self.data_panel.refresh()

    def _set_rscript_path(self, path):
        self.settings.setValue("rscript_path", path)
        self.engine.r_runner.rscript_path = path
        self.engine.r_gwr_runner.rscript_path = path
        self.engine.raster_runner.rscript_path = path
        self.set_status(f"已保存 Rscript 路径：{Path(path).name}")

    def run_analysis(self, parameters):
        if self._analysis_thread is not None:
            self.set_status("已有分析任务正在运行")
            return
        self._last_analysis_shp_path = None
        if parameters.get("analysis_type") == "raster":
            raster_paths = [path for path in parameters.get("raster_paths", []) if path]
            if len(raster_paths) < 2:
                self.set_status("栅格分析至少需要选择两个栅格数据集")
                return
            parameters = dict(parameters)
            manifest = RasterPreprocessor(self.store.project_dir).latest_manifest()
            aligned = (manifest or {}).get("processed", [])
            aligned_by_source = {item.get("source_path"): item.get("aligned_path") for item in aligned}
            parameters["raster_paths"] = [aligned_by_source.get(path, path) for path in raster_paths]
            source_by_path = {source.path: source for source in self.store.sources}
            parameters["raster_names"] = [
                source_by_path[path].name if path in source_by_path else Path(path).stem
                for path in raster_paths
            ]
        elif parameters.get("analysis_type") == "attribute":
            shp_path = next(
                (source.path for source in self.store.sources
                 if Path(source.path).suffix.lower() in {".shp", ".gpkg", ".geojson"}),
                None,
            )
            if not shp_path:
                self.set_status("属性 GWR 分析需要先导入一个矢量数据（SHP/GeoPackage/GeoJSON）")
                return
            parameters = dict(parameters)
            parameters["shp_path"] = shp_path
            # 每个项目独立输出目录，避免结果 SHP 相互覆盖
            parameters["output_dir"] = str(
                self.engine.project_dir / ".runtime" / "attribute_results" / f"run_{len(self.runs) + 1}"
            )
            self._last_analysis_shp_path = shp_path
        self.latest_parameters = parameters
        self.set_status(f"正在运行 {parameters.get('backend', '算法')}...")
        self.analysis_progress.setVisible(True)
        self._analysis_thread = QThread(self)
        self._analysis_worker = AnalysisWorker(self.engine, parameters)
        self._analysis_worker.moveToThread(self._analysis_thread)
        self._analysis_thread.started.connect(self._analysis_worker.run)
        self._analysis_worker.progress.connect(self.set_status)
        self._analysis_worker.finished.connect(self._analysis_finished)
        self._analysis_worker.finished.connect(self._analysis_thread.quit)
        self._analysis_worker.finished.connect(self._analysis_worker.deleteLater)
        self._analysis_thread.finished.connect(self._analysis_thread.deleteLater)
        self._analysis_thread.finished.connect(self._analysis_thread_finished)
        self._analysis_thread.start()

    @Slot(object)
    def _analysis_finished(self, result):
        self.analysis_progress.setVisible(False)
        self.latest_result = result
        if result.status != "error" and self.latest_parameters.get("analysis_type") != "raster":
            self._render_scatter_for_result(result)
        self.results_page.update_result(result)
        self.workbench_page.update_result(result, self._last_analysis_shp_path)
        if result.status == "error":
            self.set_status(f"分析失败：{result.message}")
        else:
            self._add_run(result)
            # 自动加载结果 SHP 到地图，方便直接分层设色查看
            output_shp = getattr(result, "output_shp", "") or ""
            if output_shp and Path(output_shp).exists():
                self.workbench_page.load_shp(output_shp, reset_xy=False)
            self.set_status(f"分析完成：{result.engine}")

    def _render_scatter_for_result(self, result):
        x = self.latest_parameters.get("independent_variable", "")
        y = self.latest_parameters.get("dependent_variable", "")
        if not (x and y and self._last_analysis_shp_path):
            return
        out_path = self.engine.project_dir / ".runtime" / f"scatter_{len(self.runs) + 1}.png"
        if self.workbench_page.render_scatter_png(self._last_analysis_shp_path, x, y, str(out_path)):
            result.artifacts["scatter"] = str(out_path)

    @Slot()
    def _analysis_thread_finished(self):
        self._analysis_thread = None
        self._analysis_worker = None

    def export_current_report(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出分析报告", "空间数据交叉验证报告.md", "Markdown 文件 (*.md)",
        )
        if path:
            export_report(path, {
                "metrics": self.latest_result.metrics,
                "message": self.latest_result.message,
            }, self.latest_parameters)
            self.set_status(f"报告已导出：{Path(path).name}")

    def _add_run(self, result):
        y = self.latest_parameters.get("dependent_variable", "")
        x = self.latest_parameters.get("independent_variable", "")
        if self.latest_parameters.get("analysis_type") == "raster":
            name = f"栅格分析 · #{len(self.runs) + 1}"
        elif y and x:
            name = f"{y} vs {x} · #{len(self.runs) + 1}"
        else:
            name = f"分析 · #{len(self.runs) + 1}"
        sym = self.workbench_page.get_symbology_state()
        run = AnalysisRun(
            name=name,
            parameters=dict(self.latest_parameters),
            result=result,
            shp_path=self._last_analysis_shp_path or "",
            symbology_field=sym["symbology_field"],
            symbology_method=sym["symbology_method"],
            symbology_classes=sym["symbology_classes"],
        )
        self.runs.append(run)
        self.data_panel.set_runs(self.runs, len(self.runs) - 1)

    def _switch_run(self, index):
        if not (0 <= index < len(self.runs)):
            return
        run = self.runs[index]
        self.latest_result = run.result
        self.latest_parameters = run.parameters
        self._last_analysis_shp_path = run.shp_path
        self.workbench_page.restore_run(run)
        self.results_page.update_result(run.result)
        self.data_panel.set_runs(self.runs, index)
        self.set_status(f"已切换到项目：{run.name}")

    def _delete_run(self, index):
        if not (0 <= index < len(self.runs)):
            return
        name = self.runs[index].name
        del self.runs[index]
        self.data_panel.set_runs(self.runs, -1)
        self.set_status(f"已删除项目：{name}")

    def _rename_run(self, index):
        if not (0 <= index < len(self.runs)):
            return
        name, ok = QInputDialog.getText(self, "重命名项目", "新名称：", text=self.runs[index].name)
        if ok and name.strip():
            self.runs[index].name = name.strip()
            self.data_panel.set_runs(self.runs, index)
            self.set_status(f"已重命名为：{name.strip()}")
