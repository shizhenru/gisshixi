"""结果与报告页：全局/局部摘要 + 图表 + 分析报告。"""
from pathlib import Path

from ...qt_compat import (
    QHBoxLayout,
    QLabel,
    QPixmap,
    QPushButton,
    QFrame,
    QSizePolicy,
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
        self.scatter_box = None
        self.scatter_label = None
        self._scatter_path = ""
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
            self.metric_card_widgets.append(card)
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
        self.chart_tabs = QTabWidget()
        scatter_page = QWidget()
        scatter_layout = QHBoxLayout(scatter_page)
        scatter_layout.setContentsMargins(0, 0, 0, 0)
        scatter_layout.addStretch()
        self.scatter_box = QFrame()
        self.scatter_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.scatter_box.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #dfe8e6; border-radius: 6px; }"
        )
        box_layout = QVBoxLayout(self.scatter_box)
        box_layout.setContentsMargins(10, 10, 10, 10)
        self.scatter_label = QLabel("运行栅格分析并生成散点图后，这里会显示图片")
        self.scatter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scatter_label.setStyleSheet("background: transparent; border: 0;")
        box_layout.addWidget(self.scatter_label)
        scatter_layout.addWidget(self.scatter_box)
        scatter_layout.addStretch()
        self.chart_tabs.addTab(scatter_page, "散点图")
        for name in ["误差直方图", "局部 R² 直方图", "系数直方图", "专题图"]:
            placeholder = QLabel("该图表暂未生成")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.chart_tabs.addTab(placeholder, name)
        body.addWidget(self.chart_tabs)
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
        self._scatter_path = result.artifacts.get("raster_scatter", "")
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
        if not self.scatter_box or not self.scatter_label:
            return
        if not self._scatter_path or not Path(self._scatter_path).exists():
            self.scatter_box.setFixedSize(420, 220)
            self.scatter_label.setPixmap(QPixmap())
            self.scatter_label.setText("本次分析没有生成散点图")
            return
        pixmap = QPixmap(self._scatter_path)
        if pixmap.isNull():
            return
        page_width = self.width() or 1200
        target_width = max(360, int(page_width * 0.5))
        content_width = target_width - 22
        content_height = max(220, round(content_width * pixmap.height() / pixmap.width()))
        self.scatter_box.setFixedSize(target_width, content_height + 22)
        self.scatter_label.setFixedSize(content_width, content_height)
        self.scatter_label.setPixmap(pixmap.scaled(
            content_width,
            content_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        self.scatter_label.setText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_scatter_image()
