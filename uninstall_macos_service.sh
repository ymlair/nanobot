#!/bin/bash
# macOS LaunchAgent 卸载脚本

PLIST_NAME="com.nanobot.gateway"
PLIST_FILE="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo "=== Nanobot LaunchAgent 卸载脚本 ==="
echo ""

if [ ! -f "$PLIST_FILE" ]; then
    echo "❌ LaunchAgent 未安装"
    exit 1
fi

# 停止并卸载服务
if launchctl list | grep -q "$PLIST_NAME"; then
    echo "停止服务..."
    launchctl stop "$PLIST_NAME"
    echo "卸载服务..."
    launchctl unload "$PLIST_FILE"
fi

# 删除配置文件
echo "删除配置文件..."
rm "$PLIST_FILE"

echo ""
echo "✓ Nanobot LaunchAgent 已成功卸载！"
echo ""
echo "注意: 日志文件保留在 ~/.nanobot/logs/"
echo "如需删除日志: rm -rf ~/.nanobot/logs/"
