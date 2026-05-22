# 翻译助手 (Translate Popup)

一个轻量的 Windows 桌面工具：在**任何应用**里选中文本，光标旁会出现一个 **译** 小图标，点击即用大模型流式翻译。

> 灵感与对标：[openai-translator](https://github.com/openai-translator/openai-translator)。
> 主要差异：openai-translator 是"选中 → 按快捷键 → 弹窗"；本项目是"选中 → 光标旁出小图标 → 点击翻译"，更接近网易有道词典 / Bob 风格。

## 特性

- 全局划词：监听鼠标拖选，自动抓取选中文本
- 跟随光标：在选区附近显示小图标，点击触发翻译
- 流式输出：token 实时追加显示
- OpenAI 兼容协议：DeepSeek、通义千问 (DashScope)、智谱 GLM、Moonshot、OpenAI、Ollama 本地等任意兼容服务
- 系统托盘：暂停/启用、设置、退出
- 配置持久化：`~/.translate-popup/config.json`

## 安装

```powershell
cd E:\jingtong\projects\translate
python -m pip install -r requirements.txt
python main.py
```

## 首次配置

启动后右键托盘 **译** 图标 → **设置**：

| 字段 | 示例 |
|---|---|
| 服务商 | DeepSeek |
| Base URL | `https://api.deepseek.com/v1` |
| API Key | `sk-...` |
| 模型 | `deepseek-chat` |
| 目标语言 | 中文 |

预设里也有通义千问、智谱、Moonshot、OpenAI、Ollama 本地等，切换预设会自动填好 Base URL 和模型名。

## 使用

1. 在任意应用（浏览器、PDF 阅读器、记事本、IDE…）里**拖动选中**一段文本
2. 光标右下方出现蓝色 **译** 图标
3. 点击图标 → 弹出翻译卡片，流式渲染译文
4. 按 `Esc` 或点击 `×` 关闭，或点 **复制** 复制结果

> 单击鼠标（没有拖动）不会触发，避免误判。

## 已知限制

- 某些应用（PDF Reader / 部分游戏 / 沙箱里的应用）`Ctrl+C` 拿不到选中文本，这是系统层限制
- 触发方式依赖模拟 `Ctrl+C` + 读剪贴板，会瞬间替换剪贴板再恢复（200ms 内）
- Windows 下表现最完整；macOS / Linux 未测试

## 项目结构

```
translate/
├── main.py                # 入口，串起所有模块
├── config.py              # 配置加载/保存
├── llm_client.py          # OpenAI 兼容协议 + 流式
├── selection_monitor.py   # 全局鼠标监听 + 抓取选中文本
├── floating_icon.py       # 跟随光标的小图标
├── translation_popup.py   # 翻译结果卡片
├── settings_dialog.py     # 设置对话框
├── tray.py                # 系统托盘
└── requirements.txt
```

## 打包成 exe

```powershell
python -m pip install pyinstaller
pyinstaller --noconfirm --windowed --onefile --name TranslatePopup main.py
```

产物在 `dist/TranslatePopup.exe`。
