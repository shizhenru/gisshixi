import os

# 本机装的 PostgreSQL/PostGIS 会把 PROJ_LIB / GDAL_DATA 指到它自带的 PROJ 数据上，
# 那份 proj.db 版本与 GDAL 内置的 PROJ 不兼容，会让 rasterio 解析任何 EPSG 码都失败
# （「proj.db contains DATABASE.LAYOUT.VERSION.MINOR = 2 whereas >= 6 is expected」）。
# rasterio 自带的 PROJ 数据才是匹配版本，故在导入它之前清掉这两个继承来的变量。
for _var in ("PROJ_LIB", "GDAL_DATA"):
    os.environ.pop(_var, None)

from app.main_window import SpatialValidationWindow
from pathlib import Path

from app.qt_compat import QApplication, QFont, QFontDatabase


def load_chinese_font(app):
    """Use a system font file explicitly when Qt does not auto-discover Windows fonts."""
    candidates = [
        Path.home() / "AppData/Local/Microsoft/Windows/Fonts/Deng.ttf",
        Path(r"C:\Windows\Fonts\Deng.ttf"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            font_id = QFontDatabase.addApplicationFont(str(candidate))
            families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
            if families:
                font = QFont(families[0])
                font.setPixelSize(13)
                app.setFont(font)
                return families[0]
    return ""


def main():
    app = QApplication([])
    app.setApplicationName("空间数据交叉验证工作台")
    app.setOrganizationName("GIS 综合实习")
    load_chinese_font(app)
    window = SpatialValidationWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
