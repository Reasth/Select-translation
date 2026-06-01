from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget


class FloatingIcon(QWidget):
    """选中文本后在鼠标位置右上方显示的彩色小圆点。点击时再触发抓取+翻译。"""

    clicked = pyqtSignal()
    auto_hidden = pyqtSignal()  # 超时自动隐藏（≠ 用户点击触发的 hide）→ 上层据此取消 eager 请求

    SIZE = 16
    DOT_SIZE = 9
    COLOR = "#3b82f6"

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(QSize(self.SIZE, self.SIZE))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.hide)
        self._auto_hide.timeout.connect(self.auto_hidden.emit)

    def show_near_cursor(self, anchor_x: int, anchor_y: int, lifetime_ms: int = 4000) -> None:
        """贴着选区右上角 (anchor_x, anchor_y) 的右上方显示。坐标应为 Qt 逻辑坐标。"""
        gap_x = 4
        gap_y = self.SIZE + 4
        pos = QPoint(anchor_x + gap_x, anchor_y - gap_y)
        self.move(pos)
        self.show()
        self._auto_hide.start(lifetime_ms)

    def contains_global_point(self, gp: QPoint) -> bool:
        top_left = self.mapToGlobal(QPoint(0, 0))
        return (
            top_left.x() <= gp.x() <= top_left.x() + self.width()
            and top_left.y() <= gp.y() <= top_left.y() + self.height()
        )

    def dot_center_global(self) -> QPoint:
        pad = (self.SIZE - self.DOT_SIZE) // 2
        center = QPoint(pad + self.DOT_SIZE // 2, pad + self.DOT_SIZE // 2)
        return self.mapToGlobal(center)

    def enterEvent(self, event):
        self._auto_hide.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        # hover 后离开圆点 = 不打算点 → 极短缓冲后立即消失（避免鼠标抖动误关）
        self._auto_hide.start(200)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.hide()
            self._auto_hide.stop()
            # main 收到 clicked 时再去 grab 当前选中文本
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(self.COLOR))
        p.setPen(Qt.PenStyle.NoPen)
        pad = (self.SIZE - self.DOT_SIZE) // 2
        p.drawEllipse(pad, pad, self.DOT_SIZE, self.DOT_SIZE)
