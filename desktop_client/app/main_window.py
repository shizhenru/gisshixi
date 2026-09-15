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
    QLabel,
    QMainWindow,
    QPushButton,
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
from core.models import AnalysisResult
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
        root_layout.addWidget(self.status_label)
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

    def navigate(self, key):
        self.stack.setCurrentWidget(self.pages[key])
        self.data_panel.refresh()
        if key == "workspace":
            self.workbench_page._refresh_variable_options()
            self.workbench_page.update_after_data_change()
        elif key == "preprocess":
            self.preprocess_page.update_after_data_change()
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
            raster_paths = [
                source.path for source in self.store.sources
                if "栅格" in source.data_type
                or Path(source.path).suffix.lower() in {".tif", ".tiff", ".img", ".asc"}
            ]
            if len(raster_paths) < 2:
                self.set_status("栅格分析至少需要两个已导入的栅格数据集")
                return
            parameters = dict(parameters)
            selected_paths = [parameters.get("reference_path"), parameters.get("comparison_path")]
            selected_paths = [path for path in selected_paths if path]
            if len(selected_paths) == 2 and selected_paths[0] != selected_paths[1]:
                raster_paths = selected_paths
            manifest = RasterPreprocessor(self.store.project_dir).latest_manifest()
            aligned = (manifest or {}).get("processed", [])
            aligned_by_source = {item.get("source_path"): item.get("aligned_path") for item in aligned}
            parameters["raster_paths"] = [aligned_by_source.get(path, path) for path in raster_paths]
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
            self._last_analysis_shp_path = shp_path
        self.latest_parameters = parameters
        self.set_status(f"正在运行 {parameters.get('backend', '算法')}...")
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
        self.latest_result = result
        self.results_page.update_result(result)
        self.workbench_page.update_result(result, self._last_analysis_shp_path)
        if result.status == "error":
            self.set_status(f"分析失败：{result.message}")
        else:
            self.set_status(f"分析完成：{result.engine}")

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
