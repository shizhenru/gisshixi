from math import hypot

from .qt_compat import (
    QColor,
    QBrush,
    QFrame,
    QPainter,
    QPen,
    QPolygonF,
    QPointF,
    QRectF,
    QSizePolicy,
    Qt,
    Signal,
    QVBoxLayout,
    QLabel,
    QWidget,
)


class MapCanvas(QWidget):
    """Lightweight schematic map placeholder. Replace with a real GIS canvas later."""

    selectedChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.selected_index = 17
        self.points = [
            (0.12, 0.21), (0.18, 0.34), (0.24, 0.26), (0.31, 0.43), (0.39, 0.25),
            (0.45, 0.50), (0.54, 0.35), (0.60, 0.57), (0.68, 0.44), (0.74, 0.63),
            (0.83, 0.74), (0.38, 0.72), (0.50, 0.78), (0.66, 0.25), (0.79, 0.38),
            (0.28, 0.59), (0.56, 0.69), (0.72, 0.82), (0.89, 0.30), (0.92, 0.65),
        ]
        self.colors = ["#2d8c7c", "#e6a05d", "#2d8c7c", "#d86659", "#2d8c7c"] * 4

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor("#dce9e4"), 1))
        painter.setBrush(QBrush(QColor("#eef5f1")))
        painter.drawRoundedRect(rect, 6, 6)
        x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()

        painter.setPen(QPen(QColor("#dce8e2"), 1))
        for x in range(x1 + 28, x2, 38):
            painter.drawLine(x, y1, x, y2)
        for y in range(y1 + 28, y2, 38):
            painter.drawLine(x1, y, x2, y)

        river = [
            QPointF(x1, y1 + .34 * rect.height()),
            QPointF(x1 + .16 * rect.width(), y1 + .25 * rect.height()),
            QPointF(x1 + .29 * rect.width(), y1 + .47 * rect.height()),
            QPointF(x1 + .45 * rect.width(), y1 + .31 * rect.height()),
            QPointF(x1 + .63 * rect.width(), y1 + .25 * rect.height()),
            QPointF(x1 + .76 * rect.width(), y1 + .39 * rect.height()),
            QPointF(x2, y1 + .48 * rect.height()),
            QPointF(x2, y1 + .70 * rect.height()),
            QPointF(x1 + .78 * rect.width(), y2),
            QPointF(x1 + .48 * rect.width(), y2),
            QPointF(x1 + .34 * rect.width(), y1 + .61 * rect.height()),
            QPointF(x1 + .18 * rect.width(), y1 + .53 * rect.height()),
            QPointF(x1, y1 + .48 * rect.height()),
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#c6e6e5")))
        painter.drawPolygon(QPolygonF(river))

        road_pen = QPen(QColor("#ffffff"), 2)
        road_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(road_pen)
        roads = [
            [(x1 + 18, y1 + 25), (x1 + 130, y1 + 112), (x1 + 285, y1 + 165), (x2 - 18, y2 - 25)],
            [(x1 + 45, y2 - 12), (x1 + 175, y1 + 180), (x1 + 320, y1 + 92), (x2 - 16, y1 + 28)],
            [(x1 + 12, y1 + 195), (x1 + 145, y1 + 183), (x1 + 285, y1 + 102), (x2 - 20, y1 + 138)],
        ]
        for road in roads:
            painter.drawPolyline(QPolygonF([QPointF(*point) for point in road]))

        painter.setPen(QPen(QColor("#d5e2dd"), 1))
        for road in [
            [(x1 + 4, y1 + 62), (x1 + 120, y1 + 135), (x1 + 260, y1 + 124), (x2 - 6, y1 + 220)],
            [(x1 + 70, y2 - 8), (x1 + 170, y1 + 132), (x1 + 305, y1 + 143), (x2 - 15, y1 + 77)],
        ]:
            painter.drawPolyline(QPolygonF([QPointF(*point) for point in road]))

        for index, (px, py) in enumerate(self.points):
            cx = x1 + px * rect.width()
            cy = y1 + py * rect.height()
            radius = 7 if index == self.selected_index else 4
            color = QColor(self.colors[index % len(self.colors)])
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPointF(cx, cy), radius, radius)
            if index == self.selected_index:
                painter.setPen(QPen(QColor("#d86659"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), radius + 4, radius + 4)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        rect = self.rect().adjusted(1, 1, -1, -1)
        nearest = None
        nearest_distance = 24.0
        for index, (px, py) in enumerate(self.points):
            cx = rect.left() + px * rect.width()
            cy = rect.top() + py * rect.height()
            distance = hypot(event.position().x() - cx, event.position().y() - cy)
            if distance < nearest_distance:
                nearest = index
                nearest_distance = distance
        if nearest is not None:
            self.selected_index = nearest
            self.selectedChanged.emit(nearest)
            self.update()


class MetricCard(QFrame):
    def __init__(self, title, value, note, accent="#2d8c7c", parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 13)
        title_label = QLabel(title)
        title_label.setObjectName("Muted")
        value_label = QLabel(value)
        value_label.setStyleSheet(f"color: {accent}; font-size: 23px; font-weight: 700;")
        note_label = QLabel(note)
        note_label.setObjectName("Muted")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(note_label)
