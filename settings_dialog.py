from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from config import Config, normalize_base_url
from llm_client import check_connection


PRESETS = {
    "MiniMax": ("https://api.minimaxi.com/v1", "MiniMax-M2.1"),
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
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self._on_preset)
        form.addRow("服务商", self.preset_combo)

        self.base_url_edit = QLineEdit(normalize_base_url(cfg.base_url))
        self.base_url_edit.setPlaceholderText("https://api.example.com/v1")
        form.addRow("Base URL", self.base_url_edit)

        self.api_key_edit = QLineEdit(cfg.api_key)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        form.addRow("API Key", self.api_key_edit)

        self.model_edit = QLineEdit(cfg.model)
        form.addRow("模型", self.model_edit)

        self.target_lang_edit = QLineEdit(cfg.target_lang)
        form.addRow("目标语言", self.target_lang_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.test_button = QPushButton("测试连接")
        buttons.addButton(self.test_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.test_button.clicked.connect(self._on_test_connection)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_preset(self, name: str):
        base, model = PRESETS.get(name, ("", ""))
        if base:
            self.base_url_edit.setText(base)
        if model:
            self.model_edit.setText(model)

    def _build_config_from_form(self) -> Config:
        return Config(
            base_url=normalize_base_url(self.base_url_edit.text()),
            api_key=self.api_key_edit.text().strip(),
            model=self.model_edit.text().strip(),
            target_lang=self.target_lang_edit.text().strip() or "中文",
            source_lang=self.cfg.source_lang,
            enabled=self.cfg.enabled,
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
        cfg.base_url = form_cfg.base_url
        cfg.api_key = form_cfg.api_key
        cfg.model = form_cfg.model
        cfg.target_lang = form_cfg.target_lang
        cfg.save()
