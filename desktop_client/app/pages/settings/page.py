"""系统设置页：Rscript 运行环境与显示偏好。"""
import shutil
import subprocess
from pathlib import Path

from ...qt_compat import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QObject,
    QPushButton,
    QThread,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
    Slot,
)
from ...widgets import panel_box


class REnvironmentWorker(QObject):
    """后台检测 Rscript 及所需 R 包，避免阻塞界面。"""

    finished = Signal(str, str)  # status(ok/warn/error), detail

    def __init__(self, rscript_path, packages):
        super().__init__()
        self.rscript_path = rscript_path
        self.packages = packages

    @Slot()
    def run(self):
        try:
            exe = (self.rscript_path or "").strip() or shutil.which("Rscript") or ""
            if not exe:
                raise RuntimeError("未配置 Rscript.exe 路径，且在系统 PATH 中未找到 Rscript")
            if not Path(exe).exists():
                raise RuntimeError(f"找不到 Rscript.exe：{exe}")

            ver = subprocess.run(
                [exe, "--version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30, check=False,
            )
            if ver.returncode != 0:
                raise RuntimeError((ver.stderr or ver.stdout or "Rscript 无法执行").strip())
            version = next((line for line in (ver.stdout or "").splitlines() if line.strip()), "R（版本未知）")

            pkg_list = "c(" + ", ".join("'" + p + "'" for p in self.packages) + ")"
            expr = (
                "for (p in " + pkg_list + ") "
                "cat(sprintf('%s %s\\n', p, if (requireNamespace(p, quietly=TRUE)) 'OK' else 'MISSING'))"
            )
            pkg = subprocess.run(
                [exe, "-e", expr], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=180, check=False,
            )
            if pkg.returncode != 0:
                raise RuntimeError((pkg.stderr or pkg.stdout or "R 包检测失败").strip())

            ok, missing = [], []
            for line in pkg.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[-1] in ("OK", "MISSING"):
                    (ok if parts[-1] == "OK" else missing).append(parts[0])

            detail = version
            if ok:
                detail += f"；已装包：{', '.join(ok)}"
            if missing:
                detail += f"；缺失包：{', '.join(missing)}"

            if missing:
                self.finished.emit(
                    "warn",
                    f"R 环境可用（{detail}），但缺少 R 包：{', '.join(missing)}，相关算法将无法运行",
                )
            else:
                self.finished.emit("ok", f"R 环境可用：{detail}")
        except Exception as exc:  # noqa: BLE001 - 测试失败需转成可读信息回传
            self.finished.emit("error", str(exc))


class SettingsPage(QWidget):
    """管理运行环境与输出偏好。"""

    rscriptChanged = Signal(str)
    statusMessage = Signal(str)

    def __init__(self, rscript_path="", parent=None):
        super().__init__(parent)
        self.rscript_input = None
        self.test_button = None
        self.result_label = None
        self._thread = None
        self._worker = None
        self._initial_path = rscript_path
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
        if self._initial_path:
            self.rscript_input.setText(self._initial_path)
        self.rscript_input.editingFinished.connect(self._save_typed_path)
        row.addWidget(self.rscript_input, 1)
        browse = QPushButton("浏览")
        browse.setObjectName("OutlineButton")
        browse.clicked.connect(self._browse_rscript)
        row.addWidget(browse)
        body.addLayout(row)

        self.test_button = QPushButton("测试 R 环境")
        self.test_button.setObjectName("PrimaryButton")
        self.test_button.clicked.connect(self._test_rscript)
        body.addWidget(self.test_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("padding: 4px 0;")
        body.addWidget(self.result_label)

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

    def _save_typed_path(self):
        path = self.rscript_input.text().strip()
        if path:
            self.rscriptChanged.emit(path)

    def _test_rscript(self):
        if self._thread is not None:
            self.statusMessage.emit("正在检测 R 环境，请稍候...")
            return
        path = self.rscript_input.text().strip()
        if path:
            self.rscriptChanged.emit(path)  # 顺带保存手动输入/粘贴的路径
        self.test_button.setEnabled(False)
        self._show_result("info", "正在检测 R 环境，请稍候...")
        self.statusMessage.emit("正在检测 R 环境...")
        self._thread = QThread(self)
        self._worker = REnvironmentWorker(path, ["jsonlite", "sf", "GWmodel", "sp", "terra"])
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_test_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    @Slot(str, str)
    def _on_test_finished(self, status, detail):
        self.test_button.setEnabled(True)
        self._show_result(status, detail)
        self.statusMessage.emit(detail)

    @Slot()
    def _thread_finished(self):
        self._thread = None
        self._worker = None

    def _show_result(self, status, detail):
        color = {
            "ok": "#2d8c7c",
            "warn": "#e78338",
            "error": "#d86659",
            "info": "#a8b7b4",
        }.get(status, "#a8b7b4")
        self.result_label.setText(detail)
        self.result_label.setStyleSheet(f"color: {color}; padding: 4px 0;")
