from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config import Config, normalize_base_url
from llm_client import check_connection


PRESETS = {
    "MiniMax": ("https://api.minimaxi.com/v1", "MiniMax-M2.7-highspeed"),
    "DeepSeek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "通义千问 (DashScope)": (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-turbo",
    ),
    "智谱 GLM": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    "Moonshot Kimi": ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "Ollama 本地": ("http://localhost:11434/v1", "qwen2.5:7b"),
    "自定义": ("", ""),
}

COMMON_LANGS = [
    "中文",
    "English",
    "日本語",
    "한국어",
    "Français",
    "Deutsch",
    "Español",
    "Português",
    "Русский",
    "العربية",
    "Tiếng Việt",
    "ไทย",
]


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Select — 设置")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ---- 首屏：只剩目标语言 ----
        common_form = QFormLayout()
        common_form.setContentsMargins(0, 0, 0, 0)
        self.target_lang_combo = QComboBox()
        self.target_lang_combo.setEditable(True)
        self.target_lang_combo.addItems(COMMON_LANGS)
        self.target_lang_combo.setCurrentText(cfg.target_lang or "中文")
        self.target_lang_combo.setToolTip("回答始终使用此语言；外文会先翻译再解释，本语言原文会直接解释含义。")
        common_form.addRow("目标语言", self.target_lang_combo)
        layout.addLayout(common_form)

        # ---- 高级折叠 ----
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("▸ 高级设置（翻译引擎、自带 Key）")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setStyleSheet(
            "QToolButton { border: none; color: #6b7280; font-size: 12px; padding: 4px 0; }"
        )
        self.advanced_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.advanced_toggle.toggled.connect(self._on_advanced_toggled)
        layout.addWidget(self.advanced_toggle)

        self.advanced_panel = QWidget()
        self.advanced_panel.setVisible(False)
        adv_layout = QVBoxLayout(self.advanced_panel)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(6)

        # 引擎选择
        adv_layout.addWidget(self._section_label("翻译引擎"))
        self.radio_hosted = QRadioButton("默认 · 内置 MiniMax 大模型（免费、无需配置）")
        self.radio_free = QRadioButton("公共免费翻译（Google，非 AI、断网兜底）")
        self.radio_ai = QRadioButton("自带 AI 大模型（DeepSeek / OpenAI …，需自填 Key）")
        self.engine_group = QButtonGroup(self)
        for r in (self.radio_hosted, self.radio_free, self.radio_ai):
            self.engine_group.addButton(r)
            adv_layout.addWidget(r)

        self.engine_note = QLabel()
        self.engine_note.setWordWrap(True)
        self.engine_note.setStyleSheet("color:#6b7280; font-size:12px; margin:2px 0 6px 0;")
        adv_layout.addWidget(self.engine_note)

        # AI 字段
        self.ai_box = QWidget()
        ai_form = QFormLayout(self.ai_box)
        ai_form.setContentsMargins(0, 0, 0, 0)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self._on_preset)
        ai_form.addRow("服务商", self.preset_combo)
        self.base_url_edit = QLineEdit(normalize_base_url(cfg.base_url))
        self.base_url_edit.setPlaceholderText("https://api.example.com/v1")
        ai_form.addRow("Base URL", self.base_url_edit)
        self.api_key_edit = QLineEdit(cfg.api_key)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        ai_form.addRow("API Key", self.api_key_edit)
        self.model_edit = QLineEdit(cfg.model)
        ai_form.addRow("模型", self.model_edit)
        adv_layout.addWidget(self.ai_box)

        # 测试连接按钮（只放在高级区里）
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self._on_test_connection)
        adv_layout.addWidget(self.test_button)

        layout.addWidget(self.advanced_panel)

        # 分隔
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#e5e7eb;")
        layout.addWidget(sep)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # 初始状态
        engine = cfg.engine if cfg.engine in {"hosted", "free", "ai"} else "hosted"
        self.radio_hosted.setChecked(engine == "hosted")
        self.radio_free.setChecked(engine == "free")
        self.radio_ai.setChecked(engine == "ai")
        for r in (self.radio_hosted, self.radio_free, self.radio_ai):
            r.toggled.connect(self._on_engine_changed)
        self._on_engine_changed()

        # 非默认引擎自动展开「高级」，让用户立刻看到自己配置的位置
        if engine != "hosted":
            self.advanced_toggle.setChecked(True)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight:600; margin-top:2px;")
        return label

    def _current_engine(self) -> str:
        if self.radio_hosted.isChecked():
            return "hosted"
        if self.radio_free.isChecked():
            return "free"
        return "ai"

    def _on_advanced_toggled(self, on: bool):
        self.advanced_panel.setVisible(on)
        self.advanced_toggle.setText(
            ("▾ " if on else "▸ ") + "高级设置（翻译引擎、自带 Key）"
        )
        self.adjustSize()

    def _on_engine_changed(self):
        engine = self._current_engine()
        self.ai_box.setVisible(engine == "ai")
        if engine == "hosted":
            self.engine_note.setText(
                "已为你预付费 MiniMax M2.7-highspeed —— 选中文本即时出译文，无需注册、无需 Key。"
                "代理失效时自动降级到 Google 免费翻译，保证「打开就能用」。"
            )
        elif engine == "free":
            self.engine_note.setText(
                "公共免费翻译端点（Google），无需 AI、网络好就能用。"
                "适合不想走作者代理的场景。"
            )
        else:
            self.engine_note.setText(
                "用自己的 Key 调任意 OpenAI 兼容服务（DeepSeek / 通义千问 / 智谱 / Kimi / OpenAI / Ollama）。"
            )
        self.adjustSize()

    def _on_preset(self, name: str):
        base, model = PRESETS.get(name, ("", ""))
        if base:
            self.base_url_edit.setText(base)
        if model:
            self.model_edit.setText(model)

    def _build_config_from_form(self) -> Config:
        return Config(
            engine=self._current_engine(),
            base_url=normalize_base_url(self.base_url_edit.text()),
            api_key=self.api_key_edit.text().strip(),
            model=self.model_edit.text().strip(),
            target_lang=self.target_lang_combo.currentText().strip() or "中文",
            enabled=self.cfg.enabled,
            autostart=self.cfg.autostart,
            show_icon_ms=self.cfg.show_icon_ms,
            min_chars=self.cfg.min_chars,
            max_chars=self.cfg.max_chars,
            system_prompt=self.cfg.system_prompt,
        )

    def _on_test_connection(self):
        self.test_button.setEnabled(False)
        self.test_button.setText("测试中...")
        try:
            result = check_connection(self._build_config_from_form())
        finally:
            self.test_button.setEnabled(True)
            self.test_button.setText("测试连接")

        if result.ok:
            QMessageBox.information(self, "测试连接", result.message)
        else:
            QMessageBox.warning(self, "测试连接失败", result.message)

    def apply_to(self, cfg: Config) -> None:
        form_cfg = self._build_config_from_form()
        cfg.engine = form_cfg.engine
        cfg.base_url = form_cfg.base_url
        cfg.api_key = form_cfg.api_key
        cfg.model = form_cfg.model
        cfg.target_lang = form_cfg.target_lang
        cfg.save()
