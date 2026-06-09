"""生成一张纯色 PNG（512x512，品牌蓝），供 CI 用 sips 转成 .icns。

只用标准库，不依赖 PIL。PyInstaller 在 macOS BUNDLE 阶段必须拿到一个真实存在的
.icns，否则会去找默认图标并 FileNotFoundError 崩溃，所以 CI 先跑这个脚本。
"""
import struct
import zlib

W = H = 512
PIXEL = bytes((37, 99, 235, 255))  # #2563EB, 不透明


def _chunk(tag, data):
    body = tag + data
    return (
        struct.pack(">I", len(data))
        + body
        + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    )


def main():
    raw = bytearray()
    for _ in range(H):
        raw.append(0)  # 每行起始的 filter byte
        raw += PIXEL * W

    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )
    with open("icon.png", "wb") as f:
        f.write(png)
    print("wrote icon.png", len(png), "bytes")


if __name__ == "__main__":
    main()
