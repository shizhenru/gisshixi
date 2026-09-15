"""结果与报告页：全局/局部摘要 + 图表 + 分析报告。"""
from pathlib import Path

from ...qt_compat import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPixmap,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QTabWidget,
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
        self.metric_card_widgets = []
        self.artifacts_text = None
        self.chart_tabs = None
        self.scatter_label = None
        self._scatter_path = ""
        self.local_specs = []
        self.local_labels = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(self._global_summary_panel())
        root.addWidget(self._local_summary_panel())
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        bottom.addWidget(self._charts_panel(), 3)
        bottom.addWidget(self._report_panel(), 2)
        root.addLayout(bottom, 1)

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
            self.metric_card_widgets.append(card)
            row.addWidget(card)
        body.addLayout(row)
        return panel

    def _local_summary_panel(self):
        panel, body = panel_box("LOCAL SUMMARY", "局部统计摘要")
        self.local_specs = [
            ("local_r2_median", "局部 R² 中位数"),
            ("coefficient_median", "回归系数中位数"),
            ("local_corr_median", "局部相关系数中位数"),
            ("lme_median", "LME 中位数"),
            ("lmae_median", "LMAE 中位数"),
            ("lmre_median", "LMRE 中位数"),
            ("lrmse_median", "LRMSE 中位数"),
        ]
        self.local_labels = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (key, prefix) in enumerate(self.local_specs):
            item = QLabel(f"{prefix}：—")
            item.setStyleSheet("background: #f1f8f5; border: 1px solid #dbece7; border-radius: 6px; padding: 8px;")
            grid.addWidget(item, i // 4, i % 4)
            self.local_labels[key] = (item, prefix)
        body.addLayout(grid)
        return panel

    def _charts_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        self.chart_tabs = QTabWidget()
        scatter_page = QWidget()
        scatter_layout = QVBoxLayout(scatter_page)
        scatter_layout.setContentsMargins(8, 8, 8, 8)
        self.scatter_label = QLabel("运行分析并生成散点图后，这里会显示图片")
        self.scatter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scatter_label.setMinimumSize(320, 240)
        self.scatter_label.setStyleSheet("background: #ffffff; border: 1px solid #dfe8e6; border-radius: 6px;")
        scatter_layout.addWidget(self.scatter_label)
        self.chart_tabs.addTab(scatter_page, "散点图")
        for name in ["误差直方图", "局部 R² 直方图", "系数直方图", "专题图"]:
            placeholder = QLabel("该图表暂未生成")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.chart_tabs.addTab(placeholder, name)
        layout.addWidget(self.chart_tabs)
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
        is_raster = result.engine == "R / terra"
        raster_titles = ["ME", "MAE", "MRE", "RMSE", "相关系数", "有效像元"]
        attribute_titles = ["R²", "调整 R²", "AICc", "最优带宽", "ME", "MAE", "RMSE", "相关系数"]
        titles = raster_titles if is_raster else attribute_titles
        for index, card in enumerate(self.metric_card_widgets):
            card.setVisible(index < len(titles))
            if index < len(titles):
                card.set_title(titles[index])
                self.metric_cards[titles[index]] = card
        metric_names = {
            "ME": "me", "MAE": "mae", "MRE": "mre", "RMSE": "rmse",
            "相关系数": "correlation", "有效像元": "valid_cells",
        }
        for title, key in metric_names.items():
            card = self.metric_cards.get(title)
            if card is not None:
                value = result.metrics.get(key, result.metrics.get(title, "—"))
                card.update_value(value, result.engine)
        for key, (label, prefix) in self.local_labels.items():
            value = result.metrics.get(key, "—")
            label.setText(f"{prefix}：{value}")
        self._scatter_path = result.artifacts.get("scatter", result.artifacts.get("raster_scatter", ""))
        self._refresh_scatter_image()
        artifact_paths = list(result.artifacts.values())
        if artifact_paths:
            visible_paths = [path for path in artifact_paths if Path(path).suffix.lower() in {".png", ".csv", ".tif", ".tiff"}]
            self.artifacts_text.setText("输出文件：\n" + "\n".join(visible_paths))
        elif result.output_dir:
            self.artifacts_text.setText(f"输出目录：{result.output_dir}")
        self.report_text.setPlainText(
            f"执行引擎：{result.engine}\n任务状态：{result.status}\n运行信息：{result.message}\n"
            f"输出目录：{result.output_dir or '—'}"
        )

    def _refresh_scatter_image(self):
        if not self.scatter_label:
            return
        if not self._scatter_path or not Path(self._scatter_path).exists():
            self.scatter_label.setPixmap(QPixmap())
            self.scatter_label.setText("本次分析没有生成散点图")
            return
        pixmap = QPixmap(self._scatter_path)
        if pixmap.isNull():
            return
        self.scatter_label.setText("")
        size = self.scatter_label.size()
        if size.width() > 0 and size.height() > 0:
            self.scatter_label.setPixmap(pixmap.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_scatter_image()
