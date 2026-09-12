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
                app.setFont(QFont(families[0], 10))
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
