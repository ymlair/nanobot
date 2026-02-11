# Nanobot 重启功能（macOS）

在飞书中告诉 nanobot "重启"，它会自动重启并恢复连接。

## 安装

只需运行一次安装脚本：

```bash
./install_macos_service.sh
```

这会将 nanobot 注册为 macOS LaunchAgent 服务：
- ✅ 开机自动启动
- ✅ 退出后自动重启
- ✅ 飞书连接自动恢复

## 使用

安装后，服务会自动启动。

### 在飞书中重启

直接对 nanobot 说：
- "重启"
- "restart"
- "重新启动"

nanobot 会优雅退出，macOS LaunchAgent 会在 3 秒内自动重启服务。

### 命令行管理

```bash
# 查看服务状态
launchctl list | grep nanobot

# 停止服务
launchctl stop com.nanobot.gateway

# 启动服务
launchctl start com.nanobot.gateway

# 查看日志
tail -f ~/.nanobot/logs/nanobot.log
tail -f ~/.nanobot/logs/nanobot.error.log
```

## 卸载

```bash
./uninstall_macos_service.sh
```

## 工作原理

```
飞书: "重启"
  ↓
nanobot 调用 restart 工具
  ↓
等待 2 秒（发送响应消息）
  ↓
发送 SIGTERM 信号优雅退出
  ↓
macOS LaunchAgent 检测到退出
  ↓
3 秒后自动重启
  ↓
飞书连接自动恢复 ✓
```

## 日志位置

- 标准输出: `~/.nanobot/logs/nanobot.log`
- 错误输出: `~/.nanobot/logs/nanobot.error.log`

## 故障排除

### 重启后没有自动恢复

检查服务是否在运行：
```bash
launchctl list | grep nanobot
```

查看错误日志：
```bash
tail -50 ~/.nanobot/logs/nanobot.error.log
```

### 手动重启服务

```bash
launchctl stop com.nanobot.gateway && launchctl start com.nanobot.gateway
```

### 重新安装服务

```bash
./uninstall_macos_service.sh
./install_macos_service.sh
```
