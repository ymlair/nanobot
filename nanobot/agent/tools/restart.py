"""Restart tool for graceful nanobot restart (macOS LaunchAgent)."""

import os
import signal
from typing import Any

from nanobot.agent.tools.base import Tool


class RestartTool(Tool):
    """Tool to gracefully restart the nanobot process on macOS."""

    @property
    def name(self) -> str:
        return "restart"

    @property
    def description(self) -> str:
        return (
            "Gracefully restart the nanobot process. "
            "Requires macOS LaunchAgent service to be installed. "
            "Use this when you need to reload configuration or update code."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Optional reason for restart (for logging)"
                }
            },
            "required": []
        }

    async def execute(self, reason: str = "User requested restart", **kwargs: Any) -> str:
        """
        Execute graceful restart.

        Sends SIGTERM to the process, macOS LaunchAgent will automatically restart it.
        """
        try:
            # Log the restart
            from loguru import logger
            logger.info(f"Restart requested: {reason}")

            # Schedule process termination after a short delay
            # This allows the response to be sent before shutdown
            import asyncio

            async def delayed_exit():
                await asyncio.sleep(2)
                logger.info("Initiating graceful shutdown for restart...")
                os.kill(os.getpid(), signal.SIGTERM)

            asyncio.create_task(delayed_exit())

            return (
                "✅ 重启命令已接收。nanobot 将在 2 秒后重启。\n"
                f"原因: {reason}\n\n"
                "macOS LaunchAgent 会自动重启服务并恢复连接。"
            )

        except Exception as e:
            return f"❌ 重启失败: {str(e)}"
