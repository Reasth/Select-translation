from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#3b82f6"))
    p.setPen(QColor(0, 0, 0, 0))
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QColor("white"))
    f = QFont()
    f.setPointSize(30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), 0x84, "译")  # AlignCenter
    p.end()
    return QIcon(pm)


class TrayController(QObject):
    toggle_enabled = pyqtSignal(bool)
    open_settings = pyqtSignal()
    quit_app = pyqtSignal()

    def __init__(self, enabled: bool):
        super().__init__()
        self.icon = QSystemTrayIcon(make_icon(), self)
        self.icon.setToolTip("翻译助手 - 选中文本即可翻译")

        self.menu = QMenu()
        self.enable_action = QAction("启用", self.menu, checkable=True)
        self.enable_action.setChecked(enabled)
        self.enable_action.toggled.connect(self.toggle_enabled.emit)
        self.menu.addAction(self.enable_action)

        self.settings_action = QAction("设置…", self.menu)
        self.settings_action.triggered.connect(self.open_settings.emit)
        self.menu.addAction(self.settings_action)

        self.menu.addSeparator()
        self.quit_action = QAction("退出", self.menu)
        self.quit_action.triggered.connect(self.quit_app.emit)
        self.menu.addAction(self.quit_action)

        self.icon.setContextMenu(self.menu)
        self.icon.show()

    def notify(self, title: str, body: str) -> None:
        self.icon.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 3000)
