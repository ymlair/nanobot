#!/bin/bash
# macOS LaunchAgent 安装脚本

set -e

PLIST_NAME="com.nanobot.gateway"
PLIST_FILE="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_PATH=$(which python3)
LOG_DIR="$HOME/.nanobot/logs"
ENV_FILE="$HOME/.nanobot/env"

echo "=== Nanobot LaunchAgent 安装脚本 ==="
echo ""

# 创建日志目录
mkdir -p "$LOG_DIR"

# 读取可选环境变量文件（用于 LaunchAgent）
# 示例：在 ~/.nanobot/env 中设置 CURSOR_API_KEY=xxx
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# 创建 plist 文件
cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>-m</string>
        <string>nanobot</string>
        <string>gateway</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>$WORK_DIR</string>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$PATH</string>
        <key>CURSOR_API_KEY</key>
        <string>${CURSOR_API_KEY:-}</string>
    </dict>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    
    <key>StandardOutPath</key>
    <string>$LOG_DIR/nanobot.log</string>
    
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/nanobot.error.log</string>
    
    <key>ThrottleInterval</key>
    <integer>3</integer>
</dict>
</plist>
EOF

echo "✓ 已创建 LaunchAgent 配置: $PLIST_FILE"
echo ""

# 加载服务
if launchctl list | grep -q "$PLIST_NAME"; then
    echo "停止现有服务..."
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
fi

echo "加载服务..."
launchctl load "$PLIST_FILE"

echo ""
echo "✓ Nanobot 已成功安装为 LaunchAgent！"
echo ""
echo "服务管理命令："
echo "  启动: launchctl start $PLIST_NAME"
echo "  停止: launchctl stop $PLIST_NAME"
echo "  重启: launchctl stop $PLIST_NAME && launchctl start $PLIST_NAME"
echo "  卸载: launchctl unload $PLIST_FILE"
echo ""
echo "查看日志："
echo "  标准输出: tail -f $LOG_DIR/nanobot.log"
echo "  错误输出: tail -f $LOG_DIR/nanobot.error.log"
echo ""
echo "现在你可以在飞书中直接告诉 nanobot '重启'，它会自动恢复连接！"
