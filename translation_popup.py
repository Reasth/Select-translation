from __future__ import annotations

import logging

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPainterPath,
    QShortcut,
)
from PyQt6.QtWidgets import QLabel, QWidget

from llm_client import LLMClient


class TranslateWorker(QThread):
    token_received = pyqtSignal(str)
    finished_translation = pyqtSignal()

    def __init__(self, client: LLMClient, text: str, source: str = "click"):
        super().__init__()
        self.client = client
        self.text = text
        self.source = source  # 走到代理端会变成 X-Source header,用于区分 eager/click

    def run(self):
        for token in self.client.stream_translate(self.text, source=self.source):
            if self.isInterruptionRequested():
                break
            self.token_received.emit(token)
        self.finished_translation.emit()


class BubbleFrame(QWidget):
    TAIL_W = 8
    RADIUS = 12

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.TAIL_W, 1, self.width() - self.TAIL_W - 1, self.height() - 2)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        tail_y = min(24, max(16, self.height() // 2))
        tail = QPainterPath()
        tail.moveTo(self.TAIL_W + 1, tail_y - 6)
        tail.lineTo(1, tail_y)
        tail.lineTo(self.TAIL_W + 1, tail_y + 6)
        tail.closeSubpath()
        path = path.united(tail)

        p.setPen(QColor("#d9dee7"))
        p.setBrush(QColor("#ffffff"))
        p.drawPath(path)


class LoadingDots(QWidget):
    def __init__(self):
        super().__init__()
        self._phase = 0
        self.setFixedSize(34, 12)
        self._timer = QTimer(self)
        self._timer.setInterval(220)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._phase = 0
        self._timer.start()
        self.show()
        self.update()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._phase = (self._phase + 1) % 3
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(3):
            active = i == self._phase
            radius = 3.5 if active else 2.6
            color = QColor("#3b82f6" if active else "#9ca3af")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            cx = 5 + i * 11
            cy = self.height() / 2
            p.drawEllipse(QPointF(cx, cy), radius, radius)


class TranslationPopup(QWidget):
    MAX_TEXT_WIDTH = 320
    MIN_BUBBLE_WIDTH = 54
    PAD_H = 12
    PAD_V = 8
    SHADOW_PAD = 10

    closed = pyqtSignal()  # 隐藏（关闭）时发出 → 上层据此取消 eager worker

    def __init__(self, client: LLMClient):
        super().__init__()
        self.client = client
        self._worker: TranslateWorker | None = None
        self._drag_offset: QPoint | None = None
        self._buffer: str = ""

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.card = BubbleFrame()
        self.card.setParent(self)
        self.result_label = QLabel("", self.card)
        self.result_label.setStyleSheet(
            "QLabel { background: transparent; color: #111827; font-size: 13px; }"
        )
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.result_label.setContentsMargins(0, 0, 0, 0)
        self.result_label.setMargin(0)
        self.result_label.setIndent(0)

        self.loading = LoadingDots()
        self.loading.setParent(self.card)

        self.card.mousePressEvent = self._card_press
        self.card.mouseMoveEvent = self._card_move

        self._show_loading()
        QShortcut(QKeySequence("Esc"), self, activated=self.hide)

    def _card_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _card_move(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def start_translation(self, text: str) -> None:
        self.cancel_translation()
        self._buffer = ""
        self.result_label.setText("")
        self._show_loading()

        self._worker = TranslateWorker(self.client, text)
        self._worker.token_received.connect(self._on_token)
        self._worker.finished_translation.connect(self._on_worker_finished)
        self._worker.start()

    def show_message(self, message: str) -> None:
        self.cancel_translation()
        self._buffer = message
        self.loading.stop()
        self.result_label.show()
        self.result_label.setText(message)
        self._resize_to_text()

    def cancel_translation(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.quit()
            self._worker.wait(50)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self.loading.stop()

    def reveal_at(self, anchor: QPoint | None = None) -> None:
        self._position_near(anchor)
        self.show()
        self.raise_()

    def present_eager(self, buffer: str) -> None:
        """以一段 eager 已收的 buffer 起头展示;后续 token 由上层 append_eager_token 推。"""
        self.cancel_translation()  # 清掉任何内部 worker
        self._buffer = buffer
        if buffer:
            self.loading.stop()
            self.result_label.show()
            self.result_label.setText(buffer)
            self._resize_to_text()
        else:
            self._show_loading()

    def append_eager_token(self, token: str) -> None:
        """上层 eager worker 触发的新 token 转发进来。复用 _on_token 处理 loading→text 切换。"""
        self._on_token(token)

    def mark_eager_done(self) -> None:
        """Eager 流结束。如果缓冲还空说明真没拿到内容,显示提示。"""
        self.loading.stop()
        if not self._buffer:
            self.show_message("未收到翻译内容。")

    def hideEvent(self, event):
        super().hideEvent(event)
        self.closed.emit()

    def _on_token(self, token: str):
        if not self._buffer:
            self.loading.stop()
            self.result_label.show()
        self._buffer += token
        self.result_label.setText(self._buffer)
        self._resize_to_text()

    def _show_loading(self):
        self.result_label.hide()
        content_w = self.loading.width()
        content_h = self.loading.height()
        bubble_w = self.MIN_BUBBLE_WIDTH
        bubble_h = content_h + self.PAD_V * 2
        card_w = BubbleFrame.TAIL_W + bubble_w
        card_h = bubble_h
        self._set_shell_size(card_w, card_h)
        self.loading.move(BubbleFrame.TAIL_W + (bubble_w - content_w) // 2, self.PAD_V)
        self.loading.start()

    def _resize_to_text(self):
        text = self.result_label.text() or " "
        fm = self.result_label.fontMetrics()
        longest_line = max((fm.horizontalAdvance(line) for line in text.splitlines()), default=20)
        text_w = min(self.MAX_TEXT_WIDTH, max(20, longest_line))
        rect = fm.boundingRect(QRect(0, 0, text_w, 10000), Qt.TextFlag.TextWordWrap, text)
        text_h = max(rect.height(), fm.height())

        bubble_w = max(self.MIN_BUBBLE_WIDTH, text_w + self.PAD_H * 2)
        bubble_h = text_h + self.PAD_V * 2
        card_w = BubbleFrame.TAIL_W + bubble_w
        card_h = bubble_h

        self._set_shell_size(card_w, card_h)
        self.result_label.setFixedSize(text_w, text_h)
        self.result_label.move(BubbleFrame.TAIL_W + self.PAD_H, self.PAD_V)

    def _set_shell_size(self, card_w: int, card_h: int):
        self.card.setGeometry(self.SHADOW_PAD, self.SHADOW_PAD, card_w, card_h)
        self.setFixedSize(card_w + self.SHADOW_PAD * 2, card_h + self.SHADOW_PAD * 2)

    def _on_worker_finished(self):
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if not self._buffer:
            self.loading.stop()
            self.show_message("未收到翻译内容。")
        logging.info(
            "popup geometry: widget=%dx%d card=%dx%d text=%dx%d loading=%s",
            self.width(),
            self.height(),
            self.card.width(),
            self.card.height(),
            self.result_label.width(),
            self.result_label.height(),
            self.loading.isVisible(),
        )

    def _position_near(self, anchor: QPoint | None):
        if anchor is None:
            anchor = QCursor.pos()
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        w = self.width()
        h = self.height()
        sp = self.SHADOW_PAD
        tail_tip_x = sp + 1
        tail_tip_y = sp + min(24, max(16, self.card.height() // 2))
        x = anchor.x() - tail_tip_x
        y = anchor.y() - tail_tip_y
        if x + w > avail.right():
            x = avail.right() - w
        if y + h > avail.bottom():
            y = avail.bottom() - h
        x = max(avail.left(), min(x, avail.right() - w))
        y = max(avail.top(), min(y, avail.bottom() - h))
        self.move(x, y)

    def contains_global_point(self, gp: QPoint) -> bool:
        tl = self.card.mapToGlobal(QPoint(0, 0))
        return (
            tl.x() <= gp.x() <= tl.x() + self.card.width()
            and tl.y() <= gp.y() <= tl.y() + self.card.height()
        )
