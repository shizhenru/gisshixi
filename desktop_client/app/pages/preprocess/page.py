"""预处理页：工具箱（工具目录 + 参数面板 + 运行历史）。"""
from pathlib import Path

from ...qt_compat import (
    QColor,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QObject,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QThread,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
    Slot,
)
from ...widgets import clear_layout, panel_box
from core.raster_processing import RasterPreprocessor, collect_raster_sources, is_aligned_output

# (分类, 工具名) —— 目前只有「栅格对齐」接入了真实处理，其余为待实现占位。
TOOLS = [
    ("栅格", "栅格对齐（统一 CRS/分辨率/范围）"),
    ("栅格", "重采样"),
    ("栅格", "掩膜提取"),
    ("矢量", "裁剪"),
    ("矢量", "缓冲区"),
    ("投影", "坐标转换"),
    ("数据质量", "缺失值检查"),
    ("格式转换", "格式转换"),
    ("数据变换", "对数变换"),
    ("数据变换", "标准化"),
]


class _RasterAlignWorker(QObject):
    """后台线程执行栅格对齐，避免大栅格重投影阻塞 UI。"""

    finished = Signal(object, str)  # (RasterPreprocessResult|None, error)
    progress = Signal(str)

    def __init__(self, preprocessor, sources, reference, selected_paths):
        super().__init__()
        self._preprocessor = preprocessor
        self._sources = sources
        self._reference = reference
        self._selected_paths = selected_paths

    @Slot()
    def run(self):
        try:
            result = self._preprocessor.preprocess(
                self._sources, self._reference, self._selected_paths,
                progress_callback=lambda message: self.progress.emit(message),
            )
            self.finished.emit(result, "")
        except Exception as exc:  # noqa: BLE001 - 失败以错误文本回传
            self.finished.emit(None, str(exc))


class PreprocessPage(QWidget):
    """工具箱式预处理界面。"""

    statusMessage = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.preprocessor = RasterPreprocessor(store.project_dir)
        self.tool_list = None
        self.dynamic_body = None
        self.progress = None
        self.log = None
        self.raster_list = None
        self.save_result_button = None
        self._last_align_result = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索工具…")
        self.search_input.textChanged.connect(self._filter_tools)
        root.addWidget(self.search_input)

        # 主体：工具目录 + 参数面板
        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._catalog_panel())
        body.addWidget(self._parameter_panel(), 1)
        root.addLayout(body, 1)

        # 运行历史
        root.addWidget(self._history_panel())

    def _catalog_panel(self):
        panel, pbody = panel_box("TOOLBOX", "工具目录")
        self.tool_list = QListWidget()
        current_category = None
        for category, tool in TOOLS:
            if category != current_category:
                header = QListWidgetItem(f"▾ {category}")
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setForeground(QColor("#849295"))
                self.tool_list.addItem(header)
                current_category = category
            item = QListWidgetItem(f"　{tool}")
            item.setData(Qt.ItemDataRole.UserRole, tool)
            self.tool_list.addItem(item)
        self.tool_list.currentItemChanged.connect(self._on_tool_selected)
        pbody.addWidget(self.tool_list, 1)
        panel.setFixedWidth(270)
        return panel

    def _parameter_panel(self):
        panel = QFrame()
        panel.setObjectName("Panel")
        body = QVBoxLayout(panel)
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(10)
        self.param_title = QLabel("栅格对齐（统一 CRS/分辨率/范围）")
        self.param_title.setObjectName("PanelTitle")
        body.addWidget(self.param_title)
        self.param_desc = QLabel("将多个栅格统一到同一坐标系、分辨率与范围。")
        self.param_desc.setObjectName("Muted")
        self.param_desc.setWordWrap(True)
        body.addWidget(self.param_desc)
        self.dynamic_body = QVBoxLayout()
        self.dynamic_body.setSpacing(10)
        body.addLayout(self.dynamic_body)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        body.addWidget(self.progress)
        body.addStretch()
        self._show_raster_align_params()
        return panel

    def _history_panel(self):
        panel, body = panel_box("HISTORY", "运行历史")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("暂无运行记录")
        body.addWidget(self.log, 1)
        panel.setFixedHeight(150)
        return panel

    def _show_raster_align_params(self):
        """栅格对齐工具的参数（唯一已接入真实处理的工具）。"""
        clear_layout(self.dynamic_body)
        label = QLabel("参考栅格")
        label.setObjectName("Muted")
        self.dynamic_body.addWidget(label)
        self.ref_combo = QComboBox()
        self.ref_combo.setFixedHeight(32)
        self.dynamic_body.addWidget(self.ref_combo)
        selected_label = QLabel("本次处理栅格（至少选择两个）")
        selected_label.setObjectName("Muted")
        self.dynamic_body.addWidget(selected_label)
        self.raster_list = QListWidget()
        self.raster_list.setMinimumHeight(110)
        self.raster_list.setMaximumHeight(170)
        self.raster_list.itemChanged.connect(self._on_raster_item_changed)
        self.dynamic_body.addWidget(self.raster_list)
        selection_buttons = QHBoxLayout()
        select_all = QPushButton("全选")
        select_all.setObjectName("OutlineButton")
        select_all.clicked.connect(lambda: self._set_all_rasters(True))
        clear_selection = QPushButton("清空")
        clear_selection.setObjectName("OutlineButton")
        clear_selection.clicked.connect(lambda: self._set_all_rasters(False))
        selection_buttons.addWidget(select_all)
        selection_buttons.addWidget(clear_selection)
        selection_buttons.addStretch()
        self.dynamic_body.addLayout(selection_buttons)
        run = QPushButton("▶ 运行")
        run.setObjectName("PrimaryButton")
        run.clicked.connect(self._run_raster_align)
        self.dynamic_body.addWidget(run)
        self.run_button = run
        save = QPushButton("保存结果…")
        save.setObjectName("OutlineButton")
        save.setToolTip("将对齐后的栅格结果另存到指定目录（关闭软件后临时文件会被清理）")
        save.clicked.connect(self._save_align_result)
        save.setEnabled(False)
        self.dynamic_body.addWidget(save)
        self.save_result_button = save
        self._refresh_ref_combo()

    def _refresh_ref_combo(self):
        current_reference = self.ref_combo.currentData()
        current_selected = self._selected_raster_paths()
        manifest = self.preprocessor.latest_manifest() or {}
        manifest_selected = set(manifest.get("selected_sources", []))
        if not current_selected:
            current_selected = manifest_selected
        self.ref_combo.clear()
        rasters = [s for s in collect_raster_sources(self.store.sources) if not is_aligned_output(s.path)]
        for source in rasters:
            self.ref_combo.addItem(source.name, source.path)
        if rasters:
            reference_index = next((i for i, source in enumerate(rasters) if source.path == current_reference), 0)
            self.ref_combo.setCurrentIndex(reference_index)
        reference_path = self.ref_combo.currentData()
        if not current_selected:
            current_selected = {source.path for source in rasters[:2]}
        if reference_path:
            current_selected.add(reference_path)
        self.raster_list.blockSignals(True)
        self.raster_list.clear()
        for source in rasters:
            item = QListWidgetItem(f"{source.icon}  {source.name} · {source.records}")
            item.setData(Qt.ItemDataRole.UserRole, source.path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if source.path in current_selected else Qt.CheckState.Unchecked)
            self.raster_list.addItem(item)
        self.raster_list.blockSignals(False)

    def _selected_raster_paths(self):
        if self.raster_list is None:
            return set()
        return {
            self.raster_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.raster_list.count())
            if self.raster_list.item(i).checkState() == Qt.CheckState.Checked
        }

    def _on_raster_item_changed(self, item):
        reference_path = self.ref_combo.currentData()
        if reference_path and item.data(Qt.ItemDataRole.UserRole) == reference_path and item.checkState() != Qt.CheckState.Checked:
            self.raster_list.blockSignals(True)
            item.setCheckState(Qt.CheckState.Checked)
            self.raster_list.blockSignals(False)

    def _set_all_rasters(self, checked):
        self.raster_list.blockSignals(True)
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.raster_list.count()):
            self.raster_list.item(i).setCheckState(state)
        self.raster_list.blockSignals(False)
        if not checked and self.ref_combo.currentData():
            reference_path = self.ref_combo.currentData()
            for i in range(self.raster_list.count()):
                item = self.raster_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == reference_path:
                    item.setCheckState(Qt.CheckState.Checked)
                    break

    def _on_tool_selected(self, current, previous):
        del previous
        if current is None:
            return
        tool = current.data(Qt.ItemDataRole.UserRole)
        if not tool:
            return
        self.param_title.setText(tool)
        if tool.startswith("栅格对齐"):
            self.param_desc.setText("将多个栅格统一到同一坐标系、分辨率与范围。")
            self._show_raster_align_params()
        else:
            self.param_desc.setText("该工具参数待实现。")

    def _run_raster_align(self):
        selected_paths = self._selected_raster_paths()
        if len(selected_paths) < 2:
            self.statusMessage.emit("请至少选择两个栅格数据集")
            self._log("栅格对齐：失败（选择的栅格不足）")
            return
        reference = self.ref_combo.currentData() or ""
        self.run_button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.statusMessage.emit("正在统一栅格坐标系、分辨率和范围…")
        thread = QThread(self)
        worker = _RasterAlignWorker(self.preprocessor, self.store.sources, reference, selected_paths)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_align_progress)
        worker.finished.connect(self._on_align_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # 持有引用，避免线程/工作对象被 GC 导致 started 信号不触发。
        self._align_thread = thread
        self._align_worker = worker
        thread.start()

    @Slot(str)
    def _on_align_progress(self, message):
        self.statusMessage.emit(message)

    @Slot(object, str)
    def _on_align_finished(self, result, error):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setVisible(False)
        self.run_button.setEnabled(True)
        if error:
            self.statusMessage.emit(f"栅格预处理失败：{error}")
            self._log(f"栅格对齐：失败（{error}）")
            return
        if result.status == "success":
            self._log(f"栅格对齐：成功（{len(result.processed or [])} 个数据集）")
            self._register_align_results(result)
            self._last_align_result = result
            if self.save_result_button is not None:
                self.save_result_button.setEnabled(True)
        else:
            self._log(f"栅格对齐：{result.message}")
        self.statusMessage.emit(result.message)

    def _register_align_results(self, result):
        """把对齐结果登记到数据管理（store.sources），供数据目录与后续分析使用。"""
        registered = []
        for item in result.processed or []:
            aligned = item.get("aligned_path", "")
            if not aligned or not Path(aligned).exists():
                continue
            source = self.store.add_source(aligned)
            if source and source.path == aligned:
                registered.append(Path(aligned).name)
        if registered:
            self._log(f"已登记 {len(registered)} 个结果到数据管理：{'、'.join(registered)}")

    def _save_align_result(self):
        """把对齐结果另存到用户指定目录（持久保留，不随关闭清理）。"""
        result = self._last_align_result
        if not result or not (result.processed or []):
            self.statusMessage.emit("没有可保存的对齐结果，请先运行栅格对齐")
            return
        target = QFileDialog.getExistingDirectory(self, "选择保存目录", "")
        if not target:
            return
        target = Path(target)
        saved = []
        try:
            for item in result.processed:
                src = Path(item.get("aligned_path", ""))
                if not src.exists():
                    continue
                import shutil
                shutil.copy2(src, target / src.name)
                saved.append(src.name)
        except OSError as exc:
            self.statusMessage.emit(f"保存失败：{exc}")
            return
        self._log(f"已保存 {len(saved)} 个结果到：{target}")
        self.statusMessage.emit(f"已保存 {len(saved)} 个对齐结果到：{target}")

    def _filter_tools(self, text):
        if not self.tool_list:
            return
        keyword = text.strip()
        for i in range(self.tool_list.count()):
            item = self.tool_list.item(i)
            tool = item.data(Qt.ItemDataRole.UserRole)
            if tool is None:
                item.setHidden(False)
                continue
            item.setHidden(keyword not in tool)

    def _log(self, message):
        self.log.append(message)

    def update_after_data_change(self):
        """数据导入/删除后刷新参考栅格下拉框。"""
        if hasattr(self, "ref_combo"):
            self._refresh_ref_combo()
