"""数据选择：勾选对话框 + 左侧数据选择面板。"""
from ..qt_compat import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)

from .panels import clear_layout


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
    """左侧数据选择区：展示工作集数据，支持勾选与移除。"""

    statusMessage = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.display_sources = list(store.sources)
        self.source_body = None
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
            name = QLabel(source.name)
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
