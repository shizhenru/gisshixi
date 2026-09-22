"""矢量（SHP）加载：把几何解析与属性读取放到后台线程，避免大图层阻塞界面。

与 raster_preview.RasterLoadWorker 同构：工作线程只做纯数据读取，不碰 Qt 对象，
结果通过信号回主线程，由界面侧再构建 QPolygonF / 刷新面板。
"""
from core.io.readers import read_attributes, read_shapefile_geometry

from ..qt_compat import QObject, Signal, Slot


class VectorLoadWorker(QObject):
    """后台线程读取 SHP 的几何与属性表。

    finished 携带 seq（请求序号），供界面侧丢弃被后续请求取代的过期结果。
    """

    finished = Signal(int, str, object, str)  # (seq, path, payload|None, error)

    def __init__(self, seq, path, max_records):
        super().__init__()
        self._seq = seq
        self._path = path
        self._max_records = max_records

    @Slot()
    def run(self):
        try:
            # 几何与属性按同一上限读取，保证值数组与渲染出的要素一一对应。
            geometry = read_shapefile_geometry(self._path, max_records=self._max_records)
            if not geometry["geometries"]:
                self.finished.emit(self._seq, self._path, None,
                                   "未能解析 SHP 几何（可能是不支持的几何类型）")
                return
            attrs = read_attributes(self._path, limit=self._max_records)
            self.finished.emit(self._seq, self._path,
                               {"geometry": geometry, "attrs": attrs}, "")
        except Exception as exc:  # noqa: BLE001 - 读取失败以错误文本回传
            self.finished.emit(self._seq, self._path, None, str(exc))
