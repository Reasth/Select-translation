#!/bin/bash
# macOS 启动脚本：双击运行（首次需 chmod +x start_mac.command）。
cd "$(dirname "$0")"
exec python3 main.py
