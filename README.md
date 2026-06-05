# Select — 选中即懂

一个**真·轻量**的桌面划词翻译工具（**Windows / macOS**）：在**任何应用**里选中文本，光标旁会冒出一个 **译** 小蓝点，点一下立刻出 AI 译文。

> **打开即用，无需 API Key、无需注册** —— 默认就用作者代付的 **MiniMax M2.7-highspeed** 大模型（OpenAI 兼容代理，部署在 Vercel），代理失效时自动降级到 Google 免费翻译，保证「打开就能用」。
> 想要彻底自费、自由换模型？一键切到「自带 AI 大模型」，接 DeepSeek / 通义千问 / 智谱 / Kimi / OpenAI / Ollama 等任意 OpenAI 兼容服务。

> 灵感与对标：[openai-translator](https://github.com/openai-translator/openai-translator)。
> 主要差异：openai-translator 是"选中 → 按快捷键 → 弹窗"；本项目是"选中 → 光标旁出小图标 → 点击翻译"，更接近网易有道词典 / Bob 风格。

## ⬇️ 下载即用（普通用户，无需 Python）

不想碰命令行？直接下载安装包，双击就能用：

| 版本 | 下载 | 适合 |
|---|---|---|
| **安装版（推荐）** | [**TranslatePopup-Setup.exe**](https://github.com/horton2048/Select-translation/releases/latest/download/TranslatePopup-Setup.exe) | 普通用户。双击一路「下一步」，自动建桌面/开始菜单图标 |
| 免安装单文件 | [TranslatePopup.exe](https://github.com/horton2048/Select-translation/releases/latest/download/TranslatePopup.exe) | 喜欢绿色版，下载后直接双击运行 |

> 📦 全部版本在 [**Releases 页**](https://github.com/horton2048/Select-translation/releases/latest)。
> ✅ 打开即用：**无需 API Key、无需注册**，默认走作者代付的 AI 大模型，失效自动降级 Google 免费翻译。
> ⚠️ 首次运行若被 Windows SmartScreen 拦截，点「更多信息 → 仍要运行」即可（个人开发者未做数字签名，属正常提示，不影响使用）。

**三步上手**：① 任意应用里拖动选中文本 → ② 光标旁出现蓝色「译」圆点 → ③ 点圆点出译文。

## 它能帮你弄懂什么（典型场景）

不只是翻译——选中**任何看不懂的东西**，它都告诉你这是什么。下面是用户每天最常用它的几个时刻：

- **📖 读英文，撞到看不懂的词或句** —— 浏览器里读文档/新闻/论文，拖选一句英文，气泡里直接出中文。*这是大多数人装它的第一理由。*
- **🐛 终端/IDE 蹦出报错** —— 选中 `EADDRINUSE: address already in use :::3000`，气泡告诉你「3000 端口被占用 + 最可能的原因 + 怎么修」，而不是把报错原样翻一遍。
- **🔤 看到术语 / 缩写，字都认识就是不懂** —— 选中 `RAG`、`idempotent`、`p99`，气泡出「这是什么 + 一句大白话」，不是把它硬翻成奇怪的中文。
- **🌍 读到陌生的产品 / 公司 / 人名** —— 刷到「Mistral 又发新模型」，选中 `Mistral`，气泡告诉你「法国 AI 公司，开源模型起家……」。
- **💻 别人的代码 / 陌生 API 看不懂** —— 选中一段正则 `/^(?=.*\d).{8,}$/`，气泡解释「至少 8 位且含数字的密码校验」。
- **📄 一大段英文，懒得逐句读** —— 选中整段邮件或论文摘要，气泡出中文要点 TL;DR，而不是堆一大坨直译。
- **💬 聊天里的外语 / 网络黑话** —— Discord、社媒里的 `IIRC`、`skill issue`，选中即懂。

> 越用越顺手：它会**猜你这次想要哪种解释**；猜得不对，在原地**再划一次**就换个角度——用得越久越懂你。

## 卖点

- **零门槛**：默认内置 MiniMax M2.7-highspeed，普通用户什么都不用配，划词即出 AI 译文
- **作者代付 + 自动降级**：托管代理（你的 MiniMax 国内 token plan）失效时自动回退到 Google 免费翻译，断网外的任何故障都不会让用户卡住
- **真轻量**：HTTP 走标准库（去掉 httpx 整条依赖链），打包时只保留 3 个 Qt 模块，单文件实测约 35MB、UPX 压缩后约 32MB，远小于 PyQt6 默认 onefile 的 50–80MB
- **全局划词**：监听鼠标拖选，任意应用（浏览器、PDF、记事本、IDE…）通吃
- **跟随光标**：在选区附近显示小图标，点击才翻译，不打扰
- **流式输出**：MiniMax 的 token 实时追加显示，TTFT ~亚秒
- **可进可退**：三档引擎可切——托管 / 公共免费 / 自带 Key，互不影响
- **开机自启**：托盘一键勾选，开机即驻留
- **配置持久化**：`~/.translate-popup/config.json`

## 部署托管代理（仅作者/自托管者需要做一次）

代理是一个 ~80 行的 Vercel Edge 函数（`api/v1/chat/completions.mjs`），把客户端的 OpenAI 兼容请求转发到 `api.minimaxi.com`，并在服务端注入你的 MiniMax Key。

1. 在 Vercel 项目设置里加环境变量：`MINIMAX_API_KEY = <你的国内版 MiniMax Key>`
2. `vercel --prod` 部署
3. 客户端的 `HOSTED_PROXY_BASE_URL`（`config.py`）已指向稳定生产 URL，无需改

代理已经做了最小防护：白名单 MiniMax chat 模型、限制 `max_tokens`/输入长度、22s 上游超时（对齐 Vercel Hobby Edge 函数的 25s 上限）。如果担心被恶意刷量，未来可加 Vercel KV 做 IP 限频。

## 从源码运行（开发者）

> 普通用户请用上面的[「下载即用」](#️-下载即用普通用户无需-python)安装包，本节是给想改代码或自己打包的开发者。

### Windows

```powershell
cd E:\jingtong\projects\translate
python -m pip install -r requirements.txt
python main.py
```

### macOS

```bash
cd /path/to/translate
python3 -m pip install -r requirements.txt
python3 main.py
# 或双击 start_mac.command（首次：chmod +x start_mac.command）
```

> 同一套代码跑两个平台，平台差异只隔离在 `platform_win.py` / `platform_mac.py`。
> macOS 会自动多装一个 `pyobjc-framework-Cocoa`（用于读取前台应用）。

#### macOS 首次需授权（重要）

全局划词依赖系统级的鼠标监听和模拟按键，macOS 要求显式授权，否则圆点不出现或取不到文本：

1. **系统设置 → 隐私与安全性 → 辅助功能**：把运行程序的终端（Terminal / iTerm）或打包后的 App 勾上。
2. **系统设置 → 隐私与安全性 → 输入监控**：同样勾上。
3. 授权后**重启**程序生效。

## 翻译引擎（三档）

启动后右键托盘 **译** 图标 → **设置**，顶部选引擎：

### 1. 默认 · 内置 MiniMax 大模型（推荐，免费、无需配置）

什么都不用填。客户端把请求打到作者部署的 Vercel 代理，代理在服务端注入 Key，转发到 MiniMax 国内端点。Key 全程不离开服务端。代理不可用时自动降级到 Google 免费翻译。

### 2. 公共免费翻译（Google，非 AI）

直接打 Google 公开端点。无 AI、质量一般，适合"我连作者的代理都不想走"的极简场景。

### 3. 自带 AI 大模型（OpenAI 兼容）

切到此档后填写：

| 字段 | 示例 |
|---|---|
| 服务商 | DeepSeek |
| Base URL | `https://api.deepseek.com/v1` |
| API Key | `sk-...` |
| 模型 | `deepseek-chat` |
| 目标语言 | 中文 |

预设里有 MiniMax、DeepSeek、通义千问、智谱（`glm-4-flash` 免费）、Moonshot、OpenAI、Ollama 本地等，切换预设会自动填好 Base URL 和模型名。点「测试连接」可即时校验。

## 使用

1. 在任意应用里**拖动选中**一段文本
2. 光标右上方出现蓝色 **译** 圆点
3. 点击圆点 → 弹出翻译卡片，流式渲染译文
4. 按 `Esc` 或在别处单击关闭，卡片可拖动

> 单击鼠标（没有拖动）不会触发，避免误判。
> 中/日文本在目标语言为中文时会自动反向翻成英文，避免"翻了等于没翻"。

## 已知限制

- 某些应用（PDF Reader / 部分游戏 / 沙箱里的应用）复制键拿不到选中文本，这是系统层限制
- 触发方式依赖模拟复制键（Win: `Ctrl+C`，mac: `Cmd+C`）+ 读剪贴板，会瞬间替换剪贴板再恢复（200ms 内）
- 托管代理与 MiniMax 的服务可用性绑定；任何一环短暂失效都会自动降级到 Google 免费翻译
- macOS 没有"全局取当前光标形状"的公共 API，因此不做"拖窗/拖滚动条"的光标预判，全靠拖动距离 + 实际取词；最坏情况只是误弹一句"未获取到选中文本"

## 项目结构

```
translate/
├── main.py                          # 入口，串起所有模块
├── config.py                        # 配置加载/保存（engine + HOSTED 代理常量）
├── http_util.py                     # 标准库 urllib 实现的极简 HTTP
├── engines.py                       # 公共免费翻译引擎（Google + 兜底）
├── langs.py                         # 语言方向判断 + 语言名→语言码映射
├── llm_client.py                    # 三档引擎调度 + OpenAI 兼容流式
├── selection_monitor.py             # 全局鼠标监听 + 抓取选中文本（跨平台）
├── platform_backend.py              # 按 sys.platform 选择平台实现
├── platform_win.py                  # Windows：光标/进程判断、Ctrl+C、开机自启
├── platform_mac.py                  # macOS：前台判断、Cmd+C、开机自启
├── floating_icon.py                 # 跟随光标的小图标
├── translation_popup.py             # 翻译结果卡片
├── settings_dialog.py               # 设置对话框（分引擎显隐）
├── tray.py                          # 系统托盘 / 菜单栏
├── telemetry.py                     # 客户端埋点 fire-and-forget 发送器（install_id/session_id 管理）
├── api/v1/chat/completions.mjs      # Vercel Edge 代理函数（托管档后端，附 metric 落 Supabase）
├── api/event.mjs                    # 客户端事件端点（每次 popup/click/settings 改动写一行 events 表）
├── api/_supabase.mjs                # Supabase events 表写入封装（两端共用）
├── analyze_metrics.py               # 拉 Supabase events 表出每日量/eager 命中/P50P95 延迟/错误的小报
├── TranslatePopup.spec              # PyInstaller 瘦身打包配置
├── build_win.ps1                    # Windows 一键打包脚本
├── start_mac.command                # macOS 双击启动
└── requirements.txt
```

## 打包（瘦身单文件）

打包用 `TranslatePopup.spec`，已做极致瘦身：只保留 `QtCore/QtGui/QtWidgets`，排除其余 31 个 Qt 模块与无关大包。

### Windows → exe

```powershell
./build_win.ps1
# 或手动：
python -m pip install pyinstaller
python -m PyInstaller --noconfirm TranslatePopup.spec
```

产物在 `dist/TranslatePopup.exe`（实测约 35MB）。装了 [UPX](https://upx.github.io/) 后重打约 32MB——onefile 包本身已二次压缩，UPX 增益有限（约 10%）。

### macOS → .app

```bash
python3 -m pip install pyinstaller
python3 -m PyInstaller --noconfirm TranslatePopup.spec
```

产物在 `dist/TranslatePopup.app`（spec 已设 `LSUIElement=1`，纯菜单栏应用，不占 Dock）。
分发给他人还需做代码签名 / 公证，并提示对方在「辅助功能 + 输入监控」里授权该 App。

## 自测

```bash
python test_internals.py
```

覆盖：think 标签过滤、流式去前导空白、语言方向判断、语言码映射、免费引擎解析、HTTP 错误格式化、引擎端点解析、**代理失败自动降级到免费引擎**、剪贴板恢复、圆点定位等。

## 看埋点

满足「每个交互一条 log + 持久化到数据库」约束。所有事件落 Supabase `events` 表（单表 + jsonb props）。

**两类事件:**
- `origin=proxy` · `event=metric` —— 代理端每次翻译请求一条,字段含 model/input_chars/output_bytes/duration_ms/thinking/source/status/error
- `origin=client` —— 客户端 fire-and-forget POST `/api/event`,事件名包括 `app_start` / `app_quit` / `settings_opened` / `settings_saved` / `tray_enabled_changed` / `tray_autostart_changed` / `icon_shown` / `selection_cached` / `icon_clicked` / `icon_auto_hidden` / `eager_started` / `eager_adopted` / `eager_completed` / `eager_cancelled` / `popup_shown` / `popup_closed` / `translation_started` / `translation_failed`

**Install/Session 关联:** 客户端首次启动生成匿名 `install_id`(持久,落 config.json),每次启动随机 `session_id`(内存)。代理 metric 和客户端事件用同一对 ID,可在 SQL 里 JOIN。

**隐私:** 不记任何原文/译文,只记元数据(长度、duration、模型、版本、source)。客户端不直连 Supabase,所有写入经 Vercel 函数注入 ANON key。

**看报表:**

```bash
vercel env pull .env.local    # 首次:把 SUPABASE_URL + ANON_KEY 拉到本地
python analyze_metrics.py --since 1d
```

输出:每日事件数、独立 install/session、proxy 延迟 P50/P95、source/model/thinking 分布、eager 漏斗(started/adopted/completed/cancelled + 命中率)、客户端事件 Top 20、版本分布。`--since 30m/6h/1d/7d` 调窗,`--raw` 倒出原始 JSON。
