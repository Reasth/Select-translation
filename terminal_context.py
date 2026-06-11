"""终端(Claude Code)场景支持:文本清洗、本地术语词典、「发给 Claude」建议提取。

产品假设:用户在终端里划词 = 在 Claude Code 会话里,且是零编程经验的小白。
这里的一切都必须保持轻量——纯 stdlib 字符串处理,零新依赖、零网络、零常驻开销。
词典命中 = 零 LLM 调用、零延迟、零 token 成本,是终端场景轻量化的最大正贡献。
"""
from __future__ import annotations

import re

# 终端边框/分隔线字符(Claude Code 的对话框、表格边框),进 LLM 前全部剥掉——
# 它们也是要花钱的 input token,而且会干扰模型对正文的判断。
_BOX_CHARS = set("─│┌┐└┘├┤┬┴┼╭╮╰╯═║╔╗╚╝▏▕")

# 行首状态/提示符标记:Claude Code 的工具调用圆点、完成对勾、shell 提示符等。
# 只在行首且后跟空格(或独占一行)时剥,避免误伤正文里的 > 与 $。
_LINE_MARKERS = ("⏺", "✓", "✗", "✻", "●", "○", "›", "❯", ">", "$")

# 合并硬换行时,上一行以这些字符结尾视为「句子完整」,不合并。
_LINE_END_PUNCT = ".,:;!?)]}>\"'。，：；！？"


def clean_terminal_text(text: str) -> str:
    """清洗从终端抓到的选区:剥边框字符和行首标记、去行尾空白、合并被终端
    宽度硬切断的行(上一行无结束标点 + 下一行小写/数字开头才合并,保守策略)。
    清洗后为空时退回原文,保证永远有东西可翻。"""
    lines: list[str] = []
    for raw in text.splitlines():
        line = "".join(ch for ch in raw if ch not in _BOX_CHARS).strip()
        changed = True
        while changed and line:
            changed = False
            for m in _LINE_MARKERS:
                if line == m:
                    line = ""
                    changed = True
                    break
                if line.startswith(m + " "):
                    line = line[len(m):].strip()
                    changed = True
                    break
        if line:
            lines.append(line)

    merged: list[str] = []
    for line in lines:
        if (
            merged
            and merged[-1][-1] not in _LINE_END_PUNCT
            and (line[0].islower() or line[0].isdigit())
        ):
            merged[-1] += " " + line
        else:
            merged.append(line)

    out = "\n".join(merged).strip()
    return out or text.strip()


# Claude Code / 工程高频术语小词典。命中即本地直出:不发请求、不花 token、零延迟。
# 解释口径面向零编程经验用户,只在目标语言是中文时启用(见 main.py 的调用方)。
# 全部文本约 3KB,对包体积无感。
_GLOSSARY: dict[str, str] = {
    # ---- Claude Code 自身概念 ----
    "claude code": "Anthropic 出的 AI 编程助手，就是你正在这个终端里用的工具：你用中文提需求，它帮你写代码、改文件、跑命令。",
    "mcp": "MCP（Model Context Protocol）是给 Claude 接外部工具的插件标准。看到它说明 Claude 在用某个扩展能力，不需要你操作。",
    "compact": "Claude Code 在压缩对话历史，给后续对话腾出记忆空间。自动完成，等几秒就好。压缩后它可能忘记早先细节，重要要求可以再说一遍。",
    "compacting": "Claude Code 正在压缩对话历史，给后续对话腾记忆空间。自动完成，等几秒就好，不用管。",
    "compacting conversation": "Claude Code 正在压缩对话历史，给后续对话腾记忆空间。自动完成，等几秒就好，不用管。",
    "context": "Claude 的「工作记忆」。快满时它会自动压缩（compact），之后可能忘了早先的细节，重要要求可以再说一遍。",
    "context low": "Claude 的工作记忆快满了，马上会自动压缩。不影响使用，但压缩后它可能忘记早先细节，重要要求可以再提一次。",
    "plan mode": "Claude Code 的「先规划后动手」模式：它先列出打算怎么改，经你确认才真正改文件。放心看完计划再回复。",
    "thinking": "Claude 正在思考。屏幕上滚动的是它的推理过程，等它想完会给出正式回答，不用打断。",
    "subagent": "Claude 派出的「分身」助手，在后台跑一个子任务，跑完把结果汇报回来。全自动，不用你管。",
    "hook": "Claude Code 的自动化钩子：在特定时机（比如改完文件后）自动执行的命令。是提前配置好的，不需要你操作。",
    "hooks": "Claude Code 的自动化钩子：在特定时机（比如改完文件后）自动执行的命令。是提前配置好的，不需要你操作。",
    "claude.md": "项目里写给 Claude 看的说明书。它每次启动都会读这个文件，用来记住这个项目的规则和约定。",
    "/clear": "Claude Code 的命令：清空当前对话，重新开始。之前聊的内容它会全部忘掉。",
    "/compact": "Claude Code 的命令：手动压缩对话历史，腾出记忆空间。压缩后它可能忘记早先细节。",
    "token": "AI 计量文字的单位，大约 1 个 token ≈ 半个英文单词或半个汉字。AI 的用量和费用都按 token 算。",
    "tokens": "AI 计量文字的单位，大约 1 个 token ≈ 半个英文单词或半个汉字。AI 的用量和费用都按 token 算。",
    "rate limit": "请求太频繁，被服务方临时限流了。歇一会儿再试就好——不是你的错，也不会弄坏任何东西。",
    # ---- git / 版本管理 ----
    "git": "管理代码版本的工具，负责存档、回滚、同步，Claude 经常用它帮你保存进度。",
    "repo": "repository 的简称，「代码仓库」：你这个项目的所有文件和历史记录的总和。",
    "repository": "「代码仓库」：你这个项目的所有文件和历史记录的总和。",
    "commit": "把当前的修改打包存档一次，就像游戏存档。出问题随时可以回到任何一次存档。",
    "push": "把本地的存档（commit）上传到云端（比如 GitHub），给代码做云备份。",
    "pull request": "「请求合并代码」，简称 PR：把一批改动提交给仓库审核合并的流程。",
    "pr": "Pull Request（请求合并代码）：把一批改动提交给仓库审核合并的流程。",
    "branch": "代码的平行分支副本。在分支上随便改，改坏了也不影响主线。",
    "merge": "把两份代码改动合并到一起。",
    "merge conflict": "两份改动碰巧改了同一处，机器没法自动决定保留哪边。把报错原样发给 Claude，让它帮你处理就行。",
    # ---- 包管理 / 工程 ----
    "npm": "JavaScript 的「应用商店」：负责下载安装项目需要的现成组件（依赖包）。",
    "pip": "Python 的「应用商店」：负责下载安装 Python 项目需要的组件。",
    "dependency": "依赖：你的项目用到的、别人写好的现成组件。",
    "dependencies": "依赖：你的项目用到的、别人写好的现成组件。",
    "node_modules": "npm 下载的依赖包都放在这个文件夹里。体积很大但随时可以重新生成，不用备份它。",
    "package.json": "项目的「配料表」：记录项目叫什么、依赖哪些组件、有哪些可运行的命令。",
    ".env": "存密钥、密码等敏感配置的文件。注意：别截图外发，也别提交到公开仓库。",
    "deploy": "部署：把做好的应用发布到服务器上，让别人能通过网址访问。",
    "build": "构建：把源代码打包成可以运行或发布的成品。",
    "lint": "代码「体检」工具：检查格式和常见低级错误。它报的 warning 大多不影响运行。",
    "ci": "持续集成（Continuous Integration）：代码一更新就自动跑测试和构建的机器人流水线。",
    # ---- 网络 / 运行 ----
    "api": "应用之间互相调用的「服务窗口」。比如你的应用通过 API 调用 AI 服务。",
    "api key": "调用 API 服务的「门票 + 密码」。要保密：别截图外发，别提交到公开仓库。",
    "cli": "命令行工具（Command Line Interface）：在这种黑窗口里打字使用的程序。",
    "localhost": "「本机」的意思。比如 localhost:3000 就是跑在你自己电脑 3000 端口上的网页，只有你能访问。",
    "port": "端口：同一台电脑上区分不同程序网络通道的编号，比如 3000、8080。",
    "timeout": "超时：等对方响应等太久，放弃了。多半是网络慢或服务忙，重试一次通常就好。",
    "404": "「找不到」：请求的网址或资源不存在。",
    "500": "服务器内部出错：问题出在服务端，把报错发给 Claude 排查。",
    # ---- 报错相关 ----
    "stack trace": "程序出错时打印的「案发现场记录」，列出错误发生的位置链。整段复制发给 Claude 修最有效。",
    "warning": "警告：有潜在问题但程序还能跑。大多可以先忽略，报 error 才需要处理。",
    "deprecated": "「已过时，将来会移除」的提醒。暂时不影响运行，可以先不管。",
    "syntax error": "语法错误：代码写得不符合语言规则，程序跑不起来。直接让 Claude 修即可。",
    "permission denied": "权限不足：系统拒绝了这次操作。把报错发给 Claude，看是要换目录还是要管理员权限。",
    "debug": "调试：定位并修复程序问题的过程。",
}

# 词典只服务「划了一个短词/短语」的场景;超过这个长度说明是句子/报错,交给 LLM。
_GLOSSARY_MAX_CHARS = 40

_SUGGESTION_LABEL_RE = re.compile(r"^(发给\s*claude|tell\s+claude)\s*[:：]\s*", re.IGNORECASE)


def lookup_glossary(text: str) -> str | None:
    """选中文本命中本地术语词典时返回解释,否则 None(走 LLM)。"""
    t = (text or "").strip()
    if not t or "\n" in t or len(t) > _GLOSSARY_MAX_CHARS:
        return None
    t = t.strip("`'\"()[]{}<>“”‘’")
    t = t.rstrip(":：,，.。!！?？")
    t = " ".join(t.split()).lower()
    if not t:
        return None
    return _GLOSSARY.get(t)


def extract_claude_suggestion(answer: str) -> str | None:
    """从 LLM 回答里提取「👉 发给 Claude」那行建议,供一键复制。没有则 None。"""
    for line in reversed((answer or "").splitlines()):
        line = line.strip()
        if line.startswith("👉"):
            s = line[len("👉"):].strip()
            s = _SUGGESTION_LABEL_RE.sub("", s)
            return s or None
    return None
