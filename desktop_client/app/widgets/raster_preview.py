"""栅格预览读取：把单波段栅格降采样为显示用 QImage，供拉帘画布与小地图共用。

读取统一放到后台线程，避免超大栅格在 UI 线程整幅解码导致客户端卡死。
"""
from pathlib import Path

from ..qt_compat import QImage, QObject, Signal, Slot

_RASTER_SUFFIXES = {".tif", ".tiff", ".img", ".asc"}


def is_raster_path(path) -> bool:
    return Path(path).suffix.lower() in _RASTER_SUFFIXES


def read_raster_preview(path, max_dim: int = 2048):
    """读取单波段栅格并降采样为显示用 QImage，返回 (QImage, bounds, value_range)。

    bounds 为 (left, bottom, right, top)；value_range 为 (low, high)，即灰度拉伸所用的
    2~98 百分位数值区间，用于在界面上提示各栅格的实际取值范围。失败抛 ValueError（中文提示）。
    """
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling

    raster_path = Path(path)
    if not raster_path.exists():
        raise ValueError(f"栅格文件不存在：{raster_path.name}")
    try:
        with rasterio.open(raster_path) as ds:
            if ds.count != 1:
                raise ValueError(f"栅格必须是单波段：{raster_path.name}")
            # 只按显示分辨率降采样读取，避免整幅高分辨率栅格载入内存。
            scale = min(1.0, max_dim / max(ds.width, ds.height))
            out_shape = (
                max(1, int(round(ds.height * scale))),
                max(1, int(round(ds.width * scale))),
            )
            values = ds.read(1, out_shape=out_shape, masked=True, resampling=Resampling.average)
            data = np.asarray(values.astype("float32").filled(np.nan), dtype="float32")
            valid = np.isfinite(data) & ~np.asarray(values.mask, dtype=bool)
            if not valid.any():
                raise ValueError(f"栅格没有有效像元：{raster_path.name}")
            low, high = np.nanpercentile(data[valid], [2, 98])
            if high <= low:
                low = float(np.nanmin(data[valid]))
                high = float(np.nanmax(data[valid]))
            if high <= low:
                high = low + 1.0
            normalized = np.nan_to_num((data - low) / (high - low), nan=0.0, posinf=1.0, neginf=0.0)
            intensity = np.clip(normalized * 255, 0, 255).astype("uint8")
            alpha = np.where(valid, 255, 0).astype("uint8")
            rgba = np.empty((data.shape[0], data.shape[1], 4), dtype="uint8")
            rgba[..., 0] = intensity
            rgba[..., 1] = intensity
            rgba[..., 2] = intensity
            rgba[..., 3] = alpha
            image = QImage(
                rgba.data,
                rgba.shape[1],
                rgba.shape[0],
                rgba.strides[0],
                QImage.Format.Format_RGBA8888,
            ).copy()
            b = ds.bounds
            return image, (b.left, b.bottom, b.right, b.top), (float(low), float(high))
    except ValueError:
        raise
    except ImportError as exc:
        raise ValueError("缺少 rasterio 或 numpy，无法显示栅格影像") from exc
    except Exception as exc:  # noqa: BLE001 - 读取失败不应拖垮界面
        raise ValueError(f"栅格打开失败：{raster_path.name}（{exc}）") from exc


class RasterLoadWorker(QObject):
    """后台线程读取单幅栅格预览。"""

    finished = Signal(object)  # 发送 dict: {"image": QImage, "bounds": tuple|None, "error": str}

    def __init__(self, path, max_dim: int = 2048):
        super().__init__()
        self._path = path
        self._max_dim = max_dim

    @Slot()
    def run(self):
        try:
            image, bounds, value_range = read_raster_preview(self._path, self._max_dim)
            self.finished.emit({"image": image, "bounds": bounds, "range": value_range, "error": ""})
        except Exception as exc:  # noqa: BLE001
            self.finished.emit({"image": QImage(), "bounds": None, "range": None, "error": str(exc)})
