"""数据管理页：项目统一参数设置 + 数据目录表格（不一致标红）+ 导入/删除/导出。"""
from pathlib import Path

from ...qt_compat import (
    QAbstractItemView,
    QColor,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    Signal,
)
from ...widgets import panel_box
from core.io.exporters import export_data_catalog


class DataPage(QWidget):
    """登记多源数据，设定项目统一参数并做一致性检查。"""

    statusMessage = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.reference_combo = None
        self.crs_combo = None
        self.resolution_combo = None
        self.extent_combo = None
        self.format_combo = None
        self.table = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 项目统一参数设置
        std, std_body = panel_box("PROJECT STANDARD", "项目统一参数设置")

        ref_row = QHBoxLayout()
        ref_label = QLabel("参考数据源")
        ref_label.setObjectName("Muted")
        ref_row.addWidget(ref_label)
        self.reference_combo = QComboBox()
        self.reference_combo.setFixedHeight(32)
        self.reference_combo.addItem("手动设置")
        ref_row.addWidget(self.reference_combo)
        ref_row.addStretch()
        std_body.addLayout(ref_row)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.crs_combo = self._add_std_field(row, "坐标系", ["CGCS2000 / 3°分带", "WGS 84"])
        self.resolution_combo = self._add_std_field(row, "分辨率", ["500 m", "1000 m", "100 m"])
        self.extent_combo = self._add_std_field(row, "研究区范围", ["武汉市域", "中心城区"])
        self.format_combo = self._add_std_field(row, "数据格式", ["GeoPackage", "Shapefile", "GeoTIFF"])
        row.addStretch()
        std_body.addLayout(row)
        note = QLabel("选择「参考数据源」自动填充统一参数，或手动设置；与统一参数不同的项标红。")
        note.setObjectName("Muted")
        std_body.addWidget(note)
        root.addWidget(std)

        # 数据目录
        catalog, catalog_body = panel_box("DATA CATALOG", "数据目录")
        toolbar = QHBoxLayout()
        import_button = QPushButton("↥ 导入数据")
        import_button.setObjectName("PrimaryButton")
        import_button.clicked.connect(self.import_data)
        delete_button = QPushButton("删除选中")
        delete_button.setObjectName("OutlineButton")
        delete_button.clicked.connect(self.delete_selected)
        export_button = QPushButton("↓ 导出数据清单")
        export_button.setObjectName("OutlineButton")
        export_button.clicked.connect(self.export_data)
        toolbar.addWidget(import_button)
        toolbar.addWidget(delete_button)
        toolbar.addWidget(export_button)
        toolbar.addStretch()
        catalog_body.addLayout(toolbar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["数据集", "类型", "坐标系", "分辨率", "数据格式", "操作"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        catalog_body.addWidget(self.table, 1)
        root.addWidget(catalog, 1)

        self.reference_combo.currentTextChanged.connect(self._on_reference_changed)
        for combo in (self.crs_combo, self.resolution_combo, self.extent_combo, self.format_combo):
            combo.currentTextChanged.connect(self.refresh)
        self._refresh_reference_combo()
        self.refresh()

    def _add_std_field(self, row, label_text, items):
        holder = QVBoxLayout()
        holder.setSpacing(5)
        label = QLabel(label_text)
        label.setObjectName("Muted")
        holder.addWidget(label)
        combo = QComboBox()
        combo.setFixedHeight(32)
        combo.addItems(items)
        holder.addWidget(combo)
        row.addLayout(holder)
        return combo

    @staticmethod
    def _set_combo_value(combo, value):
        if value is None:
            return
        if combo.findText(value) < 0:
            combo.addItem(value)
        combo.setCurrentText(value)

    def _refresh_reference_combo(self):
        current = self.reference_combo.currentText()
        self.reference_combo.blockSignals(True)
        self.reference_combo.clear()
        self.reference_combo.addItem("手动设置")
        for source in self.store.sources:
            self.reference_combo.addItem(source.name)
        self.reference_combo.blockSignals(False)
        items = [self.reference_combo.itemText(i) for i in range(self.reference_combo.count())]
        if current and current in items:
            self.reference_combo.setCurrentText(current)

    def _on_reference_changed(self, name):
        source = next((s for s in self.store.sources if s.name == name), None)
        if source is None:
            self.refresh()
            return
        for combo, value in [
            (self.crs_combo, source.crs),
            (self.resolution_combo, self._resolution(source)),
            (self.extent_combo, source.extent),
            (self.format_combo, self._classify_format(source)),
        ]:
            combo.blockSignals(True)
            self._set_combo_value(combo, value)
            combo.blockSignals(False)
        self.refresh()

    def _classify_format(self, source) -> str:
        suffix = Path(source.path).suffix.lower()
        if suffix in {".gpkg"}:
            return "GeoPackage"
        if suffix in {".shp"}:
            return "Shapefile"
        if suffix in {".tif", ".tiff"}:
            return "GeoTIFF"
        if suffix in {".csv"}:
            return "CSV"
        if suffix in {".xlsx", ".xls"}:
            return "Excel"
        return suffix.lstrip(".") or "其他"

    def _resolution(self, source) -> str:
        return source.records if source.data_type == "栅格数据" else "—"

    def refresh(self, *args):
        del args
        self.table.setRowCount(0)
        std_crs = self.crs_combo.currentText()
        std_res = self.resolution_combo.currentText()
        std_format = self.format_combo.currentText()
        for source in self.store.sources:
            row = self.table.rowCount()
            self.table.insertRow(row)
            data_type = source.data_type
            if source.geometry_type:
                data_type = f"{source.data_type} · {source.geometry_type}"
            fmt = self._classify_format(source)
            res = self._resolution(source)
            values = [source.name, data_type, source.crs, res, fmt]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                self.table.setItem(row, col, item)
            # 一致性标红
            if source.crs != std_crs and source.data_type != "属性数据":
                self._mark_red(row, 2)
            if source.data_type == "栅格数据" and res != std_res and res != "—":
                self._mark_red(row, 3)
            if fmt != std_format and fmt not in ("CSV", "Excel"):
                self._mark_red(row, 4)
            # 操作：标红行可跳转预处理
            if source.crs != std_crs or (source.data_type == "栅格数据" and res != std_res) or (fmt != std_format):
                link = QTableWidgetItem("→ 去预处理")
                link.setForeground(QColor("#2d6bb8"))
                self.table.setItem(row, 5, link)
            self.table.item(row, 0).setToolTip(self._tooltip(source))
        widths = [140, 110, 130, 90, 100, 90]
        for index, width in enumerate(widths):
            self.table.setColumnWidth(index, width)

    def _mark_red(self, row, col):
        item = self.table.item(row, col)
        if item is not None:
            item.setForeground(QColor("#d86659"))
            item.setBackground(QColor("#fdecea"))

    @staticmethod
    def _tooltip(source) -> str:
        parts = []
        if source.fields:
            shown = source.fields[:20]
            suffix = "" if len(source.fields) <= 20 else f" 等 {len(source.fields)} 个"
            parts.append("字段：" + "、".join(shown) + suffix)
        if source.warnings:
            parts.append("提示：" + "；".join(source.warnings))
        return "\n".join(parts)

    def import_data(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择空间数据", "",
            "空间数据 (*.csv *.xlsx *.xls *.xlsm *.json *.geojson *.shp *.gpkg *.tif *.tiff *.asc *.img);;所有文件 (*.*)",
        )
        if path:
            source = self.store.add_source(path)
            self._refresh_reference_combo()
            self.refresh()
            self.statusMessage.emit(source.summary())

    def delete_selected(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            self.statusMessage.emit("请先在表格中选择要删除的数据行")
            return
        names = [self.store.sources[row].name for row in rows if row < len(self.store.sources)]
        reply = QMessageBox.question(
            self, "删除数据",
            f"确定移除选中的 {len(rows)} 条数据吗？\n（不会删除磁盘上的文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for row in rows:
            if row < len(self.store.sources):
                self.store.remove_source(self.store.sources[row].path)
        self._refresh_reference_combo()
        self.refresh()
        self.statusMessage.emit(f"已移除：{'、'.join(names)}")

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出数据清单", "data_catalog.csv", "CSV 文件 (*.csv)")
        if path:
            export_data_catalog(path, self.store.sources)
            self.statusMessage.emit(f"数据清单已导出：{Path(path).name}")
