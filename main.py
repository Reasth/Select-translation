from __future__ import annotations

import logging
import sys
import traceback

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import QApplication

from config import CONFIG_DIR, Config
from floating_icon import FloatingIcon
from llm_client import LLMClient
from selection_monitor import SelectionMonitor, grab_selected_text, is_foreground_terminal
from settings_dialog import SettingsDialog
from translation_popup import TranslationPopup
from tray import TrayController


LOG_PATH = CONFIG_DIR / "app.log"


def _install_logging() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH),
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )

    def _excepthook(exc_type, exc, tb):
        logging.error("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = _excepthook


class App:
    def __init__(self):
        self.cfg = Config.load()
        self.client = LLMClient(self.cfg)

        self.icon = FloatingIcon()
        self.popup = TranslationPopup(self.client)
        self.monitor = SelectionMonitor()
        self.tray = TrayController(enabled=self.cfg.enabled)
        self._suppress_next_close: bool = False
        self._cached_selection_text: str = ""

        self.monitor.selection_finished.connect(self._on_selection_finished)
        self.monitor.mouse_pressed.connect(self._on_mouse_pressed)
        self.icon.clicked.connect(self._on_icon_clicked)
        self.tray.toggle_enabled.connect(self._on_toggle_enabled)
        self.tray.open_settings.connect(self._on_open_settings)
        self.tray.quit_app.connect(QApplication.instance().quit)

        if self.cfg.enabled:
            self.monitor.start()

        if not self.cfg.api_key:
            self.tray.notify(
                "翻译助手已启动",
                "首次使用请右键托盘图标 → 设置，填写 API Key。",
            )

    def _on_toggle_enabled(self, on: bool):
        self.cfg.enabled = on
        self.cfg.save()
        if on:
            self.monitor.start()
        else:
            self.monitor.stop()
            self.icon.hide()
            self._cached_selection_text = ""

    def _on_open_settings(self):
        dlg = SettingsDialog(self.cfg)
        if dlg.exec():
            dlg.apply_to(self.cfg)
            self.client.cfg = self.cfg

    def _on_mouse_pressed(self):
        QTimer.singleShot(0, self._maybe_hide_icon)

    def _maybe_hide_icon(self):
        if self._suppress_next_close:
            self._suppress_next_close = False
            return
        if self.popup.isVisible():
            if not self.popup.contains_global_point(QCursor.pos()):
                self.popup.hide()
            return
        if self.icon.isVisible():
            if self.icon.contains_global_point(QCursor.pos()):
                return
            self.icon.hide()
            self._cached_selection_text = ""

    def _on_selection_finished(self, press_x: int, press_y: int, release_x: int, release_y: int):
        if not self.cfg.enabled:
            return
        right_x = max(press_x, release_x)
        top_y = min(press_y, release_y)
        ratio = QGuiApplication.primaryScreen().devicePixelRatio() or 1.0
        lx = int(right_x / ratio)
        ly = int(top_y / ratio)
        self._cached_selection_text = ""
        self.icon.show_near_cursor(lx, ly, lifetime_ms=self.cfg.show_icon_ms)
        if is_foreground_terminal():
            logging.info("skip eager selection cache for terminal foreground window")
        else:
            QTimer.singleShot(80, self._cache_selected_text)

    def _cache_selected_text(self):
        text = grab_selected_text(timeout_ms=300, restore_clipboard=True)
        if text:
            self._cached_selection_text = text
            logging.info("cached selected text len=%s", len(text))

    def _on_icon_clicked(self):
        self._suppress_next_close = True
        bubble_anchor = self.icon.dot_center_global()
        text = self._cached_selection_text or grab_selected_text()
        logging.info("icon clicked, selected text len=%s cached=%s", len(text), bool(self._cached_selection_text))
        if len(text) < self.cfg.min_chars or len(text) > self.cfg.max_chars:
            self.popup.show_message("未获取到选中文本，请重新划词后再点圆点。")
            self.popup.reveal_at(anchor=bubble_anchor)
            return
        self._cached_selection_text = ""
        self.popup.start_translation(text)
        self.popup.reveal_at(anchor=bubble_anchor)


def main():
    _install_logging()
    logging.info("translate-popup starting, log=%s", LOG_PATH)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    holder = App()
    logging.info("event loop entering")
    code = app.exec()
    logging.info("event loop exited with code=%s", code)
    sys.exit(code)


if __name__ == "__main__":
    main()
