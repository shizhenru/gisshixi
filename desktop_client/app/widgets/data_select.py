"""数据选择：勾选对话框 + 左侧数据选择面板。"""
from ..qt_compat import (
    QApplication,
    QDialog,
    QDrag,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMimeData,
    QPushButton,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)

from .panels import clear_layout

MIME_SOURCE_PATH = "application/x-spatial-source"


class DraggableSourceLabel(QLabel):
    """可拖拽的数据源名称标签，拖拽时携带数据源路径（MIME: application/x-spatial-source）。"""

    def __init__(self, text, source_path, parent=None):
        super().__init__(text, parent)
        self._source_path = source_path
        self._drag_start = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (event.position().toPoint() - self._drag_start).manhattanLength() >= QApplication.startDragDistance():
                self._start_drag()
                self._drag_start = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_SOURCE_PATH, self._source_path.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class ClickableRunLabel(QLabel):
    """项目名称标签：点击切换、双击重命名、拖拽到地图显示 SHP。"""

    clicked = Signal(int)
    doubleClicked = Signal(int)

    def __init__(self, text, index, shp_path="", parent=None):
        super().__init__(text, parent)
        self._index = index
        self._shp_path = shp_path
        self._drag_start = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (event.position().toPoint() - self._drag_start).manhattanLength() >= QApplication.startDragDistance():
                self._start_drag()
                self._drag_start = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_start is not None:
            self._drag_start = None
            if event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit(self._index)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit(self._index)
        super().mouseDoubleClickEvent(event)

    def _start_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_SOURCE_PATH, self._shp_path.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class DataSelectDialog(QDialog):
    """从已导入的数据目录中勾选要展示到工作台的数据。"""

    def __init__(self, sources, selected, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择数据")
        self.resize(380, 340)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("勾选要在工作台显示的数据（数据在「数据管理」页导入）："))
        self.list = QListWidget()
        self.sources = list(sources)
        selected_paths = {s.path for s in selected}
        for source in self.sources:
            item = QListWidgetItem(f"{source.icon}  {source.name} · {source.data_type}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if source.path in selected_paths else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.setObjectName("OutlineButton")
        ok = QPushButton("确定")
        ok.setObjectName("PrimaryButton")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def selected_sources(self):
        result = []
        for i, source in enumerate(self.sources):
            if self.list.item(i).checkState() == Qt.CheckState.Checked:
                result.append(source)
        return result


class DataSelectionPanel(QWidget):
    """左侧数据选择区：上方数据源，下方项目（工作区）列表。"""

    statusMessage = Signal(str)
    runSelected = Signal(int)
    runDeleteRequested = Signal(int)
    runRenameRequested = Signal(int)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.display_sources = list(store.sources)
        self.source_body = None
        self.run_body = None
        self.runs = []
        self._current_index = -1
        self._build()

    def _build(self):
        self.setObjectName("Panel")
        self.setFixedWidth(210)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        self.source_body = QVBoxLayout()
        self.source_body.setSpacing(6)
        root.addLayout(self.source_body)
        select_button = QPushButton("＋  选择数据")
        select_button.setObjectName("OutlineButton")
        select_button.clicked.connect(self._select_data)
        root.addWidget(select_button)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #dfe8e6;")
        root.addWidget(separator)
        projects_label = QLabel("项目")
        projects_label.setObjectName("Kicker")
        root.addWidget(projects_label)
        self.run_body = QVBoxLayout()
        self.run_body.setSpacing(4)
        root.addLayout(self.run_body)
        root.addStretch(1)

        self.refresh()

    def refresh(self):
        """按 store 目录重新构建列表（已删除的目录项会被剔除）。"""
        if self.source_body is None:
            return
        clear_layout(self.source_body)
        catalog_paths = {s.path for s in self.store.sources}
        self.display_sources = [s for s in self.display_sources if s.path in catalog_paths]
        for source in self.display_sources:
            row = QHBoxLayout()
            row.setSpacing(6)
            icon = QLabel(source.icon)
            icon.setFixedSize(22, 22)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setStyleSheet("color: #2d8c7c; background: #e3f3ef; border-radius: 4px; font-size: 12px;")
            row.addWidget(icon)
            name = DraggableSourceLabel(source.name, source.path)
            name.setStyleSheet("font-weight: 700;")
            name.setToolTip(self._tooltip_text(source))
            row.addWidget(name, 1)
            delete_button = QPushButton("×")
            delete_button.setObjectName("GhostButton")
            delete_button.setFixedWidth(26)
            delete_button.setToolTip("从工作区移除（不删除文件）")
            delete_button.clicked.connect(lambda checked=False, s=source: self._remove(s))
            row.addWidget(delete_button)
            self.source_body.addLayout(row)

    @staticmethod
    def _tooltip_text(source) -> str:
        parts = [f"{source.data_type} · {source.records}"]
        if source.geometry_type:
            parts.append(f"几何：{source.geometry_type}")
        if source.fields:
            shown = source.fields[:12]
            suffix = "" if len(source.fields) <= 12 else f" 等 {len(source.fields)} 个"
            parts.append("字段：" + "、".join(shown) + suffix)
        if source.warnings:
            parts.append("提示：" + "；".join(source.warnings))
        return "\n".join(parts)

    def _select_data(self):
        dialog = DataSelectDialog(self.store.sources, self.display_sources, self)
        if dialog.exec():
            self.display_sources = dialog.selected_sources()
            self.refresh()
            self.statusMessage.emit(f"已选择 {len(self.display_sources)} 个数据")

    def _remove(self, source):
        self.display_sources = [s for s in self.display_sources if s.path != source.path]
        self.refresh()
        self.statusMessage.emit(f"已从工作区移除：{source.name}")

    def set_runs(self, runs, current_index=-1):
        self.runs = list(runs)
        self._current_index = current_index
        self._refresh_runs()

    def _refresh_runs(self):
        if self.run_body is None:
            return
        clear_layout(self.run_body)
        if not self.runs:
            empty = QLabel("暂无项目\n（运行分析后自动加入）")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            self.run_body.addWidget(empty)
            return
        for i, run in enumerate(self.runs):
            row = QHBoxLayout()
            row.setSpacing(5)
            marker = QLabel("▸" if i == self._current_index else " ")
            marker.setFixedWidth(12)
            marker.setStyleSheet("color: #2d8c7c; font-weight: 700;")
            row.addWidget(marker)
            drag_path = getattr(run.result, "output_shp", "") or run.shp_path
            name = ClickableRunLabel(run.name, i, drag_path)
            name.setToolTip("点击切换 · 双击重命名 · 拖拽到地图显示")
            if i == self._current_index:
                name.setStyleSheet("font-weight: 700; color: #1e655b;")
            name.clicked.connect(self._on_run_clicked)
            name.doubleClicked.connect(self._on_run_double_clicked)
            row.addWidget(name, 1)
            delete_btn = QPushButton("×")
            delete_btn.setObjectName("GhostButton")
            delete_btn.setFixedWidth(22)
            delete_btn.setToolTip("删除项目")
            delete_btn.clicked.connect(lambda checked=False, idx=i: self.runDeleteRequested.emit(idx))
            row.addWidget(delete_btn)
            self.run_body.addLayout(row)

    def _on_run_clicked(self, index):
        self.runSelected.emit(index)

    def _on_run_double_clicked(self, index):
        self.runRenameRequested.emit(index)
