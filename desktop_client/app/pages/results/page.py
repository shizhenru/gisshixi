"""结果与报告页：全局/局部摘要 + 图表 + 分析报告。"""
from ...qt_compat import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from ...widgets import MetricCard, panel_box
from core.models import AnalysisResult


class ResultsPage(QWidget):
    """展示 GWR 分析结果摘要、图表与可复现报告。"""

    exportRequested = Signal()
    statusMessage = Signal(str)

    def __init__(self, result: AnalysisResult | None = None, parent=None):
        super().__init__(parent)
        self.result = result or AnalysisResult()
        self.report_text = None
        self.metric_cards = {}
        self.artifacts_text = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(self._global_summary_panel())
        root.addWidget(self._local_summary_panel())
        root.addWidget(self._charts_panel())
        root.addWidget(self._report_panel(), 1)

    def _global_summary_panel(self):
        panel, body = panel_box("GLOBAL MODEL", "全局模型摘要")
        row = QHBoxLayout()
        row.setSpacing(10)
        metrics = [
            ("R²", "—"), ("调整 R²", "—"), ("AICc", "—"), ("最优带宽", "—"),
            ("ME", "—"), ("MAE", "—"), ("RMSE", "—"), ("相关系数", "—"),
        ]
        for title, value in metrics:
            card = MetricCard(title, value, "暂无结果")
            self.metric_cards[title] = card
            row.addWidget(card)
        body.addLayout(row)
        return panel

    def _local_summary_panel(self):
        panel, body = panel_box("LOCAL SUMMARY", "局部统计摘要")
        row = QHBoxLayout()
        row.setSpacing(10)
        for text in ["局部 R²：—（中位数 —）", "回归系数：—", "显著区域占比：—"]:
            item = QLabel(text)
            item.setStyleSheet("background: #f1f8f5; border: 1px solid #dbece7; border-radius: 6px; padding: 10px;")
            row.addWidget(item, 1)
        body.addLayout(row)
        return panel

    def _charts_panel(self):
        panel, body = panel_box("CHARTS", "图表")
        row = QHBoxLayout()
        row.setSpacing(10)
        for name in ["散点图", "误差直方图", "局部 R² 直方图", "系数直方图", "专题图"]:
            box = QLabel(name)
            box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.setStyleSheet("background: #fbfcfb; border: 1px solid #dfe8e6; border-radius: 6px; padding: 24px 0;")
            row.addWidget(box, 1)
        body.addLayout(row)
        return panel

    def _report_panel(self):
        panel, body = panel_box("REPORT", "分析报告")
        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setPlainText("运行分析后，将在此处展示全局评价指标、局部空间差异说明与可复现的分析摘要。")
        body.addWidget(self.report_text, 1)
        self.artifacts_text = QLabel("输出文件：暂无")
        self.artifacts_text.setObjectName("Muted")
        self.artifacts_text.setWordWrap(True)
        body.addWidget(self.artifacts_text)
        export = QPushButton("↓ 生成报告")
        export.setObjectName("PrimaryButton")
        export.clicked.connect(self.exportRequested.emit)
        body.addWidget(export, alignment=Qt.AlignmentFlag.AlignRight)
        return panel

    def update_result(self, result: AnalysisResult):
        self.result = result
        metric_names = {
            "ME": "me", "MAE": "mae", "RMSE": "rmse",
            "相关系数": "correlation", "有效像元": "valid_cells",
        }
        for title, key in metric_names.items():
            card = self.metric_cards.get(title)
            if card is not None:
                value = result.metrics.get(key, result.metrics.get(title, "—"))
                card.update_value(value, result.engine)
        artifact_paths = list(result.artifacts.values())
        if artifact_paths:
            self.artifacts_text.setText("输出文件：" + "、".join(artifact_paths))
        elif result.output_dir:
            self.artifacts_text.setText(f"输出目录：{result.output_dir}")
        self.report_text.setPlainText(
            f"执行引擎：{result.engine}\n任务状态：{result.status}\n运行信息：{result.message}\n"
            f"输出目录：{result.output_dir or '—'}"
        )
