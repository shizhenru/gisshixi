"""属性表展示组件：可接收数据源拖放的虚拟表格 + 按需取数的数据模型。

QTableWidget 要为每个单元格建一个 QTableWidgetItem：18 万行 × 5 字段要建 93 万个对象，
实测卡顿 20 秒、占 590MB，无法用于栅格转面这类十几万行的数据。这里改用
QTableView + QAbstractTableModel：只为当前可见的几十个单元格取值，行数再多也能秒开。
"""
from ..qt_compat import (
    QAbstractTableModel,
    QModelIndex,
    QTableView,
    Qt,
    Signal,
)

from .data_select import MIME_RUN_INDEX, MIME_SOURCE_PATH

_DISPLAY_ROLE = Qt.ItemDataRole.DisplayRole


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def columns_from_rows(fields, rows):
    """把逐行记录转成按列组织的列表，供模型直接引用。"""
    if not rows:
        return [[] for _ in fields]
    return [list(column) for column in zip(*rows)]


class AttributeTableModel(QAbstractTableModel):
    """惰性属性表模型：按列持有值列表的引用，取值时按需索引，不预建单元格对象。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fields = []
        self._columns = []
        self._rows = 0

    def set_columns(self, fields, columns, row_count):
        """设置表格内容。fields 为列名，columns 为按列组织的值列表（直接引用，不复制）。"""
        self.beginResetModel()
        self._fields = list(fields)
        self._columns = list(columns)
        self._rows = max(0, int(row_count))
        self.endResetModel()

    def clear(self):
        self.set_columns([], [], 0)

    def value(self, row, column):
        if not (0 <= column < len(self._columns)):
            return None
        values = self._columns[column]
        return values[row] if 0 <= row < len(values) else None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._rows

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._fields)

    def data(self, index, role=_DISPLAY_ROLE):
        if not index.isValid() or role != _DISPLAY_ROLE:
            return None
        return _cell_text(self.value(index.row(), index.column()))

    def headerData(self, section, orientation, role=_DISPLAY_ROLE):
        if role != _DISPLAY_ROLE:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._fields[section]) if 0 <= section < len(self._fields) else ""
        return str(section + 1)


class DroppableTableView(QTableView):
    """可接收拖放的虚拟属性表。

    拖数据源 → sourceDropped(路径)，只换表内容；拖项目 → runDropped(序号)，
    交给主窗口切项目（与拖到地图上同一套处理）。
    """

    sourceDropped = Signal(str)
    runDropped = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def _accepts(mime) -> bool:
        return mime.hasFormat(MIME_SOURCE_PATH) or mime.hasFormat(MIME_RUN_INDEX)

    def dragEnterEvent(self, event):
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME_RUN_INDEX):
            raw = bytes(event.mimeData().data(MIME_RUN_INDEX)).decode("utf-8")
            try:
                self.runDropped.emit(int(raw))
            except ValueError:
                pass
            event.acceptProposedAction()
            return
        if event.mimeData().hasFormat(MIME_SOURCE_PATH):
            path = bytes(event.mimeData().data(MIME_SOURCE_PATH)).decode("utf-8")
            self.sourceDropped.emit(path)
            event.acceptProposedAction()
        else:
            event.ignore()
