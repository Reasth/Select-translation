"""生成「选中即懂 Select」应用图标（Pillow 渲染，4x 超采样抗锯齿）。

构图 = Select 自己的品牌标识：squircle 底 + 文本选区框 + 两个拖拽手柄 + 选区内文本行。
配色提供两套：
  - claude（默认）：Anthropic 设计语言——陶土橘底 + 奶油白图形。借的是气质与配色，
    不是 Claude 星芒商标；构图仍是 Select 的「选区」，避免冒充官方。
  - blue：1.3 时代的蓝色渐变（旧版,备查）。

用法（在仓库根目录运行）：python scripts/design_logo.py [claude|blue]
输出：assets/icon-1024.png
（旧版纯标准库 SDF 渲染器备份在 scripts/design_logo_sdf_backup.py）
"""
import sys

from PIL import Image, ImageDraw

SIZE = 1024
SS = 4  # 超采样倍数

PALETTES = {
    "claude": {
        # Anthropic 陶土橘,上浅下深的极轻渐变,保留近乎平涂的手工暖感
        "bg_top": (0xE0, 0x82, 0x5E),
        "bg_bot": (0xCB, 0x62, 0x3C),
        "ink": (0xFA, 0xF9, 0xF5),     # 奶油白(图形主色)
        "handle_in": (0xCB, 0x62, 0x3C),
    },
    "blue": {
        "bg_top": (0x4C, 0x8D, 0xF7),
        "bg_bot": (0x1B, 0x46, 0xC9),
        "ink": (0xFF, 0xFF, 0xFF),
        "handle_in": (0x2B, 0x5A, 0xD9),
    },
}


def render(palette: dict) -> Image.Image:
    S = SIZE * SS
    k = S / 1024.0

    def px(v):  # 1024 设计坐标 → 超采样坐标
        return v * k

    # ---- 底:垂直渐变 squircle ----
    grad = Image.new("RGB", (1, S))
    top, bot = palette["bg_top"], palette["bg_bot"]
    for y in range(S):
        t = y / (S - 1)
        grad.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bot)))
    grad = grad.resize((S, S))

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, S - 1, S - 1), radius=px(232), fill=255
    )
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    # ImageDraw 对 RGBA 填充是「替换像素」不是混合 —— 半透明图形必须画在独立
    # 透明层上,再 alpha_composite 回底图,否则成品里会出现半透明的洞。
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    ink = palette["ink"]

    # ---- 文本选区框:半透明填充 + 描边 ----
    sel = (px(232), px(352), px(792), px(672))
    draw.rounded_rectangle(sel, radius=px(40), fill=ink + (46,))
    draw.rounded_rectangle(sel, radius=px(40), outline=ink + (245,), width=int(px(14)))

    # ---- 选区内文本行:一暗一亮,亮行 = 被「懂」的那行 ----
    draw.rounded_rectangle(
        (px(304), px(424), px(600), px(472)), radius=px(24), fill=ink + (120,)
    )
    draw.rounded_rectangle(
        (px(304), px(528), px(720), px(576)), radius=px(24), fill=ink + (242,)
    )

    # ---- 左上 / 右下拖拽手柄:奶油白圆 + 底色圆心 ----
    for hx, hy in ((232, 352), (792, 672)):
        r_out, r_in = px(48), px(19)
        cx, cy = px(hx), px(hy)
        draw.ellipse((cx - r_out, cy - r_out, cx + r_out, cy + r_out), fill=ink + (255,))
        draw.ellipse(
            (cx - r_in, cy - r_in, cx + r_in, cy + r_in),
            fill=palette["handle_in"] + (255,),
        )

    img = Image.alpha_composite(img, layer)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def render_tray(palette: dict) -> Image.Image:
    """托盘版:同一构图但只留「选区框 + 亮行 + 手柄」,描边加粗——托盘实际显示
    只有 16-32px,细节多了就糊成一团。输出 256px。"""
    S = 1024 * SS
    k = S / 1024.0

    def px(v):
        return v * k

    grad = Image.new("RGB", (1, S))
    top, bot = palette["bg_top"], palette["bg_bot"]
    for y in range(S):
        t = y / (S - 1)
        grad.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bot)))
    grad = grad.resize((S, S))

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, S - 1, S - 1), radius=px(232), fill=255
    )
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    ink = palette["ink"]

    sel = (px(200), px(330), px(824), px(694))
    draw.rounded_rectangle(sel, radius=px(52), fill=ink + (52,))
    draw.rounded_rectangle(sel, radius=px(52), outline=ink + (250,), width=int(px(26)))
    draw.rounded_rectangle(
        (px(296), px(472), px(728), px(552)), radius=px(40), fill=ink + (245,)
    )
    for hx, hy in ((200, 330), (824, 694)):
        r_out, r_in = px(72), px(30)
        cx, cy = px(hx), px(hy)
        draw.ellipse((cx - r_out, cy - r_out, cx + r_out, cy + r_out), fill=ink + (255,))
        draw.ellipse(
            (cx - r_in, cy - r_in, cx + r_in, cy + r_in),
            fill=palette["handle_in"] + (255,),
        )

    img = Image.alpha_composite(img, layer)
    return img.resize((256, 256), Image.LANCZOS)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "claude"
    if name not in PALETTES:
        sys.exit(f"unknown palette {name!r}; choose from {sorted(PALETTES)}")
    img = render(PALETTES[name])
    out = "assets/icon-1024.png"
    img.save(out)
    print("wrote", out, f"({name})")

    tray = render_tray(PALETTES[name])
    tray.save("assets/tray.png")
    print("wrote assets/tray.png", f"({name})")


if __name__ == "__main__":
    main()
