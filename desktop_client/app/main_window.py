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
    QSizePolicy,
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
from core.engine import AnalysisEngine
from core.io.exporters import export_report
from core.models import AnalysisResult
from core.project import ProjectStore
from core.raster_processing import RasterPreprocessor


class AnalysisWorker(QObject):
    """Small worker object used by QThread to keep subprocess execution off the UI thread."""

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
        self.nav_buttons = {}
        self._build()

    def closeEvent(self, event):
        """关闭窗口前先安全结束后台分析线程，避免 QThread 在运行中被销毁。"""
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            self._analysis_thread.quit()
            self._analysis_thread.wait(2000)
        event.accept()

    def _build(self):
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._top_bar())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._sidebar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 27, 28, 22)
        content_layout.setSpacing(0)
        self.stack = QStackedWidget()
        self.workbench_page = WorkbenchPage(self.store)
        self.data_page = DataPage(self.store)
        self.preprocess_page = PreprocessPage(self.store)
        self.analysis_page = AnalysisPage()
        self.results_page = ResultsPage(self.latest_result)
        self.settings_page = SettingsPage()
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
        content_layout.addWidget(self.stack, 1)
        body_layout.addWidget(content, 1)
        root_layout.addWidget(body, 1)

        self.status_label = QLabel("本地项目已保存 · 演示数据已就绪")
        self.status_label.setObjectName("Muted")
        self.status_label.setStyleSheet("padding: 7px 28px; background: #ffffff; border-top: 1px solid #dfe8e6;")
        root_layout.addWidget(self.status_label)
        self.setCentralWidget(root)
        self._connect_signals()
        self.navigate("workspace")
        self._refresh_sidebar()

    def _top_bar(self):
        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(76)
        layout = QHBoxLayout(top)
        layout.setContentsMargins(28, 0, 28, 0)
        layout.setSpacing(12)
        mark = QLabel("▦")
        mark.setFixedSize(37, 37)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet("color: #ffffff; background: #2d8c7c; border-radius: 8px; font-size: 18px; font-weight: 700;")
        layout.addWidget(mark)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("空间数据交叉验证工作台")
        title.setObjectName("BrandTitle")
        subtitle = QLabel("异源同质数据 · 精细尺度分析客户端")
        subtitle.setObjectName("BrandSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        layout.addLayout(titles)
        layout.addStretch()
        status = QLabel("●  本地项目已保存")
        status.setObjectName("Muted")
        layout.addWidget(status)
        export = QPushButton("↓")
        export.setToolTip("导出当前报告")
        export.setObjectName("GhostButton")
        export.setFixedWidth(34)
        export.clicked.connect(self.export_current_report)
        layout.addWidget(export)
        avatar = QLabel("施")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet("color: #ffffff; background: #496f79; border-radius: 16px; font-weight: 700;")
        layout.addWidget(avatar)
        return top

    def _sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(190)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 24, 12, 20)
        layout.setSpacing(6)
        project_label = QLabel("当前项目")
        project_label.setObjectName("Muted")
        project_name = QLabel("武汉市多源空间数据验证")
        project_name.setObjectName("ProjectName")
        project_path = QLabel("/projects/wuhan-2026")
        project_path.setObjectName("Muted")
        layout.addWidget(project_label)
        layout.addWidget(project_name)
        layout.addWidget(project_path)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #dce7e4;")
        layout.addWidget(separator)
        layout.addSpacing(12)
        nav_items = [
            ("workspace", "▦  工作台", ""),
            ("data", "↥  数据管理", ""),
            ("preprocess", "☷  预处理", ""),
            ("analysis", "◫  空间分析", ""),
            ("results", "⌁  结果与报告", ""),
        ]
        for key, title, badge in nav_items:
            button = QPushButton(title)
            button.setObjectName("NavButton")
            button.setProperty("active", False)
            button.clicked.connect(lambda checked=False, name=key: self.navigate(name))
            if badge:
                button.setText(f"{title}                                      {badge}")
            layout.addWidget(button)
            self.nav_buttons[key] = button
        layout.addStretch(1)
        health = QFrame()
        health.setObjectName("Panel")
        health_layout = QVBoxLayout(health)
        health_layout.setContentsMargins(13, 12, 13, 12)
        health_layout.setSpacing(7)
        health_head = QHBoxLayout()
        health_head.addWidget(QLabel("数据集状态"))
        self.health_ready_label = QLabel("待导入")
        self.health_ready_label.setStyleSheet("color: #849295; font-weight: 700;")
        health_head.addWidget(self.health_ready_label, alignment=Qt.AlignmentFlag.AlignRight)
        health_layout.addLayout(health_head)
        progress = QFrame()
        progress.setFixedHeight(5)
        progress.setStyleSheet("background: #dfece9; border-radius: 3px;")
        progress_bar = QFrame(progress)
        progress_bar.setGeometry(0, 0, 138, 5)
        progress_bar.setStyleSheet("background: #2d8c7c; border-radius: 3px;")
        health_layout.addWidget(progress)
        self.health_count_label = QLabel("暂无数据源")
        self.health_count_label.setObjectName("Muted")
        health_layout.addWidget(self.health_count_label)
        layout.addWidget(health)
        settings_button = QPushButton("⚙  系统设置")
        settings_button.setObjectName("GhostButton")
        settings_button.clicked.connect(lambda: self.navigate("settings"))
        layout.addWidget(settings_button)
        return sidebar

    def _connect_signals(self):
        self.workbench_page.runRequested.connect(self.run_analysis)
        self.analysis_page.runRequested.connect(self.run_analysis)
        self.data_page.statusMessage.connect(self.set_status)
        self.preprocess_page.statusMessage.connect(self.set_status)
        self.settings_page.statusMessage.connect(self.set_status)
        self.settings_page.rscriptChanged.connect(self._set_rscript_path)
        self.results_page.exportRequested.connect(self.export_current_report)

    def navigate(self, key):
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        if key == "data":
            self.data_page.refresh()
        elif key == "workspace":
            self.workbench_page.refresh_sources()
        for name, button in self.nav_buttons.items():
            button.setProperty("active", name == key)
            button.style().unpolish(button)
            button.style().polish(button)

    def set_status(self, message):
        self.status_label.setText(message)
        self._refresh_sidebar()

    def _refresh_sidebar(self):
        if not hasattr(self, "health_count_label"):
            return
        count = len(self.store.sources)
        if count:
            self.health_count_label.setText(f"已导入 {count} 个数据源")
            self.health_ready_label.setText("已就绪")
            self.health_ready_label.setStyleSheet("color: #2d8c7c; font-weight: 700;")
        else:
            self.health_count_label.setText("暂无数据源")
            self.health_ready_label.setText("待导入")
            self.health_ready_label.setStyleSheet("color: #849295; font-weight: 700;")

    def _set_rscript_path(self, path):
        self.settings.setValue("rscript_path", path)
        self.engine.r_runner.rscript_path = path
        self.engine.raster_runner.rscript_path = path
        self.set_status(f"已保存 Rscript 路径：{Path(path).name}")

    def run_analysis(self, parameters):
        if self._analysis_thread is not None:
            self.set_status("已有分析任务正在运行")
            return
        if parameters.get("analysis_type") == "raster":
            raster_paths = [
                source.path
                for source in self.store.sources
                if "栅格" in source.data_type
                or Path(source.path).suffix.lower() in {".tif", ".tiff", ".img", ".asc"}
            ]
            parameters = dict(parameters)
            manifest = RasterPreprocessor(self.store.project_dir).latest_manifest()
            aligned = (manifest or {}).get("processed", [])
            aligned_by_source = {item.get("source_path"): item.get("aligned_path") for item in aligned}
            parameters["raster_paths"] = [
                aligned_by_source.get(path, path) for path in raster_paths
            ]
            if len(raster_paths) < 2:
                self.set_status("栅格分析至少需要两个已导入的栅格数据集")
                return
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
        self.workbench_page.update_result(result)
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
            self,
            "导出分析报告",
            "空间数据交叉验证报告.md",
            "Markdown 文件 (*.md)",
        )
        if path:
            export_report(path, {
                "metrics": self.latest_result.metrics,
                "message": self.latest_result.message,
            }, self.latest_parameters)
            self.set_status(f"报告已导出：{Path(path).name}")
