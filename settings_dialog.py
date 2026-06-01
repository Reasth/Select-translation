from __future__ import annotations

from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
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


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("翻译助手 - 设置")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        # ---- 翻译引擎选择 ----
        layout.addWidget(self._section_label("翻译引擎"))
        engine_row = QWidget()
        engine_layout = QVBoxLayout(engine_row)
        engine_layout.setContentsMargins(0, 0, 0, 0)
        engine_layout.setSpacing(2)
        self.radio_hosted = QRadioButton("默认 · 内置 MiniMax 大模型（免费、无需配置）")
        self.radio_free = QRadioButton("公共免费翻译（Google，非 AI、断网兜底）")
        self.radio_ai = QRadioButton("自带 AI 大模型（DeepSeek / OpenAI / Ollama …，需自填 Key）")
        self.engine_group = QButtonGroup(self)
        self.engine_group.addButton(self.radio_hosted)
        self.engine_group.addButton(self.radio_free)
        self.engine_group.addButton(self.radio_ai)
        engine_layout.addWidget(self.radio_hosted)
        engine_layout.addWidget(self.radio_free)
        engine_layout.addWidget(self.radio_ai)
        layout.addWidget(engine_row)

        self.engine_note = QLabel()
        self.engine_note.setWordWrap(True)
        self.engine_note.setStyleSheet("color:#6b7280; font-size:12px; margin:2px 0 6px 0;")
        layout.addWidget(self.engine_note)

        # ---- AI 大模型专属字段（仅 AI 档显示）----
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
        layout.addWidget(self.ai_box)

        # ---- 通用字段 ----
        common_form = QFormLayout()
        self.target_lang_edit = QLineEdit(cfg.target_lang)
        common_form.addRow("目标语言", self.target_lang_edit)
        layout.addLayout(common_form)

        # ---- 按钮 ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.test_button = QPushButton("测试连接")
        buttons.addButton(self.test_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.test_button.clicked.connect(self._on_test_connection)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # ---- 初始状态 ----
        engine = cfg.engine if cfg.engine in {"hosted", "free", "ai"} else "hosted"
        self.radio_hosted.setChecked(engine == "hosted")
        self.radio_free.setChecked(engine == "free")
        self.radio_ai.setChecked(engine == "ai")
        self.radio_hosted.toggled.connect(self._on_engine_changed)
        self.radio_free.toggled.connect(self._on_engine_changed)
        self.radio_ai.toggled.connect(self._on_engine_changed)
        self._on_engine_changed()

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
                "适合彻底不想走作者代理的场景，或作为完全离线 AI 时的非 AI 兜底。"
            )
        else:
            self.engine_note.setText(
                "用自己的 Key 调任意 OpenAI 兼容服务（DeepSeek / 通义千问 / 智谱 / Kimi / OpenAI / Ollama）。"
                "质量与计费完全在你手里。"
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
            target_lang=self.target_lang_edit.text().strip() or "中文",
            source_lang=self.cfg.source_lang,
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
