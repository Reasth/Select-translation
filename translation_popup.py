from __future__ import annotations

import logging

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPainterPath,
    QShortcut,
)
from PyQt6.QtWidgets import QLabel, QFrame, QTextBrowser, QWidget

from llm_client import LLMClient
from terminal_context import extract_claude_suggestion


class TranslateWorker(QThread):
    token_received = pyqtSignal(str)
    finished_translation = pyqtSignal()

    def __init__(self, client: LLMClient, text: str, source: str = "click", terminal: bool = False):
        super().__init__()
        self.client = client
        self.text = text
        self.source = source  # 走到代理端会变成 X-Source header,用于区分 eager/click
        self.terminal = terminal  # 终端(Claude Code)场景:走终端专用 prompt
        # QThread 必须在 run() 真正返回后再析构,否则 Qt 喊 qFatal → fast-fail
        # 0xc0000409 P9=7。让线程自己接 finished→deleteLater,外部一律不再直接 delete。
        self.finished.connect(self.deleteLater)

    def run(self):
        try:
            for token in self.client.stream_translate(self.text, source=self.source, terminal=self.terminal):
                if self.isInterruptionRequested():
                    break
                self.token_received.emit(token)
        except Exception as e:  # noqa: BLE001 - surface unexpected worker failures in the popup
            logging.exception("translation worker crashed")
            if not self.isInterruptionRequested():
                self.token_received.emit(f"[翻译失败：{e}]")
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
    # 终端(Claude Code)场景:报错解释带「严重度 + 建议」,内容比普通释义长,放宽到 420。
    TERMINAL_MAX_TEXT_WIDTH = 420
    MIN_BUBBLE_WIDTH = 54
    PAD_H = 12
    PAD_V = 8
    SHADOW_PAD = 10

    closed = pyqtSignal()  # 隐藏（关闭）时发出 → 上层据此取消 eager worker
    suggestion_copied = pyqtSignal()  # 用户点了「复制给 Claude」→ 上层打点

    def __init__(self, client: LLMClient):
        super().__init__()
        self.client = client
        self._worker: TranslateWorker | None = None
        self._drag_offset: QPoint | None = None
        self._buffer: str = ""
        self._terminal: bool = False
        self._max_text_width: int = self.MAX_TEXT_WIDTH
        self._claude_suggestion: str = ""
        self._anchor: QPoint | None = None

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
        self.result_label = QTextBrowser(self.card)
        self.result_label.setStyleSheet(
            "QTextBrowser { background: transparent; color: #111827; font-size: 13px; border: none; }"
            "QTextBrowser > QWidget { background: transparent; }"
        )
        self.result_label.setReadOnly(True)
        self.result_label.setOpenExternalLinks(False)
        self.result_label.setOpenLinks(False)
        self.result_label.setFrameShape(QFrame.Shape.NoFrame)
        self.result_label.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.result_label.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.result_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.result_label.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.result_label.setContentsMargins(0, 0, 0, 0)
        self.result_label.document().setDocumentMargin(0)
        self.result_label.document().setDefaultStyleSheet(
            "body { margin: 0; color: #111827; font-size: 13px; }"
            "p { margin: 0 0 6px 0; }"
            "ul, ol { margin-top: 0; margin-bottom: 6px; padding-left: 18px; }"
            "li { margin: 0 0 2px 0; }"
            "pre { margin: 4px 0; padding: 6px; background: #f3f4f6; border: 1px solid #e5e7eb; }"
            "code { font-family: Consolas, 'Cascadia Mono', monospace; background: #f3f4f6; }"
            "h1, h2, h3 { margin: 0 0 6px 0; font-weight: 600; }"
        )
        self.result_label.hide()

        self.loading = LoadingDots()
        self.loading.setParent(self.card)

        # 终端场景报错回答里的「👉 建议」一键复制入口。平时隐藏,worker 收尾时检测到
        # 建议行才显示——纯 QLabel,零新依赖。
        self.copy_label = QLabel("📋 复制给 Claude", self.card)
        self.copy_label.setStyleSheet(
            "QLabel { background: transparent; color: #2563eb; font-size: 12px; }"
        )
        self.copy_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_label.hide()
        self.copy_label.mousePressEvent = self._copy_label_press

        self.card.mousePressEvent = self._card_press
        self.card.mouseMoveEvent = self._card_move

        self._show_loading()
        QShortcut(QKeySequence("Esc"), self, activated=self.hide)

    def _card_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _card_move(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._anchor = None
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def _copy_label_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._claude_suggestion:
            QGuiApplication.clipboard().setText(self._claude_suggestion)
            self.copy_label.setText("✓ 已复制，粘贴给 Claude 即可")
            self._resize_to_text()
            self.suggestion_copied.emit()

    def _set_terminal_mode(self, terminal: bool) -> None:
        self._terminal = terminal
        self._max_text_width = self.TERMINAL_MAX_TEXT_WIDTH if terminal else self.MAX_TEXT_WIDTH
        self._claude_suggestion = ""
        self.copy_label.setText("📋 复制给 Claude")
        self.copy_label.hide()

    def _set_result_plain(self, text: str) -> None:
        self.result_label.setPlainText(text)

    def _set_result_markdown(self, text: str) -> None:
        self.result_label.setMarkdown(text)

    def start_translation(self, text: str, *, terminal: bool = False) -> None:
        self.cancel_translation()
        self._set_terminal_mode(terminal)
        self._buffer = ""
        self._set_result_plain("")
        self.result_label.hide()
        self._show_loading()

        self._worker = TranslateWorker(self.client, text, terminal=terminal)
        self._worker.token_received.connect(self._on_token)
        self._worker.finished_translation.connect(self._on_worker_finished)
        self._worker.start()

    def show_message(self, message: str) -> None:
        self.cancel_translation()
        self._set_terminal_mode(False)
        self._buffer = message
        self.loading.stop()
        self.result_label.show()
        self._set_result_plain(message)
        self._resize_to_text()

    def cancel_translation(self) -> None:
        # 不调 deleteLater:worker.finished 已自接 deleteLater,run() 真正退出后自毁。
        # 直接 delete 还在跑的 QThread 会触发 fast-fail 0xc0000409。
        if self._worker is not None:
            try:
                if self._worker.isRunning():
                    self._worker.requestInterruption()
            except RuntimeError:
                pass
            self._worker = None
        self.loading.stop()

    def reveal_at(self, anchor: QPoint | None = None) -> None:
        self._anchor = anchor or QCursor.pos()
        self._position_near(self._anchor)
        self.show()
        self.raise_()

    def show_loading_state(self) -> None:
        """只把 popup 摆到 loading 形态,不起 worker——用于「点击 → 先盖住 → 后台抓 → 翻译」
        这条流程的第一步,让用户在 Ctrl+Shift+C 真发出去之前先看到 popup,选区被宿主
        清掉的瞬间被 popup 弹出遮蔽。"""
        self.cancel_translation()
        self._set_terminal_mode(False)
        self._buffer = ""
        self._set_result_plain("")
        self.result_label.hide()
        self._show_loading()

    def present_eager(self, buffer: str) -> None:
        """以一段 eager 已收的 buffer 起头展示;后续 token 由上层 append_eager_token 推。"""
        self.cancel_translation()  # 清掉任何内部 worker
        self._set_terminal_mode(False)  # eager 只在非终端场景起,宽度/按钮回到默认
        self._buffer = buffer
        if buffer:
            self.loading.stop()
            self.result_label.show()
            self._set_result_markdown(buffer)
            self._resize_to_text()
        else:
            self._show_loading()

    def append_eager_token(self, token: str) -> None:
        """上层 eager worker 触发的新 token 转发进来。复用 _on_token 处理 loading→text 切换。"""
        self._append_token(token)

    def mark_eager_done(self) -> None:
        """Eager 流结束。如果缓冲还空说明真没拿到内容,显示提示。"""
        self.loading.stop()
        if not self._buffer:
            self.show_message("未收到翻译内容。")

    def hideEvent(self, event):
        super().hideEvent(event)
        self.closed.emit()

    def _on_token(self, token: str):
        if self.sender() is not self._worker:
            return
        self._append_token(token)

    def _append_token(self, token: str):
        if not self._buffer:
            self.loading.stop()
            self.result_label.show()
        self._buffer += token
        self._set_result_markdown(self._buffer)
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
        text = self.result_label.toPlainText() or " "
        fm = self.result_label.fontMetrics()
        screen_point = self._anchor or self.frameGeometry().center() or QCursor.pos()
        screen = QGuiApplication.screenAt(screen_point) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        max_content_w = max(
            self.MIN_BUBBLE_WIDTH,
            avail.width() - self.SHADOW_PAD * 2 - BubbleFrame.TAIL_W - self.PAD_H * 2,
        )
        max_text_w = max(20, min(self._max_text_width, max_content_w))

        longest_line = max((fm.horizontalAdvance(line) for line in text.splitlines()), default=20)
        doc_text_w = min(max_text_w, max(20, longest_line))
        doc = self.result_label.document()
        doc.setDocumentMargin(0)
        doc.setTextWidth(doc_text_w)
        full_text_h = max(int(doc.size().height() + 0.999), fm.height())

        copy_h = 0
        copy_w = 0
        if not self.copy_label.isHidden():
            self.copy_label.adjustSize()
            copy_h = self.copy_label.height() + 6
            copy_w = self.copy_label.width()

        max_text_h = max(
            fm.height(),
            avail.height() - self.SHADOW_PAD * 2 - self.PAD_V * 2 - copy_h,
        )
        visible_text_h = min(full_text_h, max_text_h)
        needs_scroll = full_text_h > visible_text_h
        scrollbar_w = self.result_label.verticalScrollBar().sizeHint().width() if needs_scroll else 0
        if needs_scroll and doc_text_w + scrollbar_w > max_content_w:
            doc_text_w = max(20, max_content_w - scrollbar_w)
            doc.setTextWidth(doc_text_w)
            full_text_h = max(int(doc.size().height() + 0.999), fm.height())
            visible_text_h = min(full_text_h, max_text_h)

        content_w = min(max_content_w, doc_text_w + scrollbar_w)
        bubble_w = max(self.MIN_BUBBLE_WIDTH, content_w, copy_w) + self.PAD_H * 2
        bubble_h = visible_text_h + copy_h + self.PAD_V * 2
        card_w = BubbleFrame.TAIL_W + bubble_w
        card_h = bubble_h

        self._set_shell_size(card_w, card_h)
        self.result_label.setFixedSize(content_w, visible_text_h)
        self.result_label.move(BubbleFrame.TAIL_W + self.PAD_H, self.PAD_V)
        if copy_h:
            self.copy_label.move(BubbleFrame.TAIL_W + self.PAD_H, self.PAD_V + visible_text_h + 6)

        if self.isVisible() and self._anchor is not None:
            self._position_near(self._anchor)

    def _set_shell_size(self, card_w: int, card_h: int):
        self.card.setGeometry(self.SHADOW_PAD, self.SHADOW_PAD, card_w, card_h)
        self.setFixedSize(card_w + self.SHADOW_PAD * 2, card_h + self.SHADOW_PAD * 2)

    def _on_worker_finished(self):
        # worker 自己接了 finished→deleteLater,这里只清引用。
        if self.sender() is not self._worker:
            return
        self._worker = None
        if not self._buffer:
            self.loading.stop()
            self.show_message("未收到翻译内容。")
        elif self._terminal:
            # 终端场景:回答里有「👉 建议」行(报错的修复请求)就亮出一键复制入口。
            suggestion = extract_claude_suggestion(self._buffer)
            if suggestion:
                self._claude_suggestion = suggestion
                self.copy_label.show()
                self._resize_to_text()
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
