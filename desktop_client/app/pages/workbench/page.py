"""工作台页：模型参数设置 + 运行 + 结果地图/散点图 + 属性表。"""
import math
import shutil
import struct
from pathlib import Path

from ...qt_compat import (
    QAbstractItemView,
    QCheckBox,
    QColor,
    QComboBox,
    QItemSelection,
    QItemSelectionModel,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QObject,
    QPalette,
    QPushButton,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QThread,
    QToolTip,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
    Slot,
)
from ...widgets import (
    AttributeTableModel,
    ChartWindow,
    DroppableTableView,
    MapCanvas,
    ScatterCanvas,
    clear_layout,
    columns_from_rows,
    panel_box,
)
from ...widgets.vector_loader import VectorLoadWorker
from core.algorithms.python_runner import PythonRunner
from core.algorithms.r_runner import RRunner
from core.io.readers import read_attributes, read_unique_values
from core.models import (
    AnalysisParameters,
    AnalysisResult,
    RasterAnalysisParameters,
    attribute_pairs,
    pair_key,
    pair_label,
    parse_pair_key,
)
from core.raster_processing import RasterPreprocessor
from core.symbology import (
    auto_colors,
    categorical_colors,
    classify,
    classify_unique,
    pair_field_info,
)


class InfoIcon(QLabel):
    """小问号图标：鼠标进入立即显示提示，移出立即隐藏。"""

    def __init__(self, parent=None):
        super().__init__("?", parent)
        self.setFixedSize(16, 16)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setStyleSheet(
            "border: 1px solid #9fb3ad; border-radius: 8px; color: #6b7f7b; font-weight: 700; font-size: 10px;"
        )
        self._info = ""

    def set_info(self, text):
        self._info = text

    def enterEvent(self, event):
        if self._info:
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self._info, self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class NoWheelComboBox(QComboBox):
    """工作台下拉框不因鼠标滚轮经过而切换选项。"""

    def wheelEvent(self, event):
        event.ignore()


# 小地图与属性表共同的最大要素数。栅格转面数据常有十几万要素，全量渲染一次性阻塞
# 主线程约 2.4 秒（建 QPointF 缓存 ~1.5s + 光栅化 ~0.9s），可以接受；仍留上限兜底极端数据。
# 属性表按同一上限读取并逐行展示，保证表行与地图要素严格一一对应，联动高亮不会错位。
_MAP_MAX_RECORDS = 200000

# 散点图出图时的最大点数：点太多时按等间隔抽样。散点样式本来就是「看分布」，
# 抽样不影响判读，却能把绘制与 hit-test 的代价压到常数级。
_SCATTER_MAX_POINTS = 20000

# 分层设色图例最多列出的类别数：面板不滚动，唯一值可能有几十类。
_LEGEND_MAX_ITEMS = 30

# 统一的控件高度与间距标尺：同一界面里混用 30/32 高、5/6/7/8/10 间距会显得零碎
_CONTROL_HEIGHT = 32
_GAP_TIGHT = 4    # 标签与紧邻控件
_GAP_ITEM = 6     # 组内控件之间
_GAP_GROUP = 10   # 面板内分组之间
_GAP_PANEL = 12   # 面板之间

# 带宽探索里按配对返回的逐要素序列名（与 gwr_bandwidth.R 的 series 对齐）
_BW_SERIES = (
    "local_r2", "coefficient", "local_corr", "lme", "lmae", "lmre", "lrmse",
    "residual", "stud_residual",
)

# 分层设色字段名 → 带宽探索逐带宽结果字段（与 gwr_attribute.R 写出的结果 SHP 字段对齐）
_BANDWIDTH_FIELD_MAP = {
    "Local_R2": "local_r2",
    "Coeff": "coefficient",
    "Corr": "local_corr",
    "LME": "lme",
    "LMAE": "lmae",
    "LMRE": "lmre",
    "LRMSE": "lrmse",
}

# 带宽区间统一用百分比表示：绝对范围写死会在十几万要素的数据上失效——属性模式固定
# 1~100 个近邻，而这类数据合适的带宽可能是几千到几万。滑块与步长都走百分比，
# 实际带宽按各模式的数据基准换算（见 _bandwidth_baseline），并实时显示换算结果。
_BANDWIDTH_PERCENT = {"lo": 5, "hi": 100, "default": 50}
_BANDWIDTH_STEP_RANGE = (1, 50)   # 百分比步长
_BANDWIDTH_STEP_DEFAULT = 5

# 栅格模式的窗口上限（像素）：短路取栅格短边会让窗口跑到几万像素，
# 在几万宽的栅格上做这种尺寸的移动窗口既无意义也慢到跑不完。
_RASTER_WINDOW_MAX = 999

# 各模式的单位与说明；基准值随数据而定，不写死
_BANDWIDTH_MODES = {
    "attribute": {"unit": "近邻", "hint": "复用数据 1 / 数据 2 / 核函数"},
    "raster": {"unit": "窗口", "hint": "复用栅格选择 / 重采样 / 零值阈值"},
    "geometry": {"unit": "米", "hint": "复用类别映射 / 推荐 IoU 阈值"},
}

# 属性模式 GWR 的重投影目标（与 gwr_attribute.R 的 PROJ_CRS 保持一致，用于估算研究区范围）
_ATTRIBUTE_PROJ_CRS = (
    "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 +x_0=0 +y_0=0 "
    "+datum=WGS84 +units=m +no_defs"
)


class _BandwidthWorker(QObject):
    """后台线程运行带宽区间探索（属性 R / 栅格 R / 几何 Python），避免子进程阻塞 UI。"""

    finished = Signal(object, str)  # (dict|None, error)

    def __init__(self, runner, config, output_path):
        super().__init__()
        self._runner = runner
        self._config = config
        self._output_path = output_path

    @Slot()
    def run(self):
        try:
            result = self._runner.run(self._config, self._output_path)
            self.finished.emit(result, "")
        except Exception as exc:  # noqa: BLE001 - 失败以错误文本回传
            self.finished.emit(None, str(exc))


class WorkbenchPage(QWidget):
    """设置 GWR 模型参数并运行；分析视图与属性表视图两个页签可随时切换。"""

    runRequested = Signal(dict)
    resultDirectoryRequested = Signal()
    statusMessage = Signal(str)
    # 项目被拖进地图 / 属性表：请求切到那个项目（由主窗口处理，项目列表归它管）
    runDropped = Signal(int)

    def __init__(self, store, parent=None, rscript_path=""):
        super().__init__(parent)
        self.store = store
        self._rscript_path = rscript_path
        self._bandwidth_script = (
            Path(__file__).resolve().parents[3]
            / "core" / "algorithms" / "scripts" / "attribute" / "gwr_bandwidth.R"
        )
        self._raster_bandwidth_script = (
            Path(__file__).resolve().parents[3]
            / "core" / "algorithms" / "scripts" / "raster" / "raster_bandwidth.R"
        )
        self._geometry_bandwidth_script = (
            Path(__file__).resolve().parents[3]
            / "core" / "algorithms" / "scripts" / "geometry" / "geometry_bandwidth.py"
        )
        self._bandwidth_snapshots = {}   # mode -> 快照 dict（各模式独立，切换页签不丢结果）
        self._bandwidth_color_cache = {}  # (mode, field) -> 每档带宽的配色
        self._bandwidth_legend_cache = {}  # (mode, field) -> 每档带宽的 (breaks, colors)
        self._bandwidth_generating = False
        self._bandwidth_generating_mode = ""
        self._bw_slider_values = {}  # mode -> 最近一次滑块百分比
        self._bw_step_values = {}    # mode -> 最近一次百分比步长
        self._bw_baseline_cache = {}  # 数据基准缓存（栅格尺寸等）
        self._bw_count_cache = {}     # (路径, 参与字段元组) -> 有效样本数
        self._numeric_field_cache = {}  # 数据源路径 -> 数值字段名
        self._bw_extent_cache = {}    # (路径, 目标投影) -> 范围对角线（米）
        self._bandwidth_thread = None
        self._bandwidth_worker = None
        self.latest_result = AnalysisResult()
        self.map_canvas = None
        self.attr_hint = None
        self.result_table = None
        self.save_shp_button = None
        self._result_output_shp = ""
        self._syncing_selection = False   # 防止地图 ↔ 属性表互相触发造成回环
        self._table_linked = False        # 属性表行序是否与地图要素一一对应
        self._map_path = None
        # 属性分析用的源矢量（结果 SHP 只是它加了结果列后的副本，两者行序一致）
        self._source_shp_path = ""
        self._map_geometry = None
        self._map_fields = []
        self._map_values = {}
        self._vector_load_seq = 0      # 矢量加载请求序号，用于丢弃过期结果
        self._pending_reset_xy = True
        self._pending_fill_table = True
        self._pending_keep_bandwidth = False
        self._pending_symbology_field = ""   # 图层加载完后再还原的设色字段
        self._vector_loads = {}        # seq -> (线程, worker)，持有引用防止在飞任务被 GC
        self.field_info_label = None
        self._chart_window = None
        self.raster_list = None
        self.raster_options = None
        self._build()

    def set_rscript_path(self, path):
        self._rscript_path = path

    def current_vector_path(self):
        """地图当前加载的矢量数据路径；非矢量或不存在时返回空串，供属性 GWR 取用。"""
        path = self._map_path or ""
        if Path(path).suffix.lower() in {".shp", ".gpkg", ".geojson"} and Path(path).exists():
            return path
        return ""

    def source_vector_path(self):
        """属性 GWR 的源数据：优先「数据管理」导入的原始矢量（而非运行后自动加载的结果 SHP），
        确保带宽区间探索与主运行使用同一份数据。"""
        for source in self.store.sources:
            if Path(source.path).suffix.lower() in {".shp", ".gpkg", ".geojson"}:
                return source.path
        return self._map_path or ""

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._analysis_view(), "分析")
        self.tabs.addTab(self._attribute_view(), "属性表")
        root.addWidget(self.tabs, 1)

    def _analysis_view(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(_GAP_PANEL)

        top = QHBoxLayout()
        top.setSpacing(_GAP_PANEL)

        # 右：模型参数（滚动条）+ 分层设色（先构建，带宽面板依赖 symbology_field_combo）
        right = QVBoxLayout()
        right.setSpacing(_GAP_PANEL)
        right.addWidget(self._parameter_panel(), 1)
        right.addWidget(self._symbology_panel())
        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setFixedWidth(360)

        # 左：地图 + 带宽区间（带宽区间在地图下方，不占整行宽度）
        left = QVBoxLayout()
        left.setSpacing(_GAP_PANEL)
        left.addWidget(self._map_panel(), 1)
        self.bandwidth_panel = self._bandwidth_panel()
        left.addWidget(self.bandwidth_panel)

        top.addLayout(left, 1)
        top.addWidget(right_widget)

        layout.addLayout(top, 1)
        return container

    def _attribute_view(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(_GAP_GROUP)

        header = QHBoxLayout()
        self.attr_hint = QLabel("拖动左侧数据到此处，查看对应属性表")
        self.attr_hint.setObjectName("Muted")
        header.addWidget(self.attr_hint, 1)
        self.save_shp_button = QPushButton("另存为 SHP…")
        self.save_shp_button.setObjectName("OutlineButton")
        self.save_shp_button.clicked.connect(self._save_result_shp)
        header.addWidget(self.save_shp_button)
        layout.addLayout(header)

        # 用虚拟表（QTableView + 模型）而非 QTableWidget：十几万行也能秒开且几乎不占内存
        self.attr_model = AttributeTableModel(self)
        self.result_table = DroppableTableView()
        self.result_table.setModel(self.attr_model)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setAlternatingRowColors(True)
        # 行序必须与地图要素一一对应才能联动高亮，故不排序；按行多选，选中几行地图就亮几块。
        self.result_table.setSortingEnabled(False)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.result_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.result_table.selectionModel().selectionChanged.connect(self._on_table_selection_changed)
        self.result_table.sourceDropped.connect(self._load_source_table)
        self.result_table.runDropped.connect(self.runDropped.emit)
        layout.addWidget(self.result_table, 1)
        return container

    def _map_panel(self):
        panel, body = panel_box("RESULT MAP", "小地图", "尚未设色")
        # 标题右侧的注释跟随当前设色字段，避免写死一个字段名后与实际不符
        self.map_note = panel.findChild(QLabel, "PanelNote")
        self.map_canvas = MapCanvas()
        self.map_canvas.sourceDropped.connect(self.load_shp)
        self.map_canvas.runDropped.connect(self.runDropped.emit)
        self.map_canvas.featureClicked.connect(self._on_map_feature_clicked)
        self.map_canvas.rasterLoaded.connect(self._on_map_raster_loaded)
        body.addWidget(self.map_canvas, 1)
        hint_row = QHBoxLayout()
        hint = QLabel("滚轮缩放 · 拖拽平移 · 双击复位 · 拖入 SHP/栅格显示")
        hint.setObjectName("Muted")
        hint_row.addWidget(hint, 1)
        chart_button = QPushButton("打开图表（散点 / 直方图）")
        chart_button.setObjectName("OutlineButton")
        chart_button.clicked.connect(self._open_chart_window)
        hint_row.addWidget(chart_button)
        result_directory_button = QPushButton("结果目录")
        result_directory_button.setObjectName("OutlineButton")
        result_directory_button.clicked.connect(self.resultDirectoryRequested.emit)
        hint_row.addWidget(result_directory_button)
        body.addLayout(hint_row)
        return panel

    def _bandwidth_panel(self):
        # compact=True：这块在地图下方，压紧一点给地图让出高度
        panel, body = panel_box("BANDWIDTH", "带宽区间", "拖动滑块 · 自动生成", compact=True)

        # 模式说明 + 状态合并成一行（随「属性 / 栅格 / 几何」页签切换）
        info_row = QHBoxLayout()
        info_row.setSpacing(10)
        self.bw_mode_hint = QLabel("")
        self.bw_mode_hint.setObjectName("Muted")
        info_row.addWidget(self.bw_mode_hint, 1)
        self.bw_status = QLabel("")
        self.bw_status.setObjectName("Muted")
        self.bw_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        info_row.addWidget(self.bw_status)
        body.addLayout(info_row)

        # 滑块 + 当前值 + 生成按钮
        row = QHBoxLayout()
        self.bw_lo_label = QLabel(f"{_BANDWIDTH_PERCENT['lo']}%")
        self.bw_lo_label.setObjectName("Muted")
        row.addWidget(self.bw_lo_label)
        self.bandwidth_slider = QSlider(Qt.Orientation.Horizontal)
        self.bandwidth_slider.setRange(_BANDWIDTH_PERCENT["lo"], _BANDWIDTH_PERCENT["hi"])
        self.bandwidth_slider.setSingleStep(_BANDWIDTH_STEP_DEFAULT)
        self.bandwidth_slider.setPageStep(_BANDWIDTH_STEP_DEFAULT * 2)
        self.bandwidth_slider.setValue(_BANDWIDTH_PERCENT["default"])
        row.addWidget(self.bandwidth_slider, 1)
        self.bw_hi_label = QLabel(f"{_BANDWIDTH_PERCENT['hi']}%")
        self.bw_hi_label.setObjectName("Muted")
        row.addWidget(self.bw_hi_label)
        self.bandwidth_value = QLabel("50%")
        self.bandwidth_value.setObjectName("Muted")
        self.bandwidth_value.setMinimumWidth(38)
        self.bandwidth_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.bandwidth_value)
        # 百分比换算成实际带宽后紧挨着显示，避免只看到比例不知道具体值
        self.bw_converted = QLabel("—")
        self.bw_converted.setStyleSheet("color: #2d8c7c; font-weight: 700;")
        self.bw_converted.setMinimumWidth(150)
        row.addWidget(self.bw_converted)
        self.generate_button = QPushButton("生成快照")
        self.generate_button.setObjectName("PrimaryButton")
        row.addWidget(self.generate_button)
        body.addLayout(row)

        # 步长（真正作用于带宽序列生成与滑块步进）
        step_row = QHBoxLayout()
        step_row.setSpacing(_GAP_ITEM)
        step_label = QLabel("步长")
        step_label.setObjectName("FieldLabel")
        step_row.addWidget(step_label)
        self.bandwidth_step_spin = QSpinBox()
        self.bandwidth_step_spin.setRange(*_BANDWIDTH_STEP_RANGE)
        self.bandwidth_step_spin.setValue(_BANDWIDTH_STEP_DEFAULT)
        self.bandwidth_step_spin.setFixedHeight(_CONTROL_HEIGHT)
        self.bandwidth_step_spin.setFixedWidth(76)
        step_row.addWidget(self.bandwidth_step_spin)
        self.bw_step_unit = QLabel("%")
        self.bw_step_unit.setObjectName("Muted")
        step_row.addWidget(self.bw_step_unit)
        self.bw_sequence_hint = QLabel("")
        self.bw_sequence_hint.setObjectName("Muted")
        step_row.addWidget(self.bw_sequence_hint, 1)
        body.addLayout(step_row)

        # 当前带宽关键指标 + 最佳带宽
        self.bw_metrics_label = QLabel("拖动滑块自动生成并查看地图变化")
        self.bw_metrics_label.setObjectName("Muted")
        self.bw_metrics_label.setTextFormat(Qt.TextFormat.RichText)
        self.bw_metrics_label.setWordWrap(True)
        body.addWidget(self.bw_metrics_label)

        # 横向分级图例
        self.bw_legend_layout = QHBoxLayout()
        self.bw_legend_layout.setSpacing(10)
        body.addLayout(self.bw_legend_layout)

        self.bandwidth_slider.valueChanged.connect(self._on_bandwidth_slider_changed)
        self.bandwidth_step_spin.valueChanged.connect(self._on_bandwidth_step_changed)
        self.symbology_field_combo.currentTextChanged.connect(self._on_bandwidth_field_changed)
        self.symbology_method_combo.currentTextChanged.connect(self._on_bandwidth_field_changed)
        self.symbology_classes_spin.valueChanged.connect(self._on_bandwidth_field_changed)
        self.generate_button.clicked.connect(self._run_bandwidth_snapshots)
        # 「带宽含义」在参数页签里，切换后 100% 的基准不同（样本数 / 研究区范围），需重算
        self.bandwidth_mode_combo.currentTextChanged.connect(self._on_bandwidth_meaning_changed)
        # 面板构建晚于参数页签，这里补一次模式配置（参数页签构建时面板还不存在）
        self._apply_bandwidth_mode(self._current_mode())
        return panel

    def _symbology_panel(self):
        panel, body = panel_box("SYMBOLOGY", "分层设色", "分级渲染")
        body.setSpacing(_GAP_ITEM)

        # 配对切换：多字段分析时地图/属性表/带宽着色看的是同一份结果，
        # 由这一个下拉决定看哪一组配对。只有一个配对时没有必要显示。
        pair_row = QHBoxLayout()
        pair_row.setSpacing(_GAP_ITEM)
        pair_label_widget = QLabel("配对")
        pair_label_widget.setObjectName("FieldLabel")
        pair_row.addWidget(pair_label_widget)
        self.pair_combo = NoWheelComboBox()
        self.pair_combo.setFixedHeight(_CONTROL_HEIGHT)
        self._style_combo(self.pair_combo)
        pair_row.addWidget(self.pair_combo, 1)
        self.pair_row_widget = QWidget()
        self.pair_row_widget.setLayout(pair_row)
        pair_row.setContentsMargins(0, 0, 0, 0)
        self.pair_row_widget.hide()
        body.addWidget(self.pair_row_widget)
        self.pair_combo.currentIndexChanged.connect(self._on_pair_changed)

        # 设色字段：标签 + 问号 + 下拉框（一行）
        field_row = QHBoxLayout()
        field_row.setSpacing(_GAP_ITEM)
        label = QLabel("设色字段")
        label.setObjectName("FieldLabel")
        field_row.addWidget(label)
        self.field_info_label = InfoIcon()
        self.field_info_label.set_info("鼠标悬停查看设色字段含义与分级配色说明")
        field_row.addWidget(self.field_info_label)
        self.symbology_field_combo = QComboBox()
        self.symbology_field_combo.setFixedHeight(_CONTROL_HEIGHT)
        self._style_combo(self.symbology_field_combo)
        field_row.addWidget(self.symbology_field_combo, 1)
        body.addLayout(field_row)

        # 分类方法 + 分级数（一行）
        method_row = QHBoxLayout()
        method_row.setSpacing(_GAP_ITEM)
        method_label = QLabel("方法")
        method_label.setObjectName("FieldLabel")
        method_row.addWidget(method_label)
        self.symbology_method_combo = NoWheelComboBox()
        self.symbology_method_combo.addItems(["自然间断点", "等间隔", "分位数", "唯一值", "手动"])
        self.symbology_method_combo.setFixedHeight(_CONTROL_HEIGHT)
        self.symbology_method_combo.setFixedWidth(128)
        self._style_combo(self.symbology_method_combo)
        method_row.addWidget(self.symbology_method_combo)
        method_row.addStretch(1)
        class_label = QLabel("分级数")
        class_label.setObjectName("FieldLabel")
        method_row.addWidget(class_label)
        self.symbology_classes_spin = QSpinBox()
        self.symbology_classes_spin.setRange(2, 10)
        self.symbology_classes_spin.setValue(5)
        self.symbology_classes_spin.setFixedHeight(_CONTROL_HEIGHT)
        self.symbology_classes_spin.setFixedWidth(72)
        method_row.addWidget(self.symbology_classes_spin)
        body.addLayout(method_row)

        self.manual_breaks_input = QLineEdit()
        self.manual_breaks_input.setPlaceholderText("逗号分隔断点，如 0, 10, 50, 100")
        self.manual_breaks_input.hide()
        body.addWidget(self.manual_breaks_input)

        self.legend_layout = QGridLayout()
        self.legend_layout.setHorizontalSpacing(12)
        self.legend_layout.setVerticalSpacing(3)
        self.legend_layout.setColumnStretch(0, 1)
        self.legend_layout.setColumnStretch(1, 1)
        body.addLayout(self.legend_layout)

        self.symbology_field_combo.currentTextChanged.connect(self._apply_symbology)
        self.symbology_field_combo.currentTextChanged.connect(self._update_field_tooltip)
        self.symbology_method_combo.currentTextChanged.connect(self._on_method_changed)
        self.symbology_classes_spin.valueChanged.connect(self._apply_symbology)
        self.manual_breaks_input.editingFinished.connect(self._apply_symbology)
        # 参数面板先于本面板构建，构建期间 pair_combo 还不存在，这里补一次配对列表
        self._refresh_pair_options()
        return panel

    def _parameter_panel(self):
        panel, body = panel_box("GWR MODEL", "模型参数")
        body.setSpacing(_GAP_GROUP)

        self.param_tabs = QTabWidget()
        self.param_tabs.setMinimumHeight(210)
        self.param_tabs.addTab(self._attribute_options(), "属性数据")
        self.param_tabs.addTab(self._raster_options(), "栅格数据")
        self.param_tabs.addTab(self._geometry_options(), "几何数据")
        body.addWidget(self.param_tabs)

        self.geometry_a_combo.currentIndexChanged.connect(self._refresh_geometry_fields)
        self.geometry_b_combo.currentIndexChanged.connect(self._refresh_geometry_fields)
        self.geometry_a_field_combo.currentTextChanged.connect(self._refresh_geometry_mapping)
        self.geometry_b_field_combo.currentTextChanged.connect(self._refresh_geometry_mapping)
        self.param_tabs.currentChanged.connect(self._on_mode_changed)
        self._refresh_raster_options()
        self._on_mode_changed(self.param_tabs.currentIndex())

        self.save_result_shp = QCheckBox("运行后生成结果 SHP")
        self.save_result_shp.setChecked(True)
        body.addWidget(self.save_result_shp)
        self._refresh_variable_options()

        # 运行按钮固定在滚动区外，始终可见
        run_button = QPushButton("▶ 运行")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(self.run)
        self.run_button = run_button
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 4, 18, 14)
        footer_layout.addWidget(run_button)
        panel.layout().addWidget(footer)
        return panel

    def _attribute_options(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_GAP_GROUP)

        # 字段多选：勾选参与分析的字段，列表顺序决定配对里的 Y / X，
        # 算法会对全部勾选字段两两配对（C(N,2) 组）一次性算完。
        self._add_field_label(layout, "分析字段（至少勾选两个）")
        field_hint = QLabel("两两配对各算一组：靠前的作因变量 Y，靠后的作自变量 X")
        field_hint.setObjectName("Muted")
        field_hint.setWordWrap(True)
        layout.addWidget(field_hint)
        self.var_list = QListWidget()
        self.var_list.setMinimumHeight(120)
        self.var_list.setMaximumHeight(170)
        self.var_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.var_list)

        order_row = QHBoxLayout()
        order_row.setSpacing(_GAP_ITEM)
        self.var_up_button = QPushButton("↑ 上移")
        self.var_down_button = QPushButton("↓ 下移")
        for button in (self.var_up_button, self.var_down_button):
            button.setObjectName("OutlineButton")
            button.setFixedHeight(_CONTROL_HEIGHT)
            order_row.addWidget(button)
        order_row.addStretch()
        layout.addLayout(order_row)

        self.pair_preview = QLabel("")
        self.pair_preview.setObjectName("Muted")
        self.pair_preview.setWordWrap(True)
        layout.addWidget(self.pair_preview)

        self.kernel_combo = self._add_select(layout, "核函数", ["双平方核", "高斯核", "指数核"])

        self._add_field_label(layout, "带宽")
        bw_row = QHBoxLayout()
        self.bandwidth_input = QLineEdit("25")
        self.bandwidth_input.setFixedWidth(80)
        self.bandwidth_input.setFixedHeight(_CONTROL_HEIGHT)
        bw_row.addWidget(self.bandwidth_input)
        self.auto_bandwidth = QCheckBox("自动（AIC）")
        bw_row.addWidget(self.auto_bandwidth)
        bw_row.addStretch()
        layout.addLayout(bw_row)

        self.bandwidth_mode_combo = self._add_select(layout, "带宽含义", ["最近邻个数", "距离（米）"])
        scroll.setWidget(widget)
        self.attribute_options = scroll

        self.var_list.itemChanged.connect(self._on_variables_changed)
        self.var_up_button.clicked.connect(lambda: self._move_variable(-1))
        self.var_down_button.clicked.connect(lambda: self._move_variable(1))
        return scroll

    def _raster_options(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_GAP_GROUP)
        self._add_field_label(layout, "分析栅格（至少选择两个）")
        self.raster_list = QListWidget()
        self.raster_list.setMinimumHeight(130)
        self.raster_list.setMaximumHeight(220)
        layout.addWidget(self.raster_list)
        self._add_field_label(layout, "局部窗口大小")
        self.raster_window_spin = QSpinBox()
        self.raster_window_spin.setRange(3, 99)
        self.raster_window_spin.setSingleStep(2)
        self.raster_window_spin.setValue(5)
        layout.addWidget(self.raster_window_spin)
        self._add_field_label(layout, "重采样方法")
        self.raster_resampling_combo = NoWheelComboBox()
        self.raster_resampling_combo.addItems(["bilinear", "near", "cubic"])
        self.raster_resampling_combo.setFixedHeight(_CONTROL_HEIGHT)
        self._style_combo(self.raster_resampling_combo)
        layout.addWidget(self.raster_resampling_combo)
        self._add_field_label(layout, "相对误差零值阈值")
        self.raster_epsilon_spin = QDoubleSpinBox()
        self.raster_epsilon_spin.setDecimals(12)
        self.raster_epsilon_spin.setRange(0.0, 1.0)
        self.raster_epsilon_spin.setSingleStep(1e-12)
        self.raster_epsilon_spin.setValue(1e-12)
        layout.addWidget(self.raster_epsilon_spin)
        self.raster_local_checkbox = QCheckBox("输出局部 GeoTIFF")
        self.raster_local_checkbox.setChecked(True)
        layout.addWidget(self.raster_local_checkbox)
        self.raster_scatter_checkbox = QCheckBox("输出像元散点图")
        self.raster_scatter_checkbox.setChecked(True)
        layout.addWidget(self.raster_scatter_checkbox)
        scroll.setWidget(widget)
        self.raster_options = scroll
        return scroll

    def _geometry_options(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_GAP_GROUP)
        self.geometry_a_combo = self._add_select(layout, "几何数据 A")
        self.geometry_b_combo = self._add_select(layout, "几何数据 B")
        self.geometry_a_field_combo = self._add_select(layout, "A 类别字段")
        self.geometry_b_field_combo = self._add_select(layout, "B 类别字段")
        mapping_hint = QLabel("类别映射（双击单元格可修改；取消勾选可排除类别）")
        mapping_hint.setObjectName("Muted")
        mapping_hint.setWordWrap(True)
        layout.addWidget(mapping_hint)
        self.geometry_mapping_table = QTableWidget(0, 4)
        self.geometry_mapping_table.setHorizontalHeaderLabels(["使用", "A 值", "B 值", "显示名称"])
        self.geometry_mapping_table.verticalHeader().setVisible(False)
        self.geometry_mapping_table.setMinimumHeight(150)
        self.geometry_mapping_table.setColumnWidth(0, 48)
        self.geometry_mapping_table.setColumnWidth(1, 70)
        self.geometry_mapping_table.setColumnWidth(2, 70)
        self.geometry_mapping_table.setColumnWidth(3, 105)
        layout.addWidget(self.geometry_mapping_table)
        self.geometry_crs_input = QLineEdit("EPSG:32650")
        self._add_field_label(layout, "计算投影 CRS")
        layout.addWidget(self.geometry_crs_input)
        self.geometry_min_area_spin = QDoubleSpinBox()
        self.geometry_min_area_spin.setRange(0, 1_000_000_000)
        self.geometry_min_area_spin.setDecimals(2)
        self.geometry_min_area_spin.setSuffix(" m²")
        self._add_field_label(layout, "最小面积阈值")
        layout.addWidget(self.geometry_min_area_spin)
        self.geometry_thresholds_input = QLineEdit("0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9")
        self._add_field_label(layout, "外接矩形 IoU 阈值")
        layout.addWidget(self.geometry_thresholds_input)
        self.geometry_bandwidth_spin = QDoubleSpinBox()
        self.geometry_bandwidth_spin.setRange(1, 1_000_000)
        self.geometry_bandwidth_spin.setValue(5000)
        self.geometry_bandwidth_spin.setSuffix(" m")
        self._add_field_label(layout, "地理加权带宽")
        layout.addWidget(self.geometry_bandwidth_spin)
        self._add_field_label(layout, "输出目录（留空则使用项目运行目录）")
        output_row = QHBoxLayout()
        self.geometry_output_input = QLineEdit()
        output_row.addWidget(self.geometry_output_input, 1)
        output_button = QPushButton("浏览…")
        output_button.clicked.connect(self._browse_geometry_output)
        output_row.addWidget(output_button)
        layout.addLayout(output_row)
        self.geometry_report_checkbox = QCheckBox("生成综合报告")
        self.geometry_report_checkbox.setChecked(True)
        self.geometry_figures_checkbox = QCheckBox("生成 4 张 3×3 综合图")
        self.geometry_figures_checkbox.setChecked(True)
        layout.addWidget(self.geometry_report_checkbox)
        layout.addWidget(self.geometry_figures_checkbox)
        self.geometry_validation_label = QLabel("等待配置校验")
        self.geometry_validation_label.setWordWrap(True)
        self.geometry_validation_label.setObjectName("Muted")
        layout.addWidget(self.geometry_validation_label)
        scroll.setWidget(widget)
        self.geometry_options = scroll
        return scroll

    def _add_field_label(self, body, text):
        """表单字段名统一走这里，避免有的用 Muted、有的用默认色。"""
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        body.addWidget(label)
        return label

    def _add_select(self, body, label_text, items=None):
        self._add_field_label(body, label_text)
        combo = NoWheelComboBox()
        combo.setFixedHeight(_CONTROL_HEIGHT)
        if items:
            combo.addItems(items)
        self._style_combo(combo)
        body.addWidget(combo)
        return combo

    @staticmethod
    def _style_combo(combo):
        palette = combo.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#26363c"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#26363c"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#e3f3ef"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1f695e"))
        combo.setPalette(palette)
        view = combo.view()
        view.setPalette(palette)
        view.setStyleSheet(
            "QAbstractItemView { background: #ffffff; color: #26363c; "
            "selection-background-color: #e3f3ef; selection-color: #1f695e; }"
        )

    @staticmethod
    def _set_combo(combo, text):
        if text and combo.findText(text) >= 0:
            combo.setCurrentText(text)

    def get_symbology_state(self):
        return {
            "symbology_field": self.symbology_field_combo.currentText(),
            "symbology_method": self.symbology_method_combo.currentText(),
            "symbology_classes": self.symbology_classes_spin.value(),
        }

    def render_attribute_figures(self, shp_path, variables, pairs, out_dir, tag=""):
        """渲染属性分析的图片产物：逐配对散点图 + 多字段散点图矩阵。

        属性表只读一次：DBF 解析耗时与行数成正比，每个配对各读一遍会让出图时间
        变成 C(N,2) 倍，矩阵再单独读一遍又是两倍。画布上的点按上限等间隔抽样——
        几十万个 QPointF 的绘制与命中检测都会肉眼可见地卡。

        返回 {"scatter": {配对键: 路径}, "matrix": 矩阵图路径}；矩阵只在选了
        三个以上字段时生成（两个字段其实就是那张普通散点图）。
        """
        data = read_attributes(shp_path, limit=0)
        fields = data["fields"]
        rows = data["rows"]
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        rendered = {}
        for y_field, x_field in pairs:
            if x_field not in fields or y_field not in fields:
                continue
            ix, iy = fields.index(x_field), fields.index(y_field)
            xs, ys = [], []
            for row in rows:
                if len(row) <= max(ix, iy):
                    continue
                x, y = row[ix], row[iy]
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    xs.append(x)
                    ys.append(y)
            if len(xs) < 2:
                continue
            step = max(1, len(xs) // _SCATTER_MAX_POINTS)
            canvas = ScatterCanvas()
            canvas.setStyleSheet("font-size: 18px;")
            canvas.resize(1400, 1400)
            canvas.set_data(xs[::step], ys[::step], x_field, y_field)
            key = pair_key(y_field, x_field)
            name = f"scatter_{tag}_{key}.png" if tag else f"scatter_{key}.png"
            path = out_dir / name
            if canvas.grab().save(str(path), "PNG"):
                rendered[key] = str(path)

        matrix = self._render_attribute_matrix(fields, rows, variables, out_dir, tag)
        return {"scatter": rendered, "matrix": matrix}

    def _render_attribute_matrix(self, fields, rows, variables, out_dir, tag=""):
        """多字段散点图矩阵：N×N 一次看完所有字段两两之间的关系。

        与逐配对散点图互补——散点图看的是「某一对差多少」，矩阵看的是「这些数据
        彼此之间的关系结构」。用的是栅格模式同一套渲染（core/raster_plotting）。
        """
        names = [name for name in variables if name in fields]
        if len(names) < 3:
            return ""
        columns = {}
        for name in names:
            index = fields.index(name)
            columns[name] = [row[index] if index < len(row) else None for row in rows]
        name_part = f"matrix_{tag}.png" if tag else "matrix.png"
        path = Path(out_dir) / name_part
        try:
            from core.raster_plotting import plot_column_matrix
            ok = plot_column_matrix(
                columns, path, names,
                "人口数据散点图矩阵 · 对角线=分布 · 下三角=散点 · 上三角=成对指标",
            )
        except Exception:  # noqa: BLE001 - 出图失败不影响分析结果
            ok = False
        return str(path) if ok else ""

    def restore_run(self, run):
        p = run.parameters
        self.latest_result = run.result
        # 1. 回填分析字段：多字段按保存顺序勾选，只有旧版单配对参数时退回 x/y 两个
        variables = p.get("variables") or [
            v for v in (p.get("dependent_variable"), p.get("independent_variable")) if v
        ]
        self._rebuild_variable_list(self._available_fields(variables), variables)
        self._refresh_pair_preview()
        # 2. 配对下拉还原（必须在字段列表重建之后，否则选项还不存在）
        if run.pair_key:
            index = self.pair_combo.findData(run.pair_key)
            if index >= 0:
                self.pair_combo.blockSignals(True)
                self.pair_combo.setCurrentIndex(index)
                self.pair_combo.blockSignals(False)
        # 3. 加载该配对的结果 SHP（含结果列，方便分层设色），否则加载源 SHP
        result_shp = self._result_shp_for(run.pair_key) or (getattr(run.result, "output_shp", "") or "")
        load_path = result_shp if (result_shp and Path(result_shp).exists()) else run.shp_path
        if load_path:
            # 下面第 5 步会用 _show_results 填入带结果列的表，这里不要抢先覆盖。
            # reset_xy=False：字段选择在上一步已按保存的参数还原好，加载结果 SHP
            # 不该再按它的字段重建一遍覆盖掉。
            self.load_shp(load_path, reset_xy=False, fill_table=False)
        # 4. 其余参数面板回填
        self._set_combo(self.kernel_combo, p.get("kernel", "双平方核"))
        self.bandwidth_input.setText(str(p.get("bandwidth", "25")))
        self.auto_bandwidth.setChecked(bool(p.get("auto_bandwidth", False)))
        self._set_combo(self.bandwidth_mode_combo, p.get("bandwidth_mode", "最近邻个数"))
        backend = p.get("backend", "R 属性 GWR")
        if backend == "栅格 R / terra":
            self.param_tabs.setCurrentIndex(1)
        elif backend == "外接矩形法几何交叉验证":
            self.param_tabs.setCurrentIndex(2)
        else:
            self.param_tabs.setCurrentIndex(0)
        self.save_result_shp.setChecked(bool(p.get("write_shp", True)))
        # 3. 设色还原。设色字段的候选列表要等图层解析完才有，而上面第 3 步的
        #    load_shp 是后台线程——图层还没加载完时下拉框里根本没有这个字段，
        #    直接 setCurrentText 会静默失败并回落成默认的 Local_R2。
        #    所以这里先看能不能立刻设上，设不上就挂起，等加载完再补。
        if run.symbology_field:
            if self.symbology_field_combo.findText(run.symbology_field) >= 0:
                self.symbology_field_combo.setCurrentText(run.symbology_field)
            else:
                self._pending_symbology_field = run.symbology_field
        self._set_combo(self.symbology_method_combo, run.symbology_method)
        self.symbology_classes_spin.setValue(run.symbology_classes)
        self._apply_symbology()
        # 5. 结果回填属性表
        self._result_output_shp = result_shp or (getattr(run.result, "output_shp", "") or "")
        self._show_results(run.shp_path, run.result.local_columns, result_shp=result_shp)
        self.tabs.setCurrentIndex(0)

    def _available_fields(self, extra=()):
        """分析字段候选：已导入数据源的字段并集，外加 extra（历史运行里可能用到、
        但当前数据源已不再列出的字段，回填时不能丢）。"""
        fields = []
        for source in self.store.sources:
            for field in source.fields:
                if field not in fields:
                    fields.append(field)
        for field in extra:
            if field and field not in fields:
                fields.append(field)
        return fields

    def _variable_order(self):
        """字段列表里的全部字段，按列表顺序（含未勾选的）。"""
        return [self.var_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.var_list.count())]

    def _selected_variables(self):
        """已勾选参与分析的字段，按列表顺序——顺序即配对里的因变量→自变量次序。"""
        return [self.var_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.var_list.count())
                if self.var_list.item(i).checkState() == Qt.CheckState.Checked]

    def _rebuild_variable_list(self, fields, selected):
        """按 fields 重建字段列表；selected 中的字段勾选并排到最前（保持其相对次序）。

        勾选字段前置，是为了让「谁作因变量 Y」在界面上直接可见：列表第一行就是
        所有配对共用的那个 Y。
        """
        selected = [value for value in selected if value in fields]
        order = selected + [value for value in fields if value not in selected]
        self.var_list.blockSignals(True)
        try:
            self.var_list.clear()
            for name in order:
                item = QListWidgetItem(str(name))
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if name in selected else Qt.CheckState.Unchecked)
                self.var_list.addItem(item)
        finally:
            self.var_list.blockSignals(False)

    def _numeric_fields_of_source(self, path):
        """数据源里的数值字段名：读前若干行按取值类型判断，按路径缓存。

        只读 50 行，代价与文件大小无关；没有这一步，首次进入工作台只能按字段
        顺序猜，很容易把「name / gb」这类文本字段默认勾上、直接运行就失败。
        """
        if path in self._numeric_field_cache:
            return self._numeric_field_cache[path]
        numeric = []
        try:
            data = read_attributes(path, limit=50)
            rows = data["rows"]
            for index, field in enumerate(data["fields"]):
                values = [row[index] for row in rows
                          if index < len(row) and row[index] is not None]
                if values and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                  for v in values):
                    numeric.append(field)
        except Exception:  # noqa: BLE001 - 读不到就按无数值字段处理
            numeric = []
        self._numeric_field_cache[path] = numeric
        return numeric

    def _refresh_variable_options(self):
        """根据已导入数据的字段刷新分析字段列表。"""
        fields = self._available_fields() or ["pop2024", "worldpop"]
        selected = self._selected_variables()
        if not selected:
            # 默认勾选前两个数值字段，直接点运行也有意义；找不到数值字段时退回前两个
            preferred = []
            for source in self.store.sources:
                preferred = self._numeric_fields_of_source(source.path)
                if len(preferred) >= 2:
                    break
            selected = (preferred or fields)[:2]
        self._rebuild_variable_list(fields, selected)
        self._refresh_pair_preview()

    def _on_variables_changed(self, _item=None):
        """勾选变化：配对集合变了，预览、配对下拉与带宽快照全部作废重来。"""
        self._refresh_pair_preview()
        mode = "attribute"
        self._bandwidth_snapshots.pop(mode, None)
        self._clear_bandwidth_caches(mode)
        self._bw_count_cache.clear()
        metrics = getattr(self, "bw_metrics_label", None)
        if metrics is not None:
            metrics.setText("分析字段已变化，请重新生成带宽快照")

    def _move_variable(self, offset):
        """上下移动选中字段——调换顺序即调换配对里的 Y / X 角色。"""
        row = self.var_list.currentRow()
        target = row + offset
        if row < 0 or not (0 <= target < self.var_list.count()):
            return
        item = self.var_list.takeItem(row)
        self.var_list.insertItem(target, item)
        self.var_list.setCurrentRow(target)
        self._on_variables_changed()

    def _refresh_pair_preview(self, *_):
        variables = self._selected_variables()
        pairs = attribute_pairs(variables)
        if len(variables) < 2:
            self.pair_preview.setText("请至少勾选两个字段")
        else:
            text = "、".join(pair_label(y, x) for y, x in pairs)
            self.pair_preview.setText(f"共 {len(pairs)} 组配对：{text}")
        self._refresh_pair_options()

    def _refresh_pair_options(self):
        """按当前勾选的字段重建配对下拉框。"""
        combo = getattr(self, "pair_combo", None)
        if combo is None:
            return
        pairs = attribute_pairs(self._selected_variables())
        previous = combo.currentData()
        combo.blockSignals(True)
        try:
            combo.clear()
            for y, x in pairs:
                combo.addItem(pair_label(y, x), pair_key(y, x))
            if previous:
                index = combo.findData(previous)
                if index >= 0:
                    combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)
        # 只有一组配对时没有可切换的对象，整行藏起来省版面
        self.pair_row_widget.setVisible(len(pairs) > 1)

    def _current_pair(self):
        """当前查看的配对键；未选择时回落第一组。"""
        combo = getattr(self, "pair_combo", None)
        if combo is not None:
            key = combo.currentData()
            if key:
                return key
        pairs = attribute_pairs(self._selected_variables())
        return pair_key(*pairs[0]) if pairs else ""

    def _current_pair_label(self):
        return self.pair_combo.currentText() if getattr(self, "pair_combo", None) else ""

    def current_pair_key(self):
        """供主窗口记录到运行快照里的配对键。"""
        return self._current_pair()

    def _result_shp_for(self, key):
        """本次运行中某个配对写出的结果 SHP；没有则返回空串。"""
        return (self.latest_result.shp_by_pair or {}).get(key, "")

    def primary_result_shp(self):
        """该自动加载到地图的结果 SHP：优先当前配对，其次算法回传的第一组。"""
        shp = self._result_shp_for(self._current_pair())
        if shp and Path(shp).exists():
            return shp
        return getattr(self.latest_result, "output_shp", "") or ""

    def _on_pair_changed(self, *_):
        """切换配对：地图与属性表换到该配对的结果 SHP，带宽着色跟着重算。"""
        if self._current_mode() != "attribute":
            return
        key = self._current_pair()
        if not key:
            return
        shp = self._result_shp_for(key)
        if shp and Path(shp).exists():
            # 带宽快照是基于源数据、与配对无关，切配对时不能一起清掉
            self.load_shp(shp, reset_xy=False, fill_table=False, keep_bandwidth=True)
            self._show_results(self._source_shp_path or shp, None, result_shp=shp)
        # 带宽配色缓存的键里本来就带配对，各配对互不干扰，切回来还能直接命中
        mode = "attribute"
        snapshots = self._bandwidth_snapshots.get(mode)
        if snapshots:
            index = self._bandwidth_index(self.bandwidth_slider.value(), mode)
            if index is not None:
                self._update_bandwidth_legend(index)
                self._set_bandwidth_map(index)
            self._update_metric_line(index if index is not None else 0)

    def _refresh_raster_options(self):
        if self.raster_list is None:
            return
        current_selected = self._selected_raster_paths()
        manifest = RasterPreprocessor(self.store.project_dir).latest_manifest() or {}
        if not current_selected:
            current_selected = set(manifest.get("selected_sources", []))
        raster_sources = [
            source for source in self.store.sources
            if "栅格" in source.data_type or Path(source.path).suffix.lower() in {".tif", ".tiff", ".img", ".asc"}
        ]
        if not current_selected:
            current_selected = {source.path for source in raster_sources}
        self.raster_list.blockSignals(True)
        self.raster_list.clear()
        for source in raster_sources:
            item = QListWidgetItem(f"{source.icon}  {source.name} · {source.records}")
            item.setData(Qt.ItemDataRole.UserRole, source.path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if source.path in current_selected else Qt.CheckState.Unchecked
            )
            self.raster_list.addItem(item)
        self.raster_list.blockSignals(False)

    def _selected_raster_paths(self):
        if self.raster_list is None:
            return []
        return [
            self.raster_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.raster_list.count())
            if self.raster_list.item(index).checkState() == Qt.CheckState.Checked
        ]

    def _refresh_geometry_sources(self):
        sources = [s for s in self.store.sources if Path(s.path).suffix.lower() == ".shp"]
        previous_a = self.geometry_a_combo.currentData()
        previous_b = self.geometry_b_combo.currentData()
        for combo in (self.geometry_a_combo, self.geometry_b_combo):
            combo.blockSignals(True)
            combo.clear()
            for source in sources:
                combo.addItem(source.name, source.path)
            combo.blockSignals(False)
        if previous_a and self.geometry_a_combo.findData(previous_a) >= 0:
            self.geometry_a_combo.setCurrentIndex(self.geometry_a_combo.findData(previous_a))
        if previous_b and self.geometry_b_combo.findData(previous_b) >= 0:
            self.geometry_b_combo.setCurrentIndex(self.geometry_b_combo.findData(previous_b))
        elif self.geometry_b_combo.count() > 1:
            self.geometry_b_combo.setCurrentIndex(1)
        self._refresh_geometry_fields()

    def _source_for_path(self, path):
        return next((source for source in self.store.sources if source.path == path), None)

    def _refresh_geometry_fields(self, *_):
        for source_combo, field_combo in (
            (self.geometry_a_combo, self.geometry_a_field_combo),
            (self.geometry_b_combo, self.geometry_b_field_combo),
        ):
            current = field_combo.currentText()
            source = self._source_for_path(source_combo.currentData())
            field_combo.blockSignals(True)
            field_combo.clear()
            if source:
                field_combo.addItems(source.fields)
            preferred = field_combo.findText("gridcode", Qt.MatchFlag.MatchFixedString)
            if current and field_combo.findText(current) >= 0:
                field_combo.setCurrentText(current)
            elif preferred >= 0:
                field_combo.setCurrentIndex(preferred)
            field_combo.blockSignals(False)
        self._refresh_geometry_mapping()

    @staticmethod
    def _value_sort_key(value):
        try:
            return (0, float(value))
        except (TypeError, ValueError):
            return (1, str(value))

    def _refresh_geometry_mapping(self, *_):
        path_a = self.geometry_a_combo.currentData()
        path_b = self.geometry_b_combo.currentData()
        field_a = self.geometry_a_field_combo.currentText()
        field_b = self.geometry_b_field_combo.currentText()
        try:
            values_a = sorted(read_unique_values(path_a, field_a), key=self._value_sort_key) if path_a and field_a else []
            values_b = sorted(read_unique_values(path_b, field_b), key=self._value_sort_key) if path_b and field_b else []
        except Exception as exc:  # noqa: BLE001
            self.geometry_mapping_table.setRowCount(0)
            self.statusMessage.emit(f"类别值读取失败：{exc}")
            return
        if path_a and field_a and path_b and field_b and not values_a and not values_b:
            self.statusMessage.emit("未读取到类别值，请确认 SHP 的 DBF 文件存在且类别字段有值")
        common = sorted(set(values_a) & set(values_b), key=self._value_sort_key)
        rest_a = [value for value in values_a if value not in common]
        rest_b = [value for value in values_b if value not in common]
        pairs = [(value, value) for value in common]
        pairs.extend(
            (rest_a[index] if index < len(rest_a) else "", rest_b[index] if index < len(rest_b) else "")
            for index in range(max(len(rest_a), len(rest_b)))
        )
        self.geometry_mapping_table.setRowCount(len(pairs))
        for row, (value_a, value_b) in enumerate(pairs):
            enabled = QTableWidgetItem()
            enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            enabled.setCheckState(Qt.CheckState.Checked if value_a and value_b else Qt.CheckState.Unchecked)
            self.geometry_mapping_table.setItem(row, 0, enabled)
            self.geometry_mapping_table.setItem(row, 1, QTableWidgetItem(value_a))
            self.geometry_mapping_table.setItem(row, 2, QTableWidgetItem(value_b))
            label = value_a if value_a == value_b else f"{value_a} ↔ {value_b}".strip()
            self.geometry_mapping_table.setItem(row, 3, QTableWidgetItem(label))

    def _browse_geometry_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择几何分析输出目录")
        if path:
            self.geometry_output_input.setText(path)

    def _geometry_parameters(self):
        path_a = self.geometry_a_combo.currentData() or ""
        path_b = self.geometry_b_combo.currentData() or ""
        if not path_a or not path_b:
            return None, "请先导入并选择两个 SHP 数据"
        if path_a == path_b:
            return None, "几何数据 A 和 B 不能是同一个文件"
        field_a = self.geometry_a_field_combo.currentText().strip()
        field_b = self.geometry_b_field_combo.currentText().strip()
        if not field_a or not field_b:
            return None, "请分别选择 A 和 B 的类别字段"
        mappings = []
        for row in range(self.geometry_mapping_table.rowCount()):
            enabled = self.geometry_mapping_table.item(row, 0)
            if enabled is None or enabled.checkState() != Qt.CheckState.Checked:
                continue
            value_a = (self.geometry_mapping_table.item(row, 1).text() if self.geometry_mapping_table.item(row, 1) else "").strip()
            value_b = (self.geometry_mapping_table.item(row, 2).text() if self.geometry_mapping_table.item(row, 2) else "").strip()
            label = (self.geometry_mapping_table.item(row, 3).text() if self.geometry_mapping_table.item(row, 3) else "").strip()
            if not value_a or not value_b:
                return None, f"第 {row + 1} 行已启用，但 A/B 类别值不完整"
            mappings.append({"a_value": value_a, "b_value": value_b, "label": label or f"{value_a}-{value_b}"})
        if not mappings:
            return None, "至少需要启用一组类别映射"
        if len({m["a_value"] for m in mappings}) != len(mappings) or len({m["b_value"] for m in mappings}) != len(mappings):
            return None, "启用的类别映射中存在重复的 A 值或 B 值"
        try:
            thresholds = [float(value.strip()) for value in self.geometry_thresholds_input.text().split(",") if value.strip()]
        except ValueError:
            return None, "IoU 阈值必须是用英文逗号分隔的数字"
        if len(thresholds) != 9 or len(set(thresholds)) != 9 or any(value <= 0 or value > 1 for value in thresholds):
            return None, "3×3 图要求填写 9 个不重复且位于 (0, 1] 的 IoU 阈值"
        crs = self.geometry_crs_input.text().strip()
        if not crs:
            return None, "计算投影 CRS 不能为空"
        return {
            "analysis_type": "geometry",
            "backend": "外接矩形法几何交叉验证",
            "geometry_a": path_a,
            "geometry_b": path_b,
            "category_field_a": field_a,
            "category_field_b": field_b,
            "category_mappings": mappings,
            "projected_crs": crs,
            "min_area_m2": self.geometry_min_area_spin.value(),
            "thresholds": sorted(thresholds),
            "bandwidth_m": self.geometry_bandwidth_spin.value(),
            "output_dir": self.geometry_output_input.text().strip(),
            "write_report": self.geometry_report_checkbox.isChecked(),
            "write_figures": self.geometry_figures_checkbox.isChecked(),
        }, ""

    def _current_mode(self):
        """根据当前页签返回分析模式：attribute / raster / geometry。"""
        index = self.param_tabs.currentIndex()
        if index == 1:
            return "raster"
        if index == 2:
            return "geometry"
        return "attribute"

    def _on_mode_changed(self, _index):
        mode = self._current_mode()
        # 带宽区间面板对三种模式都可见（属性 / 栅格 / 几何各有带宽含义）
        bandwidth_panel = getattr(self, "bandwidth_panel", None)
        if bandwidth_panel is not None:
            bandwidth_panel.setVisible(True)
        save_result_shp = getattr(self, "save_result_shp", None)
        if save_result_shp is not None:
            save_result_shp.setVisible(mode == "attribute")
        if mode == "geometry":
            self._refresh_geometry_sources()
        self._apply_bandwidth_mode(mode)

    def _apply_bandwidth_mode(self, mode):
        """按当前分析模式配置带宽区间面板：滑块范围 / 步长范围 / 单位 / 说明。"""
        spec = _BANDWIDTH_MODES.get(mode)
        slider = getattr(self, "bandwidth_slider", None)
        if spec is None or slider is None:
            return
        lo, hi = _BANDWIDTH_PERCENT["lo"], _BANDWIDTH_PERCENT["hi"]
        step_lo, step_hi = _BANDWIDTH_STEP_RANGE
        slider.blockSignals(True)
        self.bandwidth_step_spin.blockSignals(True)
        slider.setRange(lo, hi)
        self.bandwidth_step_spin.setRange(step_lo, step_hi)
        step = self._bw_step_values.get(mode, _BANDWIDTH_STEP_DEFAULT)
        if not (step_lo <= step <= step_hi):
            step = _BANDWIDTH_STEP_DEFAULT
        self.bandwidth_step_spin.setValue(step)
        slider.setSingleStep(step)
        slider.setPageStep(max(step * 2, 1))
        value = self._bw_slider_values.get(mode, _BANDWIDTH_PERCENT["default"])
        if not (lo <= value <= hi):
            value = _BANDWIDTH_PERCENT["default"]
        slider.setValue(value)
        slider.blockSignals(False)
        self.bandwidth_step_spin.blockSignals(False)
        self._refresh_bandwidth_baseline_hint()
        self.bw_lo_label.setText(f"{lo}%")
        self.bw_hi_label.setText(f"{hi}%")
        self.bw_step_unit.setText("%")
        self._refresh_bandwidth_sequence_hint()
        # 刷新展示（不自动触发快照生成）
        self._on_bandwidth_slider_changed(slider.value(), auto_generate=False)

    def collect_parameters(self) -> dict:
        mode = self._current_mode()
        if mode == "geometry":
            parameters, _ = self._geometry_parameters()
            return parameters or {}
        backend = "栅格 R / terra" if mode == "raster" else "R 属性 GWR"
        parameters = AnalysisParameters(
            variables=self._selected_variables(),
            kernel=self.kernel_combo.currentText(),
            bandwidth=self.bandwidth_input.text(),
            bandwidth_mode=self.bandwidth_mode_combo.currentText(),
            backend=backend,
        ).to_dict()
        parameters.update({
            "analysis_type": "raster" if mode == "raster" else "attribute",
            "auto_bandwidth": self.auto_bandwidth.isChecked(),
            "write_shp": self.save_result_shp.isChecked(),
        })
        if mode == "raster":
            parameters.update(RasterAnalysisParameters(
                window_size=self.raster_window_spin.value(),
                resampling=self.raster_resampling_combo.currentText(),
                zero_epsilon=self.raster_epsilon_spin.value(),
                write_local_rasters=self.raster_local_checkbox.isChecked(),
                write_scatter_plot=self.raster_scatter_checkbox.isChecked(),
            ).to_dict())
            parameters["raster_paths"] = list(self._selected_raster_paths())
        return parameters

    def run(self):
        if not self.run_button.isEnabled():
            return
        if self._current_mode() == "geometry":
            parameters, error = self._geometry_parameters()
            if error:
                self.geometry_validation_label.setText("配置错误：" + error)
                self.geometry_validation_label.setStyleSheet(
                    "padding: 7px; color: #a23b32; background: #fdecea; border-radius: 4px;"
                )
                self.statusMessage.emit(error)
                QMessageBox.warning(self, "几何配置检查", error)
            else:
                message = f"配置校验通过，正在提交 {len(parameters['category_mappings'])} 组类别进行计算…"
                self.geometry_validation_label.setText(message)
                self.geometry_validation_label.setStyleSheet(
                    "padding: 7px; color: #1f695e; background: #e3f3ef; border-radius: 4px;"
                )
                self.statusMessage.emit(message)
                self.set_run_busy(True)
                self.runRequested.emit(parameters)
            return
        self.set_run_busy(True)
        self.runRequested.emit(self.collect_parameters())

    def set_run_busy(self, busy):
        self.run_button.setEnabled(not busy)
        self.run_button.setText("⏳ 运行中…" if busy else "▶ 运行")
        self.run_button.setStyleSheet(
            "QPushButton { background: #9aa9a6; color: #ffffff; border: 0; }" if busy else ""
        )

    def load_shp(self, path, reset_xy=True, fill_table=True, keep_bandwidth=False):
        """把矢量 / 栅格显示到小地图。矢量解析在后台线程进行，不阻塞界面。

        fill_table=False 用于「分析完成后自动加载结果 SHP」等场景：属性表此时已由
        _show_results 填好带 GWR 结果列的内容，不应被原始的字段表覆盖。
        keep_bandwidth=True 用于「切换配对」：换的只是同一份源数据的另一套结果列，
        带宽快照仍在有效期内，不该被清掉重算。
        """
        suffix = Path(path).suffix.lower()
        if suffix in {".tif", ".tiff", ".img", ".asc"}:
            self.map_canvas.load_raster(path)
            self.statusMessage.emit(f"正在加载栅格：{Path(path).name}")
            return
        if suffix != ".shp":
            self.statusMessage.emit("仅支持 SHP 或栅格（TIF/IMG/ASC）显示")
            return
        self._start_vector_load(path, reset_xy, fill_table, keep_bandwidth)

    def _start_vector_load(self, path, reset_xy, fill_table=True, keep_bandwidth=False):
        """后台解析矢量后加载到小地图。

        栅格转面等来源的 SHP 可达十几万要素，解析 + 建缓存需要数秒；放在工作线程
        执行，界面始终可响应，并立即显示「加载中」占位。
        """
        self._vector_load_seq += 1
        self._pending_reset_xy = reset_xy
        self._pending_fill_table = fill_table
        self._pending_keep_bandwidth = keep_bandwidth
        name = Path(path).name
        self.map_canvas.set_loading(True, f"正在加载矢量：{name}")
        self.statusMessage.emit(f"正在加载矢量：{name}")

        thread = QThread(self)
        worker = VectorLoadWorker(self._vector_load_seq, path, _MAP_MAX_RECORDS)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_vector_loaded)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # 持有引用，避免线程 / 工作对象被 GC 导致 started 信号不触发。
        # 释放放在本类的槽里（主线程）而非 thread.finished 上：后者在工作线程触发，
        # 且 QThread 被 deleteLater 回收后再取属性会抛 "wrapped C/C++ object deleted"。
        self._vector_loads[self._vector_load_seq] = (thread, worker)
        thread.start()

    @Slot(int, str, object, str)
    def _on_vector_loaded(self, seq, path, payload, error):
        self._vector_loads.pop(seq, None)
        # 已被后续加载请求取代的过期结果直接丢弃，避免旧数据覆盖新图层。
        if seq != self._vector_load_seq:
            return
        self.map_canvas.set_loading(False)
        if error or not payload:
            self.statusMessage.emit(f"矢量加载失败：{error}")
            return
        geometry = payload["geometry"]
        attrs = payload["attrs"]
        self._map_path = path
        self._map_geometry = geometry
        self._map_fields = attrs["fields"]
        self._map_values = {f: [] for f in self._map_fields}
        for row in attrs["rows"]:
            for c, f in enumerate(self._map_fields):
                self._map_values[f].append(row[c] if c < len(row) else None)
        self.map_canvas.load_shapes(geometry)
        if self._pending_fill_table:
            # 属性表跟地图走：表行与地图要素一一对应，两者才能按行联动高亮
            self._fill_table_from_map()
        if not self._pending_keep_bandwidth:
            self._reset_bandwidth_explore()
        self._refresh_symbology_fields()
        self._apply_pending_symbology_field()
        if self._pending_reset_xy:
            self._refresh_xy_from_map()
        self._refresh_chart_window()
        shown = len(geometry["geometries"])
        note = f"，仅显示前 {_MAP_MAX_RECORDS:,} 个要素" if shown >= _MAP_MAX_RECORDS else ""
        self.statusMessage.emit(f"已加载 {shown:,} 个几何要素到地图{note}")

    def _on_map_raster_loaded(self, error):
        if error:
            self.statusMessage.emit(f"栅格打开失败：{error}")
        else:
            self.statusMessage.emit("栅格已加载到小地图")

    def _feature_label(self, fid):
        name = self._map_values.get("name", [])
        info = f"要素 #{fid}"
        if name and fid < len(name):
            info += f"（{name[fid]}）"
        return info

    def _select_table_rows(self, rows):
        """在属性表中选中若干行并滚动到首行（不回弹触发地图高亮）。"""
        if not self._table_linked:
            return
        rows = [r for r in rows if 0 <= r < self.attr_model.rowCount()]
        self._syncing_selection = True
        try:
            selection = QItemSelection()
            last_column = max(self.attr_model.columnCount() - 1, 0)
            for r in rows:
                selection.select(self.attr_model.index(r, 0), self.attr_model.index(r, last_column))
            flags = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
            self.result_table.selectionModel().select(selection, flags)
            if rows:
                self.result_table.scrollTo(self.attr_model.index(rows[0], 0))
        finally:
            self._syncing_selection = False

    def _on_map_feature_clicked(self, fid):
        """地图点要素：高亮该要素，并在属性表中选中对应行。"""
        self.map_canvas.highlight_features(fid)
        if self._chart_window is not None:
            self._chart_window.highlight_feature(fid)
        self._select_table_rows([fid])
        self.statusMessage.emit(f"已高亮 {self._feature_label(fid)}")

    def _on_table_selection_changed(self):
        """属性表选中若干行：地图上对应的区域一起高亮。"""
        if self._syncing_selection or not self._table_linked:
            return
        rows = sorted({index.row() for index in self.result_table.selectionModel().selectedIndexes()})
        self.map_canvas.highlight_features(rows)
        if self._chart_window is not None:
            self._chart_window.highlight_feature(rows[0] if rows else None)
        if not rows:
            self.statusMessage.emit("已取消高亮")
        elif len(rows) == 1:
            self.statusMessage.emit(f"已高亮 {self._feature_label(rows[0])}")
        else:
            self.statusMessage.emit(f"已在属性表中选中 {len(rows)} 行，地图上对应区域已高亮")

    def _on_chart_feature_selected(self, fid):
        self.map_canvas.highlight_features(fid)
        self._select_table_rows([fid])
        self.statusMessage.emit(f"已高亮 {self._feature_label(fid)}")

    def _on_chart_selection_cleared(self):
        self.map_canvas.highlight_features(None)
        self._select_table_rows([])
        self.statusMessage.emit("已取消高亮")

    def _open_chart_window(self):
        if self._chart_window is None:
            self._chart_window = ChartWindow()
            self._chart_window.featureSelected.connect(self._on_chart_feature_selected)
            self._chart_window.selectionCleared.connect(self._on_chart_selection_cleared)
        self._chart_window.update_data(self._map_fields, self._map_values)
        self._chart_window.show()
        self._chart_window.raise_()
        self._chart_window.activateWindow()

    def _refresh_chart_window(self):
        if self._chart_window is not None:
            self._chart_window.update_data(self._map_fields, self._map_values)

    def _refresh_xy_from_map(self):
        """拖入新 SHP 后，把分析字段列表刷新为该文件的数值字段。

        已勾选的字段只要在新图层里还在就原样保留（含顺序）；只在不足两个时才
        从数值字段里补够。用户勾了三个字段要跑三组配对，不该因为换一份数据、
        或某几个字段在新图层里换了写法就悄悄塌成两个。
        """
        numeric = self._numeric_fields()
        if not numeric:
            return
        selected = [value for value in self._selected_variables() if value in numeric]
        for value in numeric:
            if len(selected) >= 2:
                break
            if value not in selected:
                selected.append(value)
        self._rebuild_variable_list(numeric, selected)
        self._refresh_pair_preview()

    def _numeric_fields(self):
        numeric = []
        for f in self._map_fields:
            vals = [v for v in self._map_values.get(f, []) if v is not None]
            if vals and all(isinstance(v, (int, float)) for v in vals):
                numeric.append(f)
        return numeric

    def _symbology_fields(self):
        """设色字段候选：按唯一值设色时纳入全部字段（类别常在文本字段里），否则只要数值字段。"""
        if self.symbology_method_combo.currentText() == "唯一值":
            numeric = self._numeric_fields()
            return numeric + [f for f in self._map_fields if f not in numeric]
        return self._numeric_fields()

    def _apply_pending_symbology_field(self):
        """图层加载完成后补一次设色字段还原（见 restore_run 的说明）。

        无论这次能不能设上都要清掉暂存值：换的是另一份数据时该字段本就不存在，
        留着只会污染下一次加载。
        """
        field = self._pending_symbology_field
        if not field:
            return
        self._pending_symbology_field = ""
        if self.symbology_field_combo.findText(field) >= 0:
            self.symbology_field_combo.setCurrentText(field)

    def _refresh_symbology_fields(self):
        fields = self._symbology_fields()
        current = self.symbology_field_combo.currentText()
        self.symbology_field_combo.blockSignals(True)
        self.symbology_field_combo.clear()
        self.symbology_field_combo.addItems(fields)
        self.symbology_field_combo.blockSignals(False)
        if current and current in fields:
            self.symbology_field_combo.setCurrentText(current)
        elif "Local_R2" in fields:
            # 运行 GWR 后默认展示局部 R²（与带宽区间探索的地图着色一致）
            self.symbology_field_combo.setCurrentText("Local_R2")
        self._update_field_tooltip()
        self._apply_symbology()

    def _classify_series(self, values):
        """按当前设色方法分级，返回 (labels, indices, colors)。

        labels 为各类别显示名，唯一值是取值本身，区间方法是 "a–b" 文本；
        indices 与 values 等长（缺失为 None），colors 与 labels 一一对应。
        """
        if self.symbology_method_combo.currentText() == "唯一值":
            labels, indices = classify_unique(values)
            return labels, indices, categorical_colors(len(labels))
        method = self.symbology_method_combo.currentText()
        n_classes = self.symbology_classes_spin.value()
        manual = self._parse_manual_breaks() if method == "手动" else None
        breaks, indices = classify(values, method, n_classes, manual)
        n = len(breaks) - 1
        if n <= 0:
            return [], indices, []
        labels = [f"{self._fmt_number(breaks[i])}–{self._fmt_number(breaks[i + 1])}" for i in range(n)]
        return labels, indices, auto_colors(values, n)

    def _apply_symbology(self):
        field = self.symbology_field_combo.currentText()
        if not field or field not in self._map_values:
            self.map_canvas.set_feature_colors([])
            self._clear_legend()
            return
        values = self._map_values[field]
        labels, indices, colors = self._classify_series(values)
        nc = len(labels)
        if nc <= 0:
            self.map_canvas.set_feature_colors([])
            self._clear_legend()
            return
        feature_colors = [None] * len(indices)
        for i, idx in enumerate(indices):
            if idx is not None and 0 <= idx < nc:
                feature_colors[i] = QColor(colors[idx])
        self.map_canvas.set_feature_colors(feature_colors)
        self._update_legend(labels, colors)
        if self.map_note is not None:
            self.map_note.setText(f"{field} · {len(labels)} 类")

    def _on_method_changed(self, method):
        self.manual_breaks_input.setVisible(method == "手动")
        # 唯一值的类别由字段取值决定，分级数不适用
        self.symbology_classes_spin.setEnabled(method not in ("手动", "唯一值"))
        # 唯一值允许选文本字段，其余方法只列数值字段，故切换方法时重填字段候选
        self._refresh_symbology_fields()

    def _update_field_tooltip(self, field=None):
        if field is None:
            field = self.symbology_field_combo.currentText()
        if not field or field not in self._map_values:
            self.field_info_label.set_info("鼠标悬停查看设色字段含义与分级配色说明")
            return
        y, x = parse_pair_key(self._current_pair())
        meaning, level_hint = pair_field_info(field, y, x)
        values = self._map_values[field]
        if self.symbology_method_combo.currentText() == "唯一值":
            ramp_hint = "类别色板：每个不同取值为一类，颜色之间没有大小含义"
        else:
            # 只拿数值比大小：文本字段参与 min() 会抛 TypeError
            vals = [v for v in values if isinstance(v, (int, float))]
            ramp_hint = ("发散色带：蓝色=负值，白色≈0，红色=正值" if vals and min(vals) < 0
                         else "单色渐变：颜色越深，数值越大")
        self.field_info_label.set_info(
            f"字段：{field}\n含义：{meaning}\n分级解读：{level_hint}\n配色：{ramp_hint}"
        )

    def _parse_manual_breaks(self):
        text = self.manual_breaks_input.text().strip()
        if not text:
            return None
        parts = [p.strip() for p in text.replace("，", ",").split(",") if p.strip()]
        try:
            return [float(p) for p in parts]
        except ValueError:
            return None

    def _update_legend(self, labels, colors):
        clear_layout(self.legend_layout)
        # 面板不滚动：唯一值可能有几十类，全部铺开会把面板撑变形，故只列前若干类。
        shown = min(len(labels), len(colors), _LEGEND_MAX_ITEMS)
        for i in range(shown):
            text = labels[i]
            item = QWidget()
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(4)
            swatch = QLabel(" ")
            swatch.setFixedSize(16, 12)
            swatch.setStyleSheet(f"background: {colors[i]}; border: 1px solid #cbd5d2; border-radius: 2px;")
            item_layout.addWidget(swatch)
            label = QLabel(text)
            label.setObjectName("Muted")
            item_layout.addWidget(label, 1)
            self.legend_layout.addWidget(item, i // 2, i % 2)
        if len(labels) > shown:
            note = QLabel(f"… 共 {len(labels)} 类，图例仅列前 {shown} 类")
            note.setObjectName("Muted")
            self.legend_layout.addWidget(note, (shown - 1) // 2 + 1, 0, 1, 2)

    def _clear_legend(self):
        clear_layout(self.legend_layout)

    @staticmethod
    def _fmt_number(v):
        if isinstance(v, float):
            if abs(v - round(v)) < 1e-9:
                return str(int(round(v)))
            return f"{v:.4g}"
        return str(v)

    def _fill_table(self, fields, columns, note):
        """填充属性表。填表会清空选中，用标志位避免反过来触发地图高亮。"""
        self._syncing_selection = True
        try:
            self.attr_model.set_columns(fields, columns, max((len(c) for c in columns), default=0))
        finally:
            self._syncing_selection = False
        self.attr_hint.setText(note)

    def _fill_table_from_map(self):
        """用地图当前数据填属性表，使表行与地图要素一一对应（联动高亮的前提）。"""
        if not self._map_fields:
            return
        # 直接引用 _map_values，不复制：模型按需取值，十几万行也不额外占内存
        columns = [self._map_values.get(f, []) for f in self._map_fields]
        total = max((len(c) for c in columns), default=0)
        name = Path(self._map_path).name if self._map_path else ""
        self._fill_table(self._map_fields, columns, f"{name}：{total:,} 行 · {len(self._map_fields)} 字段")
        self._table_linked = True

    def _load_source_table(self, path):
        data = read_attributes(path, limit=_MAP_MAX_RECORDS)
        fields = data["fields"]
        rows = data["rows"]
        name = Path(path).stem
        if not fields:
            self._syncing_selection = True
            try:
                self.attr_model.clear()
            finally:
                self._syncing_selection = False
            self._table_linked = False
            self.attr_hint.setText(f"无法读取属性表：{path}")
            self.statusMessage.emit(f"无法读取属性表：{path}")
            return
        note = f"{name}：{len(rows)} 行 · {len(fields)} 字段"
        if data["truncated"]:
            note += "（已截断）"
        self._fill_table(fields, columns_from_rows(fields, rows), note)
        # 只有拖入的正是地图当前数据时，行序才与地图要素对应，联动才有意义
        self._table_linked = Path(path) == Path(self._map_path) if self._map_path else False
        if not self._table_linked:
            note += "（与地图数据不一致，未启用联动高亮）"
            self.attr_hint.setText(note)
        self.statusMessage.emit(f"已加载属性表：{note}")

    # 算法 JSON 回传的结果列 → 属性表列头（仅在拿不到结果 SHP 时使用）
    _RESULT_COLUMN_SPECS = [
        ("local_r2", "局部 R²"),
        ("coefficient", "系数"),
        ("local_corr", "局部相关系数"),
        ("lme", "LME"),
        ("lmae", "LMAE"),
        ("lmre", "LMRE"),
        ("lrmse", "LRMSE"),
    ]

    def _show_results(self, shp_path, result_columns=None, result_shp=""):
        """把结果列展示到属性表。

        优先直接读结果 SHP：它按原始要素顺序写出、且结果列就在字段里，行序与地图
        要素严格一致，联动高亮才成立；多字段时每组配对各有自己的结果 SHP，读它
        也就不必把几百万个数值从算法 JSON 里搬过来。
        拿不到结果 SHP（未勾选「运行后生成结果 SHP」或写出失败）时，退回
        「源数据 + 算法回传的结果列」——这条路径只对第一组配对有效。
        """
        target = result_shp if (result_shp and Path(result_shp).exists()) else shp_path
        if not target or not Path(target).exists():
            return
        data = read_attributes(target, limit=_MAP_MAX_RECORDS)
        fields = list(data["fields"])
        rows = data["rows"]
        table_columns = columns_from_rows(fields, rows)
        extra = ""
        if Path(target) == Path(shp_path) and result_columns:
            for key, label in self._RESULT_COLUMN_SPECS:
                values = result_columns.get(key)
                if values is None:
                    continue
                fields.append(label)
                table_columns.append([values[i] if i < len(values) else None for i in range(len(rows))])
            extra = "（含 GWR 结果列）"
        name = Path(target).stem
        pair = self._current_pair_label()
        note = f"{name}：{len(rows)} 行 · {len(fields)} 字段{extra}"
        if pair:
            note = f"{pair} · {note}"
        self._fill_table(fields, table_columns, note)
        # 结果 SHP 按原始要素顺序写出，故表行与地图要素仍一一对应
        self._table_linked = True

    def _save_result_shp(self):
        src = self._result_output_shp
        if not src or not Path(src).exists():
            self.statusMessage.emit("没有可保存的结果 SHP（请先运行分析并勾选“运行后生成结果 SHP”）")
            return
        dest, _ = QFileDialog.getSaveFileName(self, "保存结果 Shapefile", "", "Shapefile (*.shp)")
        if not dest:
            return
        dest = Path(dest)
        if dest.suffix.lower() != ".shp":
            dest = dest.with_suffix(".shp")
        src_path = Path(src)
        try:
            for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                s = src_path.with_suffix(ext)
                if s.exists():
                    shutil.copy2(s, dest.with_suffix(ext))
            self.statusMessage.emit(f"结果已保存：{dest}")
        except OSError as exc:
            self.statusMessage.emit(f"保存失败：{exc}")

    # ------------------------------------------------------------------ #
    # 带宽区间探索
    # ------------------------------------------------------------------ #
    def _reset_bandwidth_explore(self):
        self._bandwidth_snapshots = {}
        self._bandwidth_color_cache = {}
        self._bandwidth_legend_cache = {}
        self._bandwidth_generating = False
        metrics = getattr(self, "bw_metrics_label", None)
        if metrics is not None:
            metrics.setText("生成带宽快照后显示各带宽指标")
        legend_layout = getattr(self, "bw_legend_layout", None)
        if legend_layout is not None:
            clear_layout(legend_layout)
        status = getattr(self, "bw_status", None)
        if status is not None:
            status.setText("选好参数后，拖动滑块即自动生成并查看地图变化")
        # 数据换了，100% 对应的基准随之变化，提示与换算值要跟着刷新
        if getattr(self, "bandwidth_slider", None) is not None:
            self._refresh_bandwidth_baseline_hint()

    def _bandwidth_baseline(self, mode=None):
        """当前模式 100% 对应的实际带宽基准，返回 (基准值, 说明)；无法推算返回 (None, 原因)。

        基准随数据而定，不写死：自适应带宽以有效样本数上限，距离类以研究区范围上限，
        栅格窗口以栅格短边像素数上限。结果按数据缓存，避免反复解析大文件。
        """
        mode = mode or self._current_mode()
        if mode == "raster":
            paths = self._selected_raster_paths()
            if not paths:
                return None, "请先在「栅格数据」页签勾选栅格"
            key = ("raster", tuple(paths))
            if key in self._bw_baseline_cache:
                return self._bw_baseline_cache[key]
            try:
                import rasterio
                with rasterio.open(paths[0]) as dataset:
                    side = min(dataset.width, dataset.height)
                if side <= _RASTER_WINDOW_MAX:
                    result = (side, f"栅格短边 {side:,} 像素")
                else:
                    result = (_RASTER_WINDOW_MAX,
                              f"窗口上限 {_RASTER_WINDOW_MAX} 像素（栅格短边 {side:,}）")
            except Exception as exc:  # noqa: BLE001 - 读不到栅格就按未知处理
                result = (None, f"无法读取栅格尺寸：{exc}")
            self._bw_baseline_cache[key] = result
            return result

        if mode == "geometry":
            path = self.geometry_a_combo.currentData()
            crs = self.geometry_crs_input.text().strip() or "EPSG:32650"
            if not path:
                return None, "请先选择几何数据 A"
            metres = self._extent_diagonal_m(path, crs)
            if metres is None:
                return None, "无法从该数据推算研究区范围"
            return metres, f"研究区范围 {metres:,.0f} m"

        # 属性模式
        path = self.source_vector_path()
        if not path:
            return None, "请先拖入 SHP 数据到地图"
        if self.bandwidth_mode_combo.currentText() == "距离（米）":
            metres = self._extent_diagonal_m(path, _ATTRIBUTE_PROJ_CRS)
            if metres is None:
                return None, "无法从该数据推算研究区范围"
            return metres, f"研究区范围 {metres:,.0f} m"
        count = self._valid_sample_count(path)
        return count, f"有效样本 {count:,} 个"

    def _valid_sample_count(self, path):
        """源矢量中全部参与字段都非空的样本数（与 R 脚本 complete.cases 的口径一致）。

        多字段时有效样本取的是「全部字段都非空」的交集——各配对共用同一份样本，
        所以这里必须按全部勾选字段统计，否则带宽滑块 100% 对应的基准会偏大。
        """
        variables = tuple(self._selected_variables())
        key = (path, variables)
        if key in self._bw_count_cache:
            return self._bw_count_cache[key]
        data = read_attributes(path, limit=0)
        fields = data["fields"]
        indexes = [fields.index(name) for name in variables if name in fields]
        if indexes:
            widest = max(indexes)
            count = sum(
                1 for row in data["rows"]
                if len(row) > widest and all(row[i] is not None for i in indexes)
            )
        else:
            count = data["row_count"]
        self._bw_count_cache[key] = count
        return count

    def _extent_diagonal_m(self, path, target_crs):
        """源矢量范围框对角线在目标投影下的长度（米）。

        用 .shp 头部已有的范围框（无需解析几何）配合 pyproj 换算到算法所用的投影，
        与 R / 几何脚本内部的米制口径一致。
        """
        key = (path, target_crs)
        if key in self._bw_extent_cache:
            return self._bw_extent_cache[key]
        result = None
        try:
            from pyproj import CRS, Transformer
            raw = Path(path).read_bytes()[:100]
            if len(raw) >= 68:
                xmin, ymin, xmax, ymax = struct.unpack_from("<4d", raw, 36)
                prj = Path(path).with_suffix(".prj")
                source = (CRS.from_wkt(prj.read_text(encoding="utf-8", errors="replace"))
                          if prj.exists() else CRS.from_user_input("EPSG:4326"))
                transform = Transformer.from_crs(
                    source, CRS.from_user_input(target_crs), always_xy=True)
                x0, y0 = transform.transform(xmin, ymin)
                x1, y1 = transform.transform(xmax, ymax)
                result = math.hypot(x1 - x0, y1 - y0)
        except Exception:  # noqa: BLE001 - 坐标系缺失或无法换算时按未知处理
            result = None
        self._bw_extent_cache[key] = result
        return result

    def _percent_to_bandwidth(self, percent, mode, baseline):
        """百分比 → 实际带宽；baseline 为 100% 对应的上限。"""
        if not baseline or baseline <= 0:
            return None
        raw = baseline * percent / 100.0
        if mode == "raster":
            value = max(3, int(round(raw)))     # 窗口须为 >=3 的奇数
            return value if value % 2 else value + 1
        if mode == "attribute" and self.bandwidth_mode_combo.currentText() != "距离（米）":
            return max(2, int(round(raw)))      # 最近邻个数至少 2
        return max(10, int(round(raw / 10.0)) * 10)   # 距离类取整到 10 m

    def _bandwidth_plan(self, mode=None):
        """当前模式的 [(百分比, 实际带宽)] 序列：百分比定轴，实际值按数据基准换算。

        换算后出现重复值时只保留一次，避免重复跑同一带宽。
        """
        mode = mode or self._current_mode()
        baseline, _note = self._bandwidth_baseline(mode)
        step = max(1, self.bandwidth_step_spin.value())
        plan, seen = [], set()
        for percent in range(_BANDWIDTH_PERCENT["lo"], _BANDWIDTH_PERCENT["hi"] + 1, step):
            value = self._percent_to_bandwidth(percent, mode, baseline)
            if value is None or value in seen:
                continue
            seen.add(value)
            plan.append((percent, value))
        return plan

    def _bandwidth_sequence(self):
        """交给算法的实际带宽序列（按步长生成的百分比换算而来）。"""
        return [value for _percent, value in self._bandwidth_plan()]

    def _bandwidth_unit(self, mode=None):
        mode = mode or self._current_mode()
        if mode == "attribute":
            return "米" if self.bandwidth_mode_combo.currentText() == "距离（米）" else "近邻"
        return _BANDWIDTH_MODES.get(mode, {}).get("unit", "")

    def _format_bandwidth(self, value, mode=None):
        return f"≈ {value:,} {self._bandwidth_unit(mode)}"

    def _bandwidth_percent_label(self, percent):
        """滑块百分比对应的换算说明，如「≈ 92,938 近邻」。"""
        mode = self._current_mode()
        baseline, note = self._bandwidth_baseline(mode)
        value = self._percent_to_bandwidth(percent, mode, baseline)
        return note if value is None else self._format_bandwidth(value, mode)

    def _refresh_bandwidth_baseline_hint(self):
        """刷新「100% = …」说明与当前百分比的换算值；数据或模式变化后调用。"""
        mode = self._current_mode()
        hint = getattr(self, "bw_mode_hint", None)
        if hint is not None:
            baseline, note = self._bandwidth_baseline(mode)
            prefix = _BANDWIDTH_MODES.get(mode, {}).get("hint", "")
            hint.setText(f"{prefix}　·　100% = {note}" if baseline else f"{prefix}　·　{note}")
        converted = getattr(self, "bw_converted", None)
        slider = getattr(self, "bandwidth_slider", None)
        if converted is not None and slider is not None:
            converted.setText(self._bandwidth_percent_label(slider.value()))
        self._refresh_bandwidth_sequence_hint()

    def _refresh_bandwidth_sequence_hint(self):
        hint = getattr(self, "bw_sequence_hint", None)
        if hint is None:
            return
        plan = self._bandwidth_plan()
        if not plan:
            hint.setText("基准未知，无法换算实际带宽")
            return
        hint.setText(f"共 {len(plan)} 个取值（{plan[0][1]:,} ~ {plan[-1][1]:,}）")

    def _on_bandwidth_meaning_changed(self, *_):
        """「带宽含义」在近邻 / 距离间切换：基准与换算值随之改变，旧快照不再适用。"""
        mode = self._current_mode()
        self._bandwidth_snapshots.pop(mode, None)
        self._clear_bandwidth_caches(mode)
        self._refresh_bandwidth_baseline_hint()

    def _on_bandwidth_step_changed(self, value):
        """步长变化：同步滑块步进，并使当前模式的快照失效（旧序列不再匹配）。"""
        mode = self._current_mode()
        self._bw_step_values[mode] = value
        self.bandwidth_slider.setSingleStep(max(1, value))
        self.bandwidth_slider.setPageStep(max(value * 2, 1))
        self._refresh_bandwidth_sequence_hint()
        self._bandwidth_snapshots.pop(mode, None)
        self._clear_bandwidth_caches(mode)
        metrics = getattr(self, "bw_metrics_label", None)
        if metrics is not None:
            metrics.setText("生成带宽快照后显示各带宽指标")
        legend_layout = getattr(self, "bw_legend_layout", None)
        if legend_layout is not None:
            clear_layout(legend_layout)
        self.bw_status.setText("步长已更新，请重新生成快照")

    def _clear_bandwidth_caches(self, mode):
        for cache in (self._bandwidth_color_cache, self._bandwidth_legend_cache):
            for key in [key for key in cache if key[0] == mode]:
                cache.pop(key, None)

    def _run_bandwidth_snapshots(self):
        mode = self._current_mode()
        if mode == "raster":
            self._run_raster_bandwidth_snapshots()
        elif mode == "geometry":
            self._run_geometry_bandwidth_snapshots()
        else:
            self._run_attribute_bandwidth_snapshots()

    def _run_attribute_bandwidth_snapshots(self):
        path = self.source_vector_path()
        variables = self._selected_variables()
        if not path:
            self.statusMessage.emit("请先拖入 SHP 数据到地图")
            return
        if len(variables) < 2:
            self.statusMessage.emit("请至少勾选两个分析字段")
            return
        config = {
            "shp_path": path,
            "variables": variables,
            "kernel": self.kernel_combo.currentText(),
            "bandwidth_mode": self.bandwidth_mode_combo.currentText(),
            "bandwidths": self._bandwidth_sequence(),
        }
        runner = RRunner(self._bandwidth_script, self._rscript_path)
        pairs = attribute_pairs(variables)
        self._start_bandwidth_worker(
            runner, config, "attribute",
            f"正在计算 {len(config['bandwidths'])} 个带宽 × {len(pairs)} 组配对…")

    def _run_raster_bandwidth_snapshots(self):
        paths = self._selected_raster_paths()
        if len(paths) < 2:
            self.statusMessage.emit("请先在「栅格数据」页签勾选至少两个栅格")
            return
        manifest = RasterPreprocessor(self.store.project_dir).latest_manifest() or {}
        aligned_by_source = {
            item.get("source_path"): item.get("aligned_path")
            for item in manifest.get("processed", [])
        }
        aligned = [aligned_by_source.get(path, path) for path in paths]
        source_by_path = {source.path: source for source in self.store.sources}
        names = [
            source_by_path[path].name if path in source_by_path else Path(path).stem
            for path in paths
        ]
        config = {
            "raster_paths": aligned,
            "raster_names": names,
            "window_sizes": self._bandwidth_sequence(),
            "resampling": self.raster_resampling_combo.currentText(),
            "zero_epsilon": self.raster_epsilon_spin.value(),
            "preview_dir": str(self.store.project_dir / ".runtime" / "bandwidth_explore" / "raster_previews"),
        }
        runner = RRunner(self._raster_bandwidth_script, self._rscript_path)
        self._start_bandwidth_worker(runner, config, "raster",
                                     f"正在计算 {len(config['window_sizes'])} 个窗口大小…")

    def _run_geometry_bandwidth_snapshots(self):
        parameters, error = self._geometry_parameters()
        if error:
            self.statusMessage.emit(error)
            return
        config = dict(parameters)
        config.pop("analysis_type", None)
        config.pop("backend", None)
        config.update({
            "bandwidths": self._bandwidth_sequence(),
            # 探索过程不产出报告/图片，全部落在 .runtime 临时目录
            "write_report": False,
            "write_figures": False,
            "output_dir": str(self.store.project_dir / ".runtime" / "bandwidth_explore" / "geometry"),
        })
        runner = PythonRunner(self._geometry_bandwidth_script)
        self._start_bandwidth_worker(runner, config, "geometry",
                                     f"正在计算 {len(config['bandwidths'])} 个带宽（米）…")

    def _start_bandwidth_worker(self, runner, config, mode, status_text):
        output_path = self.store.project_dir / ".runtime" / "bandwidth_explore" / f"result_{mode}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._bandwidth_generating_mode = mode
        self._bandwidth_generating = True
        self.generate_button.setEnabled(False)
        self.generate_button.setText("⏳ 生成中…")
        self.bw_status.setText(status_text)
        self.statusMessage.emit("正在生成带宽快照…")
        thread = QThread(self)
        worker = _BandwidthWorker(runner, config, output_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_bandwidth_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # 持有引用，避免线程/工作对象被 GC 导致 started 信号不触发。
        self._bandwidth_thread = thread
        self._bandwidth_worker = worker
        thread.start()

    @Slot(object, str)
    def _on_bandwidth_finished(self, result, error):
        mode = self._bandwidth_generating_mode or "attribute"
        self._bandwidth_generating = False
        self.generate_button.setEnabled(True)
        self.generate_button.setText("▶ 生成带宽快照")
        if error:
            self.bw_status.setText(f"生成失败：{error}")
            self.statusMessage.emit(f"带宽快照生成失败：{error}")
            return
        if not result or result.get("status") != "success":
            self.bw_status.setText(result.get("message", "生成失败") if result else "生成失败")
            self.statusMessage.emit(result.get("message", "带宽快照生成失败") if result else "带宽快照生成失败")
            return
        bandwidths = [int(b) for b in result.get("bandwidths", [])]
        if mode == "raster":
            curves = {"": result.get("curve", [])}
            raws = {"": {"local_mae": result.get("local_mae", []),
                         "previews": result.get("previews", [])}}
            probe = "local_mae"
        elif mode == "geometry":
            curves = {"": result.get("curve", [])}
            raws = {"": {"gw_iou": result.get("gw_iou", [])}}
            probe = "gw_iou"
        else:
            # 多字段：算法按配对返回 by_pair；旧版单配对输出没有 by_pair，这里补成
            # 唯一的空键，后面所有按配对取数的逻辑对两种形状都成立。
            by_pair = result.get("by_pair") or {"": result}
            curves, raws = {}, {}
            for key, entry in by_pair.items():
                curves[key] = entry.get("curve", [])
                raws[key] = {name: entry.get(name, []) for name in _BW_SERIES}
            probe = "local_r2"
            if not any(raws[key].get(probe) for key in raws):
                self.bw_status.setText("带宽快照结果为空")
                self.statusMessage.emit("带宽快照结果为空")
                return
        if not bandwidths or not any(curves.values()):
            self.bw_status.setText("带宽快照结果为空")
            self.statusMessage.emit("带宽快照结果为空")
            return
        # 滑块走百分比、快照存实际带宽，按值把两者对上，供滑块定位使用
        by_value = {value: percent for percent, value in self._bandwidth_plan(mode)}
        percents = [by_value.get(value, value) for value in bandwidths]
        self._bandwidth_snapshots[mode] = {
            "mode": mode, "percents": percents, "bandwidths": bandwidths,
            "curves": curves, "raw": raws, "probe": probe,
        }
        self._clear_bandwidth_caches(mode)
        self._on_bandwidth_slider_changed(self.bandwidth_slider.value(), auto_generate=False)
        pair_note = f"，{len(curves)} 组配对" if mode == "attribute" else ""
        self.bw_status.setText(
            f"已生成 {len(bandwidths)} 个带宽快照{pair_note}，拖动滑块查看地图变化")
        self.statusMessage.emit(result.get("message", "带宽快照已生成"))

    def _on_bandwidth_slider_changed(self, value, auto_generate=True):
        mode = self._current_mode()
        self._bw_slider_values[mode] = value
        self.bandwidth_value.setText(f"{value}%")
        snapshots = self._bandwidth_snapshots.get(mode)
        index = self._bandwidth_index(value, mode) if snapshots else None
        converted = getattr(self, "bw_converted", None)
        if converted is not None:
            # 已有快照时显示该档真正跑过的带宽，避免与换算估计值对不上
            converted.setText(self._format_bandwidth(snapshots["bandwidths"][index])
                              if index is not None else self._bandwidth_percent_label(value))
        if index is None:
            # 尚未生成快照：拖动即自动触发一次预计算
            if (not snapshots and auto_generate
                    and not getattr(self, "_bandwidth_generating", False)):
                self._run_bandwidth_snapshots()
            return
        bandwidths = snapshots.get("bandwidths", [])
        self.statusMessage.emit(f"带宽 {value}% ≈ {bandwidths[index]:,}")
        self._update_metric_line(index)
        self._update_bandwidth_legend(index)
        self._set_bandwidth_map(index)

    def _bandwidth_index(self, percent, mode=None):
        """滑块百分比 → 快照下标（滑块走百分比，快照按实际带宽存）。"""
        mode = mode or self._current_mode()
        snapshots = self._bandwidth_snapshots.get(mode)
        if not snapshots:
            return None
        percents = snapshots.get("percents", [])
        if not percents:
            return None
        # 滑块百分比通常落在两个取值之间，取最近的一档
        return min(range(len(percents)), key=lambda i: abs(percents[i] - percent))

    def _bw_pair(self, mode=None):
        """带宽探索当前查看的配对键。

        栅格 / 几何模式没有配对概念，统一用空串做键，这样「按配对取曲线」的逻辑
        对三种模式是同一条路径；属性模式下若快照里没有当前配对（例如刚改过字段
        选择还没重新生成），退回快照里的第一组。
        """
        mode = mode or self._current_mode()
        snapshots = self._bandwidth_snapshots.get(mode)
        if mode != "attribute":
            return ""
        key = self._current_pair()
        if snapshots and key in (snapshots.get("curves") or {}):
            return key
        keys = list((snapshots.get("curves") or {}).keys()) if snapshots else []
        return keys[0] if keys else key

    def _bw_curve(self, mode=None):
        """当前配对在每条带宽上的指标曲线点。"""
        mode = mode or self._current_mode()
        snapshots = self._bandwidth_snapshots.get(mode) or {}
        return (snapshots.get("curves") or {}).get(self._bw_pair(mode), [])

    def _bw_raw(self, mode=None):
        """当前配对的逐要素序列：指标名 → [每条带宽一个逐要素列表]。"""
        mode = mode or self._current_mode()
        snapshots = self._bandwidth_snapshots.get(mode) or {}
        return (snapshots.get("raw") or {}).get(self._bw_pair(mode), {})

    def _bw_cache_key(self, field):
        """带宽配色的缓存键。配对不同值也不同，必须进键，否则切配对会串色。"""
        return (self._current_mode(), self._bw_pair(), field)

    def _update_metric_line(self, index):
        mode = self._current_mode()
        curve = self._bw_curve(mode)
        if not (0 <= index < len(curve)):
            return
        item = curve[index]

        def fmt(key, digits):
            value = item.get(key)
            if value is None:
                return "—"
            try:
                text = f"{float(value):.{digits}f}"
            except (TypeError, ValueError):
                text = str(value)
            return f"<b style='color:#1f695e'>{text}</b>"

        if mode == "raster":
            parts = [
                f"MAE {fmt('mae', 4)}",
                f"RMSE {fmt('rmse', 4)}",
                f"相关 {fmt('correlation', 4)}",
                f"局部 R² 中位数 {fmt('local_r2_median', 4)}",
                f"局部 MAE 中位数 {fmt('local_mae_median', 4)}",
            ]
            best = self._best_bandwidth()
            if best is not None:
                parts.append(f"推荐窗口（RMSE 最小）<b style='color:#e78338'>{best}</b>")
        elif mode == "geometry":
            parts = [
                f"GW IoU 中位数 {fmt('gw_iou_median', 4)}",
                f"GW 面积 MAE 中位数 {fmt('gw_area_mae_median', 4)}",
                f"GW 质心距离中位数 {fmt('gw_centroid_median', 1)} m",
                f"GW RMSE 中位数 {fmt('gw_rmse_median', 4)}",
            ]
            best = self._best_bandwidth()
            if best is not None:
                parts.append(f"推荐带宽（GW IoU 最高）<b style='color:#e78338'>{best}</b> m")
        else:
            parts = [
                f"AICc {fmt('aicc', 1)}",
                f"全局 R² {fmt('r2', 4)}",
                f"局部 R² 中位数 {fmt('local_r2_median', 4)}",
                f"残差 RMSE {fmt('residual_rmse', 3)}",
            ]
            best = self._best_bandwidth()
            if best is not None:
                parts.append(f"最佳带宽（AICc 最小）<b style='color:#e78338'>{best}</b>")
        self.bw_metrics_label.setText("　·　".join(parts))

    def _best_bandwidth(self):
        mode = self._current_mode()
        curve = self._bw_curve(mode)
        key, higher_better = {
            "attribute": ("aicc", False),
            "raster": ("rmse", False),
            "geometry": ("gw_iou_median", True),
        }.get(mode, ("aicc", False))
        best, best_value = None, None
        for item in curve:
            value = item.get(key)
            if value is None:
                continue
            if best_value is None or (value > best_value if higher_better else value < best_value):
                best_value, best = value, item.get("bandwidth")
        return best

    def _update_bandwidth_legend(self, index):
        legend_layout = getattr(self, "bw_legend_layout", None)
        if legend_layout is None:
            return
        field = self._bw_field()
        self._colors_for(field)  # 确保配色/图例缓存已计算
        clear_layout(legend_layout)
        entries = self._bandwidth_legend_cache.get(self._bw_cache_key(field), [])
        if not (0 <= index < len(entries)):
            return
        labels, colors = entries[index]
        if not labels or len(colors) < len(labels):
            return
        hint = QLabel("图例")
        hint.setObjectName("Muted")
        legend_layout.addWidget(hint)
        for i, text in enumerate(labels[:_LEGEND_MAX_ITEMS]):
            swatch = QLabel(" ")
            swatch.setFixedSize(18, 14)
            swatch.setStyleSheet(f"background: {colors[i]}; border: 1px solid #cbd5d2; border-radius: 2px;")
            legend_layout.addWidget(swatch)
            label = QLabel(text)
            label.setObjectName("Muted")
            legend_layout.addWidget(label)
        legend_layout.addStretch()

    def _bw_field(self):
        """当前模式在带宽探索中着色的指标字段。"""
        mode = self._current_mode()
        if mode == "raster":
            return "local_mae"
        if mode == "geometry":
            return "gw_iou"
        return _BANDWIDTH_FIELD_MAP.get(self.symbology_field_combo.currentText(), "local_r2")

    def _colors_for(self, field):
        """返回某展示参数在每个带宽下的逐要素配色（惰性计算并缓存）。

        缓存键含配对：同一个指标字段在不同配对下是两套完全不同的值。
        """
        mode = self._current_mode()
        key = self._bw_cache_key(field)
        if key not in self._bandwidth_color_cache:
            snapshots = self._bandwidth_snapshots.get(mode)
            raw = self._bw_raw(mode).get(field, [])
            n_bands = len((snapshots or {}).get("bandwidths", []))
            if not raw:
                self._bandwidth_color_cache[key] = [[]] * n_bands
                self._bandwidth_legend_cache[key] = [([], [])] * n_bands
            elif mode == "raster":
                entries = [self._build_raster_legend(vals) for vals in raw]
                self._bandwidth_color_cache[key] = [entry[0] for entry in entries]
                self._bandwidth_legend_cache[key] = [(entry[1], entry[2]) for entry in entries]
            elif mode == "geometry":
                entries = [self._build_geometry_colors(entry) for entry in raw]
                self._bandwidth_color_cache[key] = [entry[0] for entry in entries]
                self._bandwidth_legend_cache[key] = [(entry[1], entry[2]) for entry in entries]
            else:
                entries = [self._build_feature_colors(vals) for vals in raw]
                self._bandwidth_color_cache[key] = [entry[0] for entry in entries]
                self._bandwidth_legend_cache[key] = [(entry[1], entry[2]) for entry in entries]
        return self._bandwidth_color_cache[key]

    def _on_bandwidth_field_changed(self, *_):
        """设色字段 / 分级方法 / 分级数变化后，重算当前模式的带宽配色。"""
        mode = self._current_mode()
        if not self._bandwidth_snapshots.get(mode):
            return
        self._clear_bandwidth_caches(mode)
        index = self._bandwidth_index(self.bandwidth_slider.value(), mode)
        if index is not None:
            self._update_bandwidth_legend(index)
            self._set_bandwidth_map(index)

    def _set_bandwidth_map(self, index):
        mode = self._current_mode()
        if mode == "raster":
            # 栅格模式：直接切换地图底图为该窗口的局部 MAE 预览栅格
            snapshots = self._bandwidth_snapshots.get(mode)
            previews = (snapshots or {}).get("raw", {}).get("previews", [])
            if index < len(previews) and previews[index]:
                self.map_canvas.load_raster(previews[index])
            return
        colors = self._colors_for(self._bw_field())
        self.map_canvas.set_feature_colors(colors[index])

    def _build_feature_colors(self, values):
        """把一档带宽的展示参数按「分层设色」相同的方法分级并映射为每要素填充色（缺失为 None）。"""
        labels, indices, colors = self._classify_series(values)
        nc = len(labels)
        if nc <= 0:
            return [], [], []
        feature_colors = [None] * len(indices)
        for i, cls in enumerate(indices):
            if cls is not None and 0 <= cls < nc:
                feature_colors[i] = QColor(colors[cls])
        return feature_colors, labels, colors

    def _build_raster_legend(self, values):
        """把一档窗口的局部指标（降采样网格值）分级，生成灰度图例（与地图灰度预览一致：高值更亮）。"""
        labels, _indices, _colors = self._classify_series(values)
        nc = len(labels)
        if nc <= 0:
            return None, [], []
        colors = []
        for i in range(nc):
            tone = round(60 + 175 * i / max(nc - 1, 1))
            colors.append(f"#{tone:02x}{tone:02x}{tone:02x}")
        return None, labels, colors

    def _build_geometry_colors(self, entry):
        """把一档带宽的 GW 面 IoU 按 source_id 对齐到地图要素，返回配色/图例。"""
        source_ids = entry.get("source_ids") or []
        values = entry.get("values") or []
        labels, indices, colors = self._classify_series(values)
        nc = len(labels)
        if nc <= 0:
            return [], [], []
        n_features = len(getattr(self.map_canvas, "shapes", []))
        feature_colors = [None] * n_features
        for feature_id, cls in zip(source_ids, indices):
            if cls is not None and 0 <= cls < nc and 0 <= feature_id < n_features:
                feature_colors[feature_id] = QColor(colors[cls])
        return feature_colors, labels, colors

    def update_result(self, result: AnalysisResult, shp_path=None):
        self.set_run_busy(False)
        self.latest_result = result
        if shp_path:
            # 结果 SHP 不可用时退回读源数据，这里记下它
            self._source_shp_path = shp_path
        if self._current_mode() == "geometry":
            if result.status == "error":
                self.geometry_validation_label.setText("计算失败：" + result.message)
                self.geometry_validation_label.setStyleSheet(
                    "padding: 7px; color: #a23b32; background: #fdecea; border-radius: 4px;"
                )
            else:
                self.geometry_validation_label.setText(result.message)
                self.geometry_validation_label.setStyleSheet(
                    "padding: 7px; color: #1f695e; background: #e3f3ef; border-radius: 4px;"
                )
        # 多字段运行：配对下拉按本次结果的配对重建
        if result.pairs:
            self._refresh_pair_options()
        self._result_output_shp = getattr(result, "output_shp", "") or ""
        # 内容判断而非模式判断：栅格 / 几何结果既没有结果 SHP 也没有结果列，
        # 不能把属性表顶到前台盖掉它们各自的展示。
        if result.status == "success" and (self.primary_result_shp() or result.local_columns):
            self._show_results(self._source_shp_path, result.local_columns,
                               result_shp=self.primary_result_shp())
            self.tabs.setCurrentIndex(1)
        self.statusMessage.emit(result.message)

    def update_after_data_change(self):
        self._refresh_raster_options()
        if hasattr(self, "geometry_a_combo"):
            self._refresh_geometry_sources()
