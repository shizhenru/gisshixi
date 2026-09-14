"""共享的 UI 构建工具：面板容器、页头、布局清理。"""
from ..qt_compat import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    Qt,
)


def clear_layout(layout):
    """递归清空一个布局（含嵌套布局），并删除其中控件的引用。"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget:
            widget.deleteLater()
        elif child_layout:
            clear_layout(child_layout)


def panel_box(kicker: str, title: str, right_text: str = "", scrollable: bool = False):
    """返回 (panel_frame, body_layout)：带标题栏和分隔线的白色面板。

    scrollable=True 时，body 会被包进一个 QScrollArea（用于收纳较长的参数面板）。
    """
    frame = QFrame()
    frame.setObjectName("Panel")
    root = QVBoxLayout(frame)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    header = QHBoxLayout()
    header.setContentsMargins(18, 14, 18, 12)
    labels = QVBoxLayout()
    labels.setSpacing(3)
    kicker_label = QLabel(kicker)
    kicker_label.setObjectName("Kicker")
    title_label = QLabel(title)
    title_label.setObjectName("PanelTitle")
    labels.addWidget(kicker_label)
    labels.addWidget(title_label)
    header.addLayout(labels)
    header.addStretch()
    if right_text:
        right = QLabel(right_text)
        right.setObjectName("Muted")
        header.addWidget(right)
    root.addLayout(header)
    separator = QFrame()
    separator.setFrameShape(QFrame.Shape.HLine)
    separator.setStyleSheet("color: #edf1f1;")
    root.addWidget(separator)
    body = QVBoxLayout()
    body.setContentsMargins(18, 12, 18, 17)
    body.setSpacing(10)
    if scrollable:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content.setLayout(body)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
    else:
        root.addLayout(body)
    return frame, body


def page_heading(kicker: str, title: str, description: str, action_text: str = ""):
    """返回 (heading_layout, action_button)：页面顶部标题行，可带一个动作按钮。"""
    wrapper = QHBoxLayout()
    wrapper.setContentsMargins(0, 0, 0, 12)
    titles = QVBoxLayout()
    titles.setSpacing(4)
    kicker_label = QLabel(kicker)
    kicker_label.setObjectName("Kicker")
    title_label = QLabel(title)
    title_label.setObjectName("PageTitle")
    description_label = QLabel(description)
    description_label.setObjectName("Muted")
    titles.addWidget(kicker_label)
    titles.addWidget(title_label)
    titles.addWidget(description_label)
    wrapper.addLayout(titles)
    wrapper.addStretch()
    action = None
    if action_text:
        action = QPushButton(action_text)
        action.setObjectName("PrimaryButton")
        action.setMinimumWidth(118)
        wrapper.addWidget(action, alignment=Qt.AlignmentFlag.AlignBottom)
    return wrapper, action
