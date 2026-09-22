APP_STYLE = """
QMainWindow, QWidget {
    background: #f4f7f6;
    color: #26363c;
    font-family: "DengXian", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 12px;
}
QLabel {
    background: transparent;
}
QTabWidget::pane, QTabBar {
    background: transparent;
}
QTabBar::tab {
    color: #52666b;
    background: transparent;
    border: 0;
    padding: 7px 12px;
}
QTabBar::tab:selected {
    color: #1f695e;
    background: #e3f3ef;
}
QFrame#TopBar {
    background: #ffffff;
    border-bottom: 1px solid #dfe8e6;
}
QFrame#Sidebar {
    background: #eaf3f0;
    border-right: 1px solid #dce7e4;
}
QFrame#Panel, QGroupBox#Panel {
    background: #ffffff;
    border: 1px solid #dfe8e6;
    border-radius: 8px;
}
QGroupBox#Panel {
    margin-top: 10px;
    padding-top: 18px;
}
QGroupBox#Panel::title {
    subcontrol-origin: margin;
    left: 18px;
    padding: 0 5px;
    color: #718188;
    font-size: 10px;
    font-weight: 700;
}
QLabel#BrandTitle {
    color: #26363c;
    font-size: 17px;
    font-weight: 700;
}
QLabel#BrandSubtitle, QLabel#Muted {
    color: #7b8b8e;
    font-size: 10px;
}
QLabel#PanelNote {
    color: #7b8b8e;
    font-size: 10px;
}
QLabel#Kicker {
    color: #2d8c7c;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
/* 表单字段名：比 Muted 更实一点，避免整列看着发灰 */
QLabel#FieldLabel {
    color: #5d7176;
    font-size: 11px;
    font-weight: 600;
}
QLabel#PageTitle {
    color: #26363c;
    font-size: 26px;
    font-weight: 700;
}
QLabel#PanelTitle {
    color: #26363c;
    font-size: 13px;
    font-weight: 700;
}
QLabel#ProjectName {
    color: #26363c;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#NavButton {
    min-height: 39px;
    padding: 0 12px;
    color: #68807b;
    background: transparent;
    border: 0;
    border-radius: 7px;
    text-align: left;
}
QPushButton#NavButton:hover {
    background: #e2efeb;
    color: #1e655b;
}
QPushButton#NavButton[active="true"] {
    background: #d6ece6;
    color: #1e655b;
    font-weight: 700;
}
QPushButton#PrimaryButton {
    min-height: 36px;
    padding: 0 15px;
    color: #ffffff;
    background: #2d8c7c;
    border: 0;
    border-radius: 6px;
    font-weight: 700;
}
QPushButton#PrimaryButton:hover { background: #1f695e; }
QPushButton#OutlineButton {
    min-height: 34px;
    padding: 0 13px;
    color: #2d7066;
    background: #ffffff;
    border: 1px solid #b7d5ce;
    border-radius: 5px;
}
QPushButton#OutlineButton:hover { background: #eef8f5; }
QPushButton#GhostButton {
    color: #718589;
    background: transparent;
    border: 0;
}
QPushButton#GhostButton:hover { color: #2d8c7c; }
QComboBox, QLineEdit, QDoubleSpinBox, QSpinBox {
    min-height: 32px;
    padding: 0 10px;
    color: #405155;
    background: #fbfcfc;
    border: 1px solid #dfe8e6;
    border-radius: 6px;
}
QComboBox {
    padding-right: 28px;
}
QComboBox:hover {
    border: 1px solid #b7d5ce;
}
QComboBox:focus, QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {
    border: 1px solid #72b9aa;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border: none;
}
QComboBox::down-arrow {
    image: url(app/assets/chevron-down.svg);
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #26363c;
    border: 1px solid #dfe8e6;
    border-radius: 6px;
    padding: 4px;
    selection-background-color: #e3f3ef;
    selection-color: #1f695e;
    outline: none;
}
QComboBox QAbstractItemView::item {
    color: #26363c;
    background: #ffffff;
    padding: 5px 8px;
}
QComboBox QAbstractItemView::item:selected {
    color: #1f695e;
    background: #e3f3ef;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #d9e9e5;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 12px;
    margin: -4px 0;
    background: #2d8c7c;
    border: 2px solid #ffffff;
    border-radius: 7px;
}
QCheckBox { spacing: 8px; color: #607276; }
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #cbdad7;
    border-radius: 3px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #2d8c7c;
    border-color: #2d8c7c;
}
QTableWidget {
    background: #ffffff;
    border: 0;
    gridline-color: #edf1f1;
    selection-background-color: #e3f3ef;
    selection-color: #1f695e;
}
QHeaderView::section {
    padding: 10px 8px;
    color: #849295;
    background: #f8fafa;
    border: 0;
    border-bottom: 1px solid #dfe8e6;
    font-size: 10px;
    font-weight: 700;
}
QTextEdit {
    padding: 12px;
    color: #68797b;
    background: #fbfcfb;
    border: 1px solid #e5ecea;
    border-radius: 5px;
    line-height: 1.5;
}
QProgressBar {
    min-height: 5px;
    max-height: 5px;
    background: #dfece9;
    border: 0;
    border-radius: 3px;
}
QProgressBar::chunk { background: #2d8c7c; border-radius: 3px; }
QScrollArea { border: 0; background: transparent; }
"""
