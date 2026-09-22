"""共享 UI 组件。"""
from .map_canvas import MapCanvas
from .raster_swipe_canvas import RasterSwipeCanvas
from .swipe_canvas import SwipeCanvas
from .swipe_layers import build_raster_layer, build_vector_layer, vector_crs, vector_fields
from .scatter_canvas import ScatterCanvas
from .histogram_canvas import HistogramCanvas
from .chart_window import ChartWindow
from .metric_card import MetricCard
from .panels import panel_box, page_heading, clear_layout
from .data_select import DataSelectDialog, DataSelectionPanel
from .attribute_table import AttributeTableModel, DroppableTableView, columns_from_rows

__all__ = [
    "MapCanvas",
    "RasterSwipeCanvas",
    "SwipeCanvas",
    "build_raster_layer",
    "build_vector_layer",
    "vector_crs",
    "vector_fields",
    "ScatterCanvas",
    "HistogramCanvas",
    "ChartWindow",
    "MetricCard",
    "panel_box",
    "page_heading",
    "clear_layout",
    "DataSelectDialog",
    "DataSelectionPanel",
    "AttributeTableModel",
    "DroppableTableView",
    "columns_from_rows",
]
