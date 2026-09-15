"""指标卡：标题 + 大号数值 + 备注，用于结果页等场景。"""
from ..qt_compat import QFrame, QLabel, QVBoxLayout


class MetricCard(QFrame):
    def __init__(self, title, value, note, accent="#2d8c7c", parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 13)
        title_label = QLabel(title)
        title_label.setObjectName("Muted")
        value_label = QLabel(value)
        value_label.setStyleSheet(f"color: {accent}; font-size: 23px; font-weight: 700;")
        note_label = QLabel(note)
        note_label.setObjectName("Muted")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(note_label)
        self.value_label = value_label
        self.note_label = note_label
        self.title_label = title_label

    def set_title(self, title):
        self.title_label.setText(title)

    def update_value(self, value, note=""):
        self.value_label.setText(str(value))
        self.note_label.setText(note)
