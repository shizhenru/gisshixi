"""属性表展示组件：可接收数据源拖放的表格 + 填充工具。"""
from ..qt_compat import QTableWidget, QTableWidgetItem, Qt, Signal

from .data_select import MIME_SOURCE_PATH


def fill_table(table, fields, rows):
    """把字段名和记录填充到一个 QTableWidget。"""
    table.clear()
    table.setColumnCount(len(fields))
    table.setHorizontalHeaderLabels([str(f) for f in fields])
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(_cell_text(value)))


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


class DroppableTable(QTableWidget):
    """可接收数据源拖放的属性表，拖入后发出 sourceDropped(路径)。"""

    sourceDropped = Signal(str)

    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_SOURCE_PATH):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_SOURCE_PATH):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME_SOURCE_PATH):
            path = bytes(event.mimeData().data(MIME_SOURCE_PATH)).decode("utf-8")
            self.sourceDropped.emit(path)
            event.acceptProposedAction()
        else:
            event.ignore()
