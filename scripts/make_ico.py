"""把 build/icon-1024.png 打包成多尺寸 Windows .ico（供 PyInstaller 设 exe 图标）。

依赖 Pillow，仅在 CI 里跑（本机不强制安装）。.icns 由 sips/iconutil 生成，不走这里。
"""
from PIL import Image

SRC = "build/icon-1024.png"
OUT = "build/AppIcon.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main():
    im = Image.open(SRC).convert("RGBA")
    im.save(OUT, sizes=SIZES)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
