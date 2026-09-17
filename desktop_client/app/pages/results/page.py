"""结果与报告页：全局/局部摘要 + 图表 + 分析报告。"""
from pathlib import Path

from ...qt_compat import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QDialog,
    QPainter,
    QPixmap,
    QPushButton,
    QRectF,
    QScrollArea,
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


class ClickableImageLabel(QLabel):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class ZoomableImageWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._dragging = False
        self._last_pos = None
        self.setMinimumSize(640, 480)
        self.setStyleSheet("background: #f7faf9;")

    def set_image(self, image_path):
        self._pixmap = QPixmap(image_path) if image_path else QPixmap()
        self._fit_image()
        self.update()

    def _fit_image(self):
        if self._pixmap.isNull() or self.width() <= 0 or self.height() <= 0:
            self._scale = 1.0
            self._offset_x = 0.0
            self._offset_y = 0.0
            return
        self._scale = min(
            (self.width() - 24) / self._pixmap.width(),
            (self.height() - 24) / self._pixmap.height(),
            1.0,
        )
        self._offset_x = 0.0
        self._offset_y = 0.0

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._pixmap.isNull():
            return
        width = self._pixmap.width() * self._scale
        height = self._pixmap.height() * self._scale
        left = (self.width() - width) / 2 + self._offset_x
        top = (self.height() - height) / 2 + self._offset_y
        target = QRectF(left, top, width, height)
        source = QRectF(0, 0, self._pixmap.width(), self._pixmap.height())
        painter.drawPixmap(target, self._pixmap, source)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._dragging:
            self._fit_image()

    def wheelEvent(self, event):
        if self._pixmap.isNull():
            super().wheelEvent(event)
            return
        cursor = event.position()
        old_scale = self._scale
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        new_scale = max(0.1, min(old_scale * factor, 8.0))
        if new_scale == old_scale:
            return
        center_x = self.width() / 2
        center_y = self.height() / 2
        image_x = (cursor.x() - center_x - self._offset_x) / old_scale
        image_y = (cursor.y() - center_y - self._offset_y) / old_scale
        self._scale = new_scale
        self._offset_x = cursor.x() - center_x - image_x * new_scale
        self._offset_y = cursor.y() - center_y - image_y * new_scale
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._last_pos is not None:
            current = event.position()
            self._offset_x += current.x() - self._last_pos.x()
            self._offset_y += current.y() - self._last_pos.y()
            self._last_pos = current
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._last_pos = None
            self.unsetCursor()
            return
        super().mouseReleaseEvent(event)


class ScatterPreviewDialog(QDialog):
    def __init__(self, image_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("散点图放大预览")
        self.resize(1200, 850)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.image_view = ZoomableImageWidget()
        layout.addWidget(self.image_view)
        self.set_image(image_path)

    def set_image(self, image_path):
        self.image_view.set_image(image_path)


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
        self._scatter_preview = None
        self._scatter_path = ""
        self.local_specs = []
        self.local_labels = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        content_layout.addWidget(self._global_summary_panel())
        content_layout.addWidget(self._local_summary_panel())
        content_layout.addWidget(self._charts_panel())
        content_layout.addWidget(self._report_panel())
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

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
            card = MetricCard(prefix, "—", "暂无结果")
            grid.addWidget(card, i // 4, i % 4)
            self.local_labels[key] = (card.value_label, prefix)
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
        self.scatter_label = ClickableImageLabel("运行分析并生成散点图后，这里会显示图片")
        self.scatter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scatter_label.setMinimumSize(640, 570)
        self.scatter_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.scatter_label.setStyleSheet("background: #ffffff; border: 1px solid #dfe8e6; border-radius: 6px;")
        self.scatter_label.doubleClicked.connect(self._open_scatter_preview)
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
            label.setText(str(value))
        self._scatter_path = result.artifacts.get(
            "raster_scatter_matrix",
            result.artifacts.get("scatter", result.artifacts.get("raster_scatter", "")),
        )
        self._refresh_scatter_image()
        if self._scatter_preview is not None and self._scatter_preview.isVisible():
            self._scatter_preview.set_image(self._scatter_path)
        artifact_paths = list(result.artifacts.values())
        if artifact_paths:
            visible_paths = [path for path in artifact_paths if Path(path).suffix.lower() in {".png", ".csv", ".tif", ".tiff"}]
            self.artifacts_text.setText("输出文件：\n" + "\n".join(visible_paths))
        elif result.output_dir:
            self.artifacts_text.setText(f"输出目录：{result.output_dir}")
        pairwise_note = ""
        if result.pairwise_metrics:
            pairwise_note = "\n两两比较：\n" + "\n".join(
                f"{key}: 有效像元 {values.get('valid_cells', '—')}，"
                f"RMSE {values.get('rmse', '—')}，相关系数 {values.get('correlation', '—')}"
                for key, values in result.pairwise_metrics.items()
            )
        self.report_text.setPlainText(
            f"执行引擎：{result.engine}\n任务状态：{result.status}\n运行信息：{result.message}\n"
            f"输出目录：{result.output_dir or '—'}{pairwise_note}"
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

    def _open_scatter_preview(self):
        if not self._scatter_path or not Path(self._scatter_path).exists():
            return
        if self._scatter_preview is None:
            self._scatter_preview = ScatterPreviewDialog(self._scatter_path, self)
        else:
            self._scatter_preview.set_image(self._scatter_path)
        self._scatter_preview.show()
        self._scatter_preview.raise_()
        self._scatter_preview.activateWindow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_scatter_image()
