"""空间分析页：拉帘式对比 + 带宽区间探索。"""
from ...qt_compat import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from ...widgets import panel_box


class AnalysisPage(QWidget):
    """拉帘式对比两个数据源，并通过带宽区间探索 GWR 结果变化。"""

    statusMessage = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(self._swipe_panel(), 1)
        root.addWidget(self._bandwidth_panel())

    def _swipe_panel(self):
        panel, body = panel_box("SWIPE COMPARE", "拉帘式对比", "同比例尺 · 同范围")
        swipe = QFrame()
        swipe.setObjectName("Panel")
        swipe_layout = QHBoxLayout(swipe)
        swipe_layout.setContentsMargins(0, 0, 0, 0)
        swipe_layout.setSpacing(0)

        left = QFrame()
        left.setStyleSheet("background: #eef5f1;")
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("数据 A"))
        left_layout.addStretch()
        left.setFixedWidth(400)

        divider = QFrame()
        divider.setFixedWidth(3)
        divider.setStyleSheet("background: #2d8c7c;")

        right = QFrame()
        right.setStyleSheet("background: #fdf1e7;")
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("数据 B"), alignment=Qt.AlignmentFlag.AlignRight)
        right_layout.addStretch()

        swipe_layout.addWidget(left)
        swipe_layout.addWidget(divider)
        swipe_layout.addWidget(right, 1)
        body.addWidget(swipe, 1)
        note = QLabel("拉帘对比渲染待实现（可拖动分割线）。左侧数据 A、右侧数据 B。")
        note.setObjectName("Muted")
        body.addWidget(note)
        return panel

    def _bandwidth_panel(self):
        panel, body = panel_box("BANDWIDTH", "带宽区间", "步长 100")
        row = QHBoxLayout()
        row.addWidget(QLabel("100"))
        self.bandwidth_slider = QSlider(Qt.Orientation.Horizontal)
        self.bandwidth_slider.setRange(100, 1000)
        self.bandwidth_slider.setSingleStep(100)
        self.bandwidth_slider.setPageStep(100)
        self.bandwidth_slider.setValue(500)
        self.bandwidth_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.bandwidth_slider.setTickInterval(100)
        row.addWidget(self.bandwidth_slider, 1)
        row.addWidget(QLabel("1000"))
        self.bandwidth_value = QLabel("500")
        self.bandwidth_value.setStyleSheet("color: #2d8c7c; font-weight: 700;")
        row.addWidget(self.bandwidth_value)
        body.addLayout(row)
        self.bandwidth_slider.valueChanged.connect(
            lambda value: self.bandwidth_value.setText(str(value))
        )
        self.bandwidth_slider.valueChanged.connect(
            lambda value: self.statusMessage.emit(f"带宽：{value}")
        )
        return panel
