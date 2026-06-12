"""生成「选中即懂 Select」应用图标（纯标准库，无 PIL/numpy）。

环境限制：本机 Python 渲染对多个相似的圆角矩形只生效最后一个，故内部只画一条
高亮行（= 选中的一行文字），配合选区框 + 两个拖拽手柄，构成「选中」语义。

用有符号距离场（SDF）+ 1px 抗锯齿绘制：
  - 蓝色渐变 squircle 圆角方底（四角透明）
  - 文本选区矩形（半透明白填充 + 白描边）
  - 选区内一条居中高亮文本行
  - 左上 / 右下两个选择手柄（白圆 + 蓝心）
输出 RGBA PNG，默认 1024×1024。
"""
import math
import os
import struct
import zlib

SIZE = 1024

TOP = (0x4C, 0x8D, 0xF7)
BOT = (0x1B, 0x46, 0xC9)
WHITE = (255, 255, 255)


def lerp(a, b, t):
    return a + (b - a) * t


def rr_sdf(x, y, x0, y0, x1, y1, r):
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = (x1 - x0) / 2 - r, (y1 - y0) / 2 - r
    qx, qy = abs(x - cx) - hx, abs(y - cy) - hy
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def cov_fill(d):
    return min(max(0.5 - d, 0.0), 1.0)


def cov_stroke(d, w):
    return min(max(0.5 - (abs(d) - w / 2), 0.0), 1.0)


def over(dst, src, a):
    return (int(round(lerp(dst[0], src[0], a))),
            int(round(lerp(dst[1], src[1], a))),
            int(round(lerp(dst[2], src[2], a))))


def render(S):
    k = S / 1024.0

    bg_r = 232
    sel = (232, 336, 792, 688)
    sel_r = 42
    sel_stroke = 13
    line = (360, 664, 474, 550)   # 居中高亮行
    line_r = 28
    handles = [(232, 336), (792, 688)]
    h_out = 48
    h_in = 19

    grad = []
    for py in range(S):
        t = py / (S - 1)
        grad.append((int(lerp(TOP[0], BOT[0], t)),
                     int(lerp(TOP[1], BOT[1], t)),
                     int(lerp(TOP[2], BOT[2], t))))

    raw = bytearray()
    for py in range(S):
        raw.append(0)
        y = (py + 0.5) / k
        grb = grad[py]
        for px in range(S):
            x = (px + 0.5) / k

            bgc = cov_fill(rr_sdf(x, y, 0, 0, 1024, 1024, bg_r))
            if bgc <= 0.0:
                raw += b"\x00\x00\x00\x00"
                continue

            col = grb
            sd = rr_sdf(x, y, sel[0], sel[1], sel[2], sel[3], sel_r)
            fc = cov_fill(sd)
            if fc > 0:
                col = over(col, WHITE, 0.15 * fc)

            lc = cov_fill(rr_sdf(x, y, line[0], line[1], line[2], line[3], line_r))
            if lc > 0:
                col = over(col, WHITE, 0.96 * lc)

            sc = cov_stroke(sd, sel_stroke)
            if sc > 0:
                col = over(col, WHITE, 0.92 * sc)

            for hx, hy in handles:
                d = math.hypot(x - hx, y - hy)
                oc = cov_fill(d - h_out)
                if oc > 0:
                    col = over(col, WHITE, oc)
                    ic = cov_fill(d - h_in)
                    if ic > 0:
                        col = over(col, grb, ic)

            raw += bytes((col[0], col[1], col[2], int(round(255 * bgc))))
    return raw


def main():
    S = SIZE
    raw = render(S)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", S, S, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    os.makedirs("assets", exist_ok=True)
    out = "assets/icon-%d.png" % S
    with open(out, "wb") as f:
        f.write(png)
    print("wrote", out, len(png), "bytes")


if __name__ == "__main__":
    main()
