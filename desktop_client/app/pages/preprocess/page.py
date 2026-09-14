"""预处理页：工具箱（工具目录 + 参数面板 + 运行历史）。"""
from pathlib import Path

from ...qt_compat import (
    QColor,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from ...widgets import clear_layout, panel_box
from core.raster_processing import RasterPreprocessor, collect_raster_sources

# (分类, 工具名) —— 目前只有「栅格对齐」接入了真实处理，其余为待实现占位。
TOOLS = [
    ("栅格", "栅格对齐（统一 CRS/分辨率/范围）"),
    ("栅格", "重采样"),
    ("栅格", "掩膜提取"),
    ("矢量", "裁剪"),
    ("矢量", "缓冲区"),
    ("投影", "坐标转换"),
    ("数据质量", "缺失值检查"),
    ("格式转换", "格式转换"),
    ("数据变换", "对数变换"),
    ("数据变换", "标准化"),
]


class PreprocessPage(QWidget):
    """工具箱式预处理界面。"""

    statusMessage = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.preprocessor = RasterPreprocessor(store.project_dir)
        self.tool_list = None
        self.dynamic_body = None
        self.progress = None
        self.log = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索工具…")
        self.search_input.textChanged.connect(self._filter_tools)
        root.addWidget(self.search_input)

        # 主体：工具目录 + 参数面板
        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._catalog_panel())
        body.addWidget(self._parameter_panel(), 1)
        root.addLayout(body, 1)

        # 运行历史
        root.addWidget(self._history_panel())

    def _catalog_panel(self):
        panel, pbody = panel_box("TOOLBOX", "工具目录")
        self.tool_list = QListWidget()
        current_category = None
        for category, tool in TOOLS:
            if category != current_category:
                header = QListWidgetItem(f"▾ {category}")
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setForeground(QColor("#849295"))
                self.tool_list.addItem(header)
                current_category = category
            item = QListWidgetItem(f"　{tool}")
            item.setData(Qt.ItemDataRole.UserRole, tool)
            self.tool_list.addItem(item)
        self.tool_list.currentItemChanged.connect(self._on_tool_selected)
        pbody.addWidget(self.tool_list, 1)
        panel.setFixedWidth(270)
        return panel

    def _parameter_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        body = QVBoxLayout(panel)
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(10)
        self.param_title = QLabel("栅格对齐（统一 CRS/分辨率/范围）")
        self.param_title.setObjectName("PanelTitle")
        body.addWidget(self.param_title)
        self.param_desc = QLabel("将多个栅格统一到同一坐标系、分辨率与范围。")
        self.param_desc.setObjectName("Muted")
        self.param_desc.setWordWrap(True)
        body.addWidget(self.param_desc)
        self.dynamic_body = QVBoxLayout()
        self.dynamic_body.setSpacing(10)
        body.addLayout(self.dynamic_body)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        body.addWidget(self.progress)
        body.addStretch()
        self._show_raster_align_params()
        return panel

    def _history_panel(self):
        panel, body = panel_box("HISTORY", "运行历史")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("暂无运行记录")
        body.addWidget(self.log, 1)
        panel.setFixedHeight(150)
        return panel

    def _show_raster_align_params(self):
        """栅格对齐工具的参数（唯一已接入真实处理的工具）。"""
        clear_layout(self.dynamic_body)
        label = QLabel("参考栅格")
        label.setObjectName("Muted")
        self.dynamic_body.addWidget(label)
        self.ref_combo = QComboBox()
        self.ref_combo.setFixedHeight(32)
        self.dynamic_body.addWidget(self.ref_combo)
        run = QPushButton("▶ 运行")
        run.setObjectName("PrimaryButton")
        run.clicked.connect(self._run_raster_align)
        self.dynamic_body.addWidget(run)
        self._refresh_ref_combo()

    def _refresh_ref_combo(self):
        self.ref_combo.clear()
        for source in collect_raster_sources(self.store.sources):
            self.ref_combo.addItem(source.name, source.path)

    def _on_tool_selected(self, current, previous):
        del previous
        if current is None:
            return
        tool = current.data(Qt.ItemDataRole.UserRole)
        if not tool:
            return
        self.param_title.setText(tool)
        if tool.startswith("栅格对齐"):
            self.param_desc.setText("将多个栅格统一到同一坐标系、分辨率与范围。")
            self._show_raster_align_params()
        else:
            self.param_desc.setText("该工具参数待实现。")

    def _run_raster_align(self):
        rasters = collect_raster_sources(self.store.sources)
        if len(rasters) < 2:
            self.statusMessage.emit("请先在数据管理中导入至少两个栅格数据集")
            self._log("栅格对齐：失败（栅格不足）")
            return
        reference = self.ref_combo.currentData() or ""
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.statusMessage.emit("正在统一栅格坐标系、分辨率和范围…")
        try:
            result = self.preprocessor.preprocess(rasters, reference)
        except Exception as exc:
            self.progress.setRange(0, 100)
            self.progress.setVisible(False)
            self.statusMessage.emit(f"栅格预处理失败：{exc}")
            self._log(f"栅格对齐：失败（{exc}）")
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setVisible(False)
        if result.status == "success":
            self._log(f"栅格对齐：成功（{len(result.processed or [])} 个数据集）")
        else:
            self._log(f"栅格对齐：{result.message}")
        self.statusMessage.emit(result.message)

    def _filter_tools(self, text):
        if not self.tool_list:
            return
        keyword = text.strip()
        for i in range(self.tool_list.count()):
            item = self.tool_list.item(i)
            tool = item.data(Qt.ItemDataRole.UserRole)
            if tool is None:
                item.setHidden(False)
                continue
            item.setHidden(keyword not in tool)

    def _log(self, message):
        self.log.append(message)

    def update_after_data_change(self):
        """数据导入/删除后刷新参考栅格下拉框。"""
        if hasattr(self, "ref_combo"):
            self._refresh_ref_combo()
