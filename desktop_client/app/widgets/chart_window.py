"""图表分析窗口：散点图 + 直方图，可自行选择字段。"""
from ..qt_compat import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    Signal,
)
from .histogram_canvas import HistogramCanvas
from .scatter_canvas import ScatterCanvas


class ChartWindow(QWidget):
    """独立图表窗口：散点图（X/Y 两字段）+ 直方图（单字段）。"""

    featureSelected = Signal(int)   # 散点点击某点 → 对应要素索引
    selectionCleared = Signal()     # 点击空白处取消

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fields = []
        self._values = {}
        self._scatter_feature_ids = []
        self._scatter_fid_to_point = {}
        self._build()

    def _build(self):
        self.setWindowTitle("图表分析")
        self.resize(940, 680)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._scatter_tab(), "散点图")
        self.tabs.addTab(self._histogram_tab(), "直方图")
        root.addWidget(self.tabs, 1)

    def _scatter_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        row = QHBoxLayout()
        row.addWidget(QLabel("X 字段"))
        self.x_combo = QComboBox()
        row.addWidget(self.x_combo)
        row.addWidget(QLabel("Y 字段"))
        self.y_combo = QComboBox()
        row.addWidget(self.y_combo)
        row.addStretch()
        lay.addLayout(row)
        self.scatter_canvas = ScatterCanvas()
        lay.addWidget(self.scatter_canvas, 1)
        self.x_combo.currentTextChanged.connect(self._render_scatter)
        self.y_combo.currentTextChanged.connect(self._render_scatter)
        self.scatter_canvas.pointClicked.connect(self._on_point_clicked)
        self.scatter_canvas.blankClicked.connect(self._on_blank_clicked)
        return w

    def _histogram_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        row = QHBoxLayout()
        row.addWidget(QLabel("字段"))
        self.hist_combo = QComboBox()
        row.addWidget(self.hist_combo)
        row.addStretch()
        lay.addLayout(row)
        self.histogram_canvas = HistogramCanvas()
        lay.addWidget(self.histogram_canvas, 1)
        self.hist_combo.currentTextChanged.connect(self._render_histogram)
        return w

    def update_data(self, fields, values):
        """更新字段与数据（拖入新 SHP 或重新加载时调用）。"""
        self._fields = list(fields)
        self._values = {k: list(v) for k, v in values.items()}
        numeric = [f for f in self._fields if self._is_numeric(f)]
        current_x = self.x_combo.currentText()
        current_y = self.y_combo.currentText()
        current_h = self.hist_combo.currentText()
        for combo in (self.x_combo, self.y_combo, self.hist_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(numeric)
            combo.blockSignals(False)
        if numeric:
            self.x_combo.setCurrentText(current_x if current_x in numeric else numeric[min(1, len(numeric) - 1)])
            self.y_combo.setCurrentText(current_y if current_y in numeric else numeric[0])
            self.hist_combo.setCurrentText(current_h if current_h in numeric else numeric[0])
        self._render_scatter()
        self._render_histogram()

    def _is_numeric(self, field):
        vals = [v for v in self._values.get(field, []) if v is not None]
        return bool(vals) and all(isinstance(v, (int, float)) for v in vals)

    def _render_scatter(self):
        x_field = self.x_combo.currentText()
        y_field = self.y_combo.currentText()
        self._scatter_feature_ids = []
        self._scatter_fid_to_point = {}
        if x_field not in self._values or y_field not in self._values:
            self.scatter_canvas.clear()
            return
        x_vals = self._values[x_field]
        y_vals = self._values[y_field]
        xs, ys, fids = [], [], []
        for i, (x, y) in enumerate(zip(x_vals, y_vals)):
            if x is not None and y is not None and isinstance(x, (int, float)) and isinstance(y, (int, float)):
                xs.append(x)
                ys.append(y)
                fids.append(i)
        if len(xs) < 2:
            self.scatter_canvas.clear()
            return
        self._scatter_feature_ids = fids
        self._scatter_fid_to_point = {fid: idx for idx, fid in enumerate(fids)}
        self.scatter_canvas.set_data(xs, ys, x_field, y_field)

    def _render_histogram(self):
        field = self.hist_combo.currentText()
        if field not in self._values:
            self.histogram_canvas.clear()
            return
        self.histogram_canvas.set_data(self._values[field], field)

    def highlight_feature(self, fid):
        """反向：地图点击要素后，高亮散点图中对应点。"""
        idx = self._scatter_fid_to_point.get(fid)
        self.scatter_canvas.highlight_point(idx)

    def _on_point_clicked(self, index):
        self.scatter_canvas.highlight_point(index)  # 高亮散点自身
        if 0 <= index < len(self._scatter_feature_ids):
            self.featureSelected.emit(self._scatter_feature_ids[index])

    def _on_blank_clicked(self):
        self.scatter_canvas.highlight_point(None)  # 清除散点高亮
        self.selectionCleared.emit()
