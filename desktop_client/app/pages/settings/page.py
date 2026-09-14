"""系统设置页：Rscript 运行环境与显示偏好。"""
from ...qt_compat import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from ...widgets import panel_box


class SettingsPage(QWidget):
    """管理运行环境与输出偏好。"""

    rscriptChanged = Signal(str)
    statusMessage = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rscript_input = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        runtime, body = panel_box("RUNTIME", "多语言运行环境", "Python + R")
        row = QHBoxLayout()
        row.addWidget(QLabel("Rscript.exe 路径"))
        self.rscript_input = QLineEdit()
        self.rscript_input.setPlaceholderText("未配置时使用系统 PATH 中的 Rscript")
        row.addWidget(self.rscript_input, 1)
        browse = QPushButton("浏览")
        browse.setObjectName("OutlineButton")
        browse.clicked.connect(self._browse_rscript)
        row.addWidget(browse)
        body.addLayout(row)
        test = QPushButton("测试 R 环境")
        test.setObjectName("PrimaryButton")
        test.clicked.connect(lambda: self.statusMessage.emit("R 环境测试接口待接入，请配置后验证"))
        body.addWidget(test, alignment=Qt.AlignmentFlag.AlignLeft)
        note = QLabel("Python 算法直接由当前解释器运行；R 算法通过 Rscript 子进程运行。两者使用统一 JSON 输入和 JSON 输出格式。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        body.addWidget(note)
        root.addWidget(runtime)

        display, display_body = panel_box("DISPLAY", "显示与输出", "本地")
        for name, description, checked in [
            ("自动保存分析参数", "每次调整模型参数后保存当前配置", True),
            ("显示实验性图层", "允许显示局部误差和样本密度", False),
        ]:
            row = QHBoxLayout()
            labels = QVBoxLayout()
            labels.addWidget(QLabel(name))
            sub = QLabel(description)
            sub.setObjectName("Muted")
            labels.addWidget(sub)
            row.addLayout(labels, 1)
            checkbox = QCheckBox()
            checkbox.setChecked(checked)
            row.addWidget(checkbox)
            display_body.addLayout(row)
        root.addWidget(display)
        root.addStretch()

    def _browse_rscript(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Rscript.exe", "", "Rscript (Rscript.exe);;所有文件 (*.*)")
        if path:
            self.rscript_input.setText(path)
            self.rscriptChanged.emit(path)
