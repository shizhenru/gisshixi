"""结果与报告页：全局/局部摘要 + 图表 + 分析报告。"""
import csv
import math
import os
from pathlib import Path

from ...qt_compat import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QDialog,
    QComboBox,
    QAbstractItemView,
    QPainter,
    QPixmap,
    QPushButton,
    QRectF,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
    Qt,
    Signal,
)
from ...widgets import MetricCard, panel_box
from core.io.exporters import build_report_text
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
        self.raster_identity_cards = []
        self.raster_identity_layout = None
        self.artifacts_text = None
        self.chart_tabs = None
        self.scatter_label = None
        self.pairwise_table = None
        self._scatter_preview = None
        self._scatter_path = ""
        self.local_specs = []
        self.local_labels = {}
        self.local_summary_panel = None
        self.geometry_table_combo = None
        self.geometry_image_labels = {}
        self.geometry_tab_indices = []
        self._geometry_paths = {}
        self.figure_labels = {}      # 属性模式：误差/局部R²/系数直方图 + 专题图
        self._figure_paths = {}
        self.raster_pair_pages = []
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
        self.local_summary_panel = self._local_summary_panel()
        content_layout.addWidget(self.local_summary_panel)
        content_layout.addWidget(self._charts_panel())
        content_layout.addWidget(self._report_panel())
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _global_summary_panel(self):
        panel, body = panel_box("GLOBAL MODEL", "全局模型摘要")
        self.global_panel = panel
        identity_grid = QGridLayout()
        identity_grid.setSpacing(8)
        self.raster_identity_layout = identity_grid
        body.addLayout(identity_grid)
        # 用网格而非单行：8 张卡一行放不下会被右边缘截断，这里每行 4 张自动换行
        # （与下面「局部统计摘要」的排法保持一致）
        grid = QGridLayout()
        grid.setSpacing(8)
        metrics = [
            ("R²", "—"), ("调整 R²", "—"), ("AICc", "—"), ("最优带宽", "—"),
            ("ME", "—"), ("MAE", "—"), ("RMSE", "—"), ("相关系数", "—"),
        ]
        for index, (title, value) in enumerate(metrics):
            card = MetricCard(title, value, "暂无结果")
            self.metric_cards[title] = card
            self.metric_card_widgets.append(card)
            grid.addWidget(card, index // 4, index % 4)
        body.addLayout(grid)
        return panel

    @staticmethod
    def _raster_label(index):
        value = index + 1
        label = ""
        while value:
            value, remainder = divmod(value - 1, 26)
            label = chr(65 + remainder) + label
        return label

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
        # 四类图由属性 GWR 在 R 端生成（gwr_attribute.R 的 make_figures），
        # 路径经 artifacts 传回；专题图一张页签里放 R² 与 LME 两幅。
        for name, keys in (
            ("误差直方图", ("error_hist",)),
            ("局部 R² 直方图", ("local_r2_hist",)),
            ("系数直方图", ("coef_hist",)),
            ("专题图", ("map_r2", "map_lme")),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(8, 8, 8, 8)
            page_layout.setSpacing(8)
            for key in keys:
                label = ClickableImageLabel("运行分析后这里会显示图件")
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setMinimumHeight(240)
                label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                label.setStyleSheet(
                    "background: #ffffff; border: 1px solid #dfe8e6; border-radius: 6px;"
                )
                label.doubleClicked.connect(lambda k=key: self._open_figure_preview(k))
                page_layout.addWidget(label, 1)
                self.figure_labels[key] = label
            self.chart_tabs.addTab(page, name)
        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(8, 8, 8, 8)
        table_toolbar = QHBoxLayout()
        table_toolbar.addWidget(QLabel("结果表"))
        self.geometry_table_combo = QComboBox()
        self.geometry_table_combo.setMinimumWidth(260)
        self.geometry_table_combo.currentIndexChanged.connect(self._refresh_selected_geometry_table)
        self.geometry_table_combo.hide()
        table_toolbar.addWidget(self.geometry_table_combo)
        table_toolbar.addStretch()
        table_layout.addLayout(table_toolbar)
        self.pairwise_table = QTableWidget(0, 0)
        self.pairwise_table.setAlternatingRowColors(True)
        self.pairwise_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pairwise_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.pairwise_table.setSortingEnabled(True)
        self.pairwise_table.setMinimumHeight(420)
        table_layout.addWidget(self.pairwise_table)
        self.chart_tabs.addTab(table_page, "总体对比")
        geometry_specs = [
            ("figure_polygon_iou", "面 IoU"),
            ("figure_centroid_distance_m", "质心距离"),
            ("figure_absolute_relative_area_error", "面积误差"),
            ("figure_absolute_relative_perimeter_error", "周长误差"),
        ]
        for key, title in geometry_specs:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            image_label = ClickableImageLabel("本次分析未生成该图件")
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image_label.setMinimumSize(640, 570)
            image_label.setStyleSheet("background: #ffffff; border: 1px solid #dfe8e6; border-radius: 6px;")
            image_label.doubleClicked.connect(lambda key=key: self._open_geometry_preview(key))
            page_layout.addWidget(image_label)
            index = self.chart_tabs.addTab(page, title)
            self.chart_tabs.setTabVisible(index, False)
            self.geometry_tab_indices.append(index)
            self.geometry_image_labels[key] = image_label
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
        button_row = QHBoxLayout()
        self.open_output_button = QPushButton("打开结果目录")
        self.open_output_button.setObjectName("OutlineButton")
        self.open_output_button.clicked.connect(self._open_output_directory)
        button_row.addStretch()
        button_row.addWidget(self.open_output_button)
        button_row.addWidget(export)
        body.addLayout(button_row)
        return panel

    def update_result(self, result: AnalysisResult):
        self.result = result
        is_raster = result.engine == "R / terra"
        is_geometry = result.engine == "外接矩形法几何交叉验证"
        raster_titles = ["ME", "MAE", "MRE", "RMSE", "相关系数", "有效像元"]
        attribute_titles = ["R²", "调整 R²", "AICc", "最优带宽", "ME", "MAE", "RMSE", "相关系数"]
        geometry_titles = ["类别数", "候选对", "推荐阈值", "推荐阈值匹配对"]
        titles = geometry_titles if is_geometry else raster_titles if is_raster else attribute_titles
        for index, card in enumerate(self.metric_card_widgets):
            card.setVisible(not is_raster and index < len(titles))
            if index < len(titles):
                card.set_title(titles[index])
                self.metric_cards[titles[index]] = card
        # 属性模式的四张卡（R² / 调整 R² / AICc / 最优带宽）此前没有映射，
        # 导致算法返回了值、界面上却一直显示「—」。多余键在其它模式下取不到卡片、会被跳过。
        metric_names = {
            "ME": "me", "MAE": "mae", "MRE": "mre", "RMSE": "rmse",
            "相关系数": "correlation", "有效像元": "valid_cells",
            "R²": "r2", "调整 R²": "adj_r2", "AICc": "aicc", "最优带宽": "bandwidth",
        }
        if is_geometry:
            metric_names = {
                "类别数": "categories", "候选对": "candidate_pairs",
                "推荐阈值": "recommended_threshold", "推荐阈值匹配对": "matched_pairs",
            }
        for title, key in metric_names.items():
            card = self.metric_cards.get(title)
            if card is not None:
                value = result.metrics.get(key, result.metrics.get(title, "—"))
                card.update_value(value, result.engine)
        self.local_summary_panel.setVisible(not is_geometry and not is_raster)
        self._refresh_raster_identity_cards(result, is_raster)
        title = self.global_panel.findChild(QLabel, "PanelTitle")
        kicker = self.global_panel.findChild(QLabel, "Kicker")
        if title is not None:
            title.setText("影像编号" if is_raster else "全局模型摘要")
        if kicker is not None:
            kicker.setText("RASTER INPUTS" if is_raster else "GLOBAL MODEL")
        for key, (label, prefix) in self.local_labels.items():
            value = result.metrics.get(key, "—")
            label.setText(str(value))
        self._set_geometry_mode(is_geometry, is_raster)
        if is_geometry:
            self._refresh_geometry_table_choices(result)
            self._refresh_geometry_images(result)
        elif is_raster:
            self._refresh_raster_pair_tables(result)
            self._refresh_pairwise_table(result)
        else:
            self._refresh_pairwise_table(result)
        self._scatter_path = result.artifacts.get(
            "raster_scatter_matrix",
            result.artifacts.get("scatter", result.artifacts.get("raster_scatter", "")),
        )
        self._refresh_scatter_image()
        self._refresh_figure_tabs(result)
        if self._scatter_preview is not None and self._scatter_preview.isVisible():
            self._scatter_preview.set_image(self._scatter_path)
        artifact_paths = list(result.artifacts.values())
        if artifact_paths:
            # .shp 也要列出来：属性 GWR 的主要产物就是结果 SHP，此前被后缀白名单滤掉了
            visible_paths = [path for path in artifact_paths
                             if Path(path).suffix.lower() in {".png", ".csv", ".json", ".md", ".tif", ".tiff", ".shp"}]
            self.artifacts_text.setText("输出文件：\n" + "\n".join(visible_paths))
        elif result.output_dir:
            self.artifacts_text.setText(f"输出目录：{result.output_dir}")
        report_path = result.artifacts.get("report", "") if is_geometry else ""
        if report_path and Path(report_path).exists():
            try:
                self.report_text.setPlainText(Path(report_path).read_text(encoding="utf-8"))
            except OSError:
                self.report_text.setPlainText(result.message)
        else:
            self.report_text.setPlainText(build_report_text(
                {
                    "engine": result.engine,
                    "status": result.status,
                    "metrics": result.metrics,
                    "pairwise_metrics": result.pairwise_metrics,
                    "local_statistics": result.local_statistics,
                    "message": result.message,
                },
                {
                    "engine": result.engine,
                    "status": result.status,
                    "output_dir": result.output_dir or "—",
                },
            ))

    def _set_geometry_mode(self, enabled, is_raster=False):
        self.geometry_table_combo.setVisible(enabled)
        self._clear_raster_pair_tables()
        for index in range(5):
            visible = not enabled and (not is_raster or index == 0)
            self.chart_tabs.setTabVisible(index, visible)
        self.chart_tabs.setTabVisible(5, not enabled)
        for index in self.geometry_tab_indices:
            self.chart_tabs.setTabVisible(index, enabled)
        self.chart_tabs.setCurrentIndex(self.geometry_tab_indices[0] if enabled else (0 if is_raster else 0))

    def _clear_raster_pair_tables(self):
        for page in self.raster_pair_pages:
            index = self.chart_tabs.indexOf(page)
            if index >= 0:
                self.chart_tabs.removeTab(index)
            page.deleteLater()
        self.raster_pair_pages = []

    def _refresh_raster_identity_cards(self, result, enabled):
        names = result.raster_names if enabled else []
        display_names = result.raster_display_names if enabled else []
        while len(self.raster_identity_cards) < len(names):
            index = len(self.raster_identity_cards)
            card = MetricCard(f"影像 {self._raster_label(index)}", "—", "暂无结果")
            self.raster_identity_cards.append(card)
            self.raster_identity_layout.addWidget(card, index // 4, index % 4)
        for index, card in enumerate(self.raster_identity_cards):
            visible = index < len(names)
            card.setVisible(visible)
            if visible:
                card.set_title(f"影像 {self._raster_label(index)}")
                display_name = display_names[index] if index < len(display_names) else names[index]
                card.update_value(Path(str(display_name)).name, result.engine)

    def _refresh_raster_pair_tables(self, result):
        self._clear_raster_pair_tables()
        names = result.raster_names
        name_labels = {name: self._raster_label(index) for index, name in enumerate(names)}
        stats_labels = {
            "local_r2": "局部 R²",
            "coefficient": "回归系数",
            "local_corr": "局部相关系数",
            "lme": "LME",
            "lmae": "LMAE",
            "lmre": "LMRE",
            "lrmse": "LRMSE",
        }
        headers = ["局部指标", "有效数", "最小值", "Q1", "中位数", "Q3", "最大值", "均值", "标准差"]
        for pair_key, statistics in result.local_statistics.items():
            left, _, right = pair_key.partition("__vs__")
            title = f"{name_labels.get(left, left)}-{name_labels.get(right, right)}"
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(8, 8, 8, 8)
            table = QTableWidget(0, len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setAlternatingRowColors(True)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setMinimumHeight(420)
            rows = []
            for key, label in stats_labels.items():
                values = statistics.get(key, {}) or {}
                if not self._has_statistic_values(values):
                    continue
                rows.append([
                    label,
                    values.get("count", "—"), values.get("min", "—"),
                    values.get("q1", "—"), values.get("median", "—"),
                    values.get("q3", "—"), values.get("max", "—"),
                    values.get("mean", "—"), values.get("sd", "—"),
                ])
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for column_index, value in enumerate(row):
                    table.setItem(row_index, column_index, QTableWidgetItem(self._format_statistic(value)))
            table.resizeColumnsToContents()
            table.setSortingEnabled(True)
            page_layout.addWidget(table)
            tab_index = self.chart_tabs.addTab(page, title)
            self.chart_tabs.setTabToolTip(tab_index, f"{left} vs {right}")
            self.raster_pair_pages.append(page)

    @staticmethod
    def _has_statistic_values(values):
        if not isinstance(values, dict):
            return False
        count = ResultsPage._numeric_statistic_value(values.get("count"))
        if count is not None and count <= 0:
            return False
        statistic_keys = ("min", "q1", "median", "q3", "max", "mean", "sd")
        return any(
            ResultsPage._numeric_statistic_value(values.get(key)) is not None
            for key in statistic_keys
        )

    @staticmethod
    def _numeric_statistic_value(value):
        if isinstance(value, bool) or value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _format_statistic(value):
        number = ResultsPage._numeric_statistic_value(value)
        if number is not None:
            return f"{number:.6g}"
        if value is None or str(value).strip().lower() in {"", "na", "nan", "none", "null", "—", "-"}:
            return "—"
        return str(value)

    def _refresh_geometry_table_choices(self, result):
        choices = [
            ("总体阈值汇总", "overall_summary"),
            ("分类阈值汇总", "category_summary"),
            ("全部匹配明细", "matches"),
            ("推荐阈值 GW 指标", "gw_metrics"),
        ]
        self.geometry_table_combo.blockSignals(True)
        self.geometry_table_combo.clear()
        for label, key in choices:
            path = result.artifacts.get(key, "")
            if path and Path(path).exists():
                self.geometry_table_combo.addItem(label, path)
        self.geometry_table_combo.blockSignals(False)
        self._refresh_selected_geometry_table()

    def _refresh_selected_geometry_table(self, *_):
        if not self.geometry_table_combo or self.geometry_table_combo.count() == 0:
            return
        path = self.geometry_table_combo.currentData()
        headers, rows = self._read_csv_rows(path, max_rows=5000)
        self._fill_result_table(headers, rows)
        if path and len(rows) == 5000:
            self.statusMessage.emit("匹配明细较大，客户端仅预览前 5,000 行；CSV 文件保留全部数据")

    @staticmethod
    def _read_csv_rows(path, max_rows=5000):
        if not path or not Path(path).exists():
            return [], []
        try:
            with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = []
                for index, row in enumerate(reader):
                    if index >= max_rows:
                        break
                    rows.append(row)
                return reader.fieldnames or [], rows
        except (OSError, UnicodeError):
            return [], []

    def _fill_result_table(self, headers, rows):
        self.pairwise_table.setSortingEnabled(False)
        self.pairwise_table.clear()
        self.pairwise_table.setColumnCount(len(headers))
        self.pairwise_table.setHorizontalHeaderLabels(headers)
        self.pairwise_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, header in enumerate(headers):
                value = row.get(header, "")
                self.pairwise_table.setItem(row_index, column_index, QTableWidgetItem(str(value) if value is not None else ""))
        self.pairwise_table.resizeColumnsToContents()
        self.pairwise_table.setSortingEnabled(True)

    def _refresh_figure_tabs(self, result):
        """把属性 GWR 生成的图件填进对应页签；其它模式没有这些产物则提示未生成。"""
        for key, label in self.figure_labels.items():
            path = result.artifacts.get(key, "")
            self._figure_paths[key] = path
            self._set_image_label(label, path, "本次分析未生成该图件")

    def _open_figure_preview(self, key):
        path = self._figure_paths.get(key, "")
        if not path or not Path(path).exists():
            return
        if self._scatter_preview is None:
            self._scatter_preview = ScatterPreviewDialog(path, self)
        else:
            self._scatter_preview.set_image(path)
        self._scatter_preview.show()
        self._scatter_preview.raise_()
        self._scatter_preview.activateWindow()

    def _refresh_geometry_images(self, result):
        self._geometry_paths = {}
        for key, label in self.geometry_image_labels.items():
            path = result.artifacts.get(key, "")
            self._geometry_paths[key] = path
            self._set_image_label(label, path, "本次分析未生成该图件")

    @staticmethod
    def _set_image_label(label, path, missing_text):
        if not path or not Path(path).exists():
            label.setPixmap(QPixmap())
            label.setText(missing_text)
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            label.setText("图件读取失败")
            return
        label.setText("")
        label.setPixmap(pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _open_geometry_preview(self, key):
        path = self._geometry_paths.get(key, "")
        if not path or not Path(path).exists():
            return
        if self._scatter_preview is None:
            self._scatter_preview = ScatterPreviewDialog(path, self)
        else:
            self._scatter_preview.set_image(path)
        self._scatter_preview.setWindowTitle("几何交叉验证图件预览")
        self._scatter_preview.show()
        self._scatter_preview.raise_()
        self._scatter_preview.activateWindow()

    def _open_output_directory(self):
        path = self.result.output_dir
        if not path or not Path(path).exists():
            self.statusMessage.emit("本次结果目录不存在")
            return
        try:
            os.startfile(path)
        except OSError as exc:
            self.statusMessage.emit(f"无法打开结果目录：{exc}")

    def _refresh_pairwise_table(self, result: AnalysisResult):
        if self.pairwise_table is None:
            return
        headers, rows = self._load_pairwise_rows(result)
        self._fill_result_table(headers, rows)

    @staticmethod
    def _load_pairwise_rows(result: AnalysisResult):
        csv_path = ""
        for key, path in result.artifacts.items():
            if key in {"pairwise_global_metrics", "pairwise_metrics"} or Path(path).name in {
                "pairwise_global_metrics.csv",
                "pairwise_metrics.csv",
            }:
                csv_path = path
                break
        if csv_path and Path(csv_path).exists():
            try:
                with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    return reader.fieldnames or [], list(reader)
            except (OSError, UnicodeError):
                pass

        rows = []
        for pair_name, values in result.pairwise_metrics.items():
            row = {"pair": pair_name}
            row.update(values)
            rows.append(row)
        if not rows:
            return [], []
        headers = list(rows[0])
        for row in rows[1:]:
            for header in row:
                if header not in headers:
                    headers.append(header)
        return headers, rows

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
        for key, label in self.figure_labels.items():
            self._set_image_label(label, self._figure_paths.get(key, ""), "本次分析未生成该图件")
        for key, label in self.geometry_image_labels.items():
            self._set_image_label(label, self._geometry_paths.get(key, ""), "本次分析未生成该图件")
