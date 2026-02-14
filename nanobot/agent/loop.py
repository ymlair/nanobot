"""Agent loop: the core processing engine."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import SessionManager

# Busy reply cooldown per chat: avoid spamming "I'm busy" for every message
_BUSY_REPLY_COOLDOWN = 15  # seconds

# Keywords that indicate the user wants to cancel the current task
_CANCEL_KEYWORDS = [
    "停止", "取消", "算了", "停下", "别做了", "不用了", "不要了",
    "中断", "打断", "别干了", "停一下", "别搞了",
    "stop", "cancel", "abort", "nevermind", "never mind",
]


class AgentLoop:
    """
    The agent loop is the core processing engine.
    
    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """
    
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        from nanobot.cron.service import CronService
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        
        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
        )
        
        self._running = False
        self._processing = False  # True when actively processing a message
        self._processing_description = ""  # What the agent is currently doing
        self._busy_reply_timestamps: dict[str, float] = {}  # chat_key -> last busy reply time
        self._register_default_tools()
    
    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(EditFileTool())
        self.tools.register(ListDirTool())
        
        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.exec_config.restrict_to_workspace,
        ))
        
        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        
        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)
        
        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)
        
        # Cron tool (for scheduling)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))
        
        # Restart tool (for graceful restart)
        from nanobot.agent.tools.restart import RestartTool
        self.tools.register(RestartTool())
    
    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus.
        
        Messages are processed as asyncio Tasks so the main loop can continue
        monitoring the inbound queue. This enables:
        - Immediate "busy" replies when the agent is working on something
        - Task cancellation when the user sends a "stop/cancel" message
        - Queuing of new messages for processing after the current one finishes
        """
        self._running = True
        logger.info("Agent loop started")
        
        current_task: asyncio.Task[None] | None = None
        current_msg: InboundMessage | None = None
        pending_queue: list[InboundMessage] = []
        
        while self._running:
            # --- Phase 1: If idle, pick next message and start processing ---
            if current_task is None:
                if pending_queue:
                    next_msg = pending_queue.pop(0)
                else:
                    try:
                        next_msg = await asyncio.wait_for(
                            self.bus.consume_inbound(),
                            timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        continue
                
                current_msg = next_msg
                current_task = asyncio.create_task(
                    self._safe_process(next_msg)
                )
                # Don't fall through — go back to top to enter Phase 2
                continue
            
            # --- Phase 2: Task is running, monitor for new messages ---
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=0.5
                )
            except asyncio.TimeoutError:
                # No new message; check if task finished
                if current_task.done():
                    self._collect_task(current_task)
                    current_task = None
                    current_msg = None
                continue
            
            # Got a new message while busy
            if msg.channel == "system":
                # System messages (subagent results) just queue silently
                pending_queue.append(msg)
            elif self._is_cancel_intent(msg.content):
                # User wants to cancel the current task!
                logger.info(f"Cancel requested: '{msg.content}' — cancelling current task")
                current_task.cancel()
                try:
                    await current_task
                except asyncio.CancelledError:
                    logger.info("Current task cancelled successfully")
                
                # Send cancellation confirmation
                await self._send_cancel_reply(msg, current_msg)
                
                # Save to session so cancellation is in history
                if current_msg and current_msg.channel != "system":
                    session = self.sessions.get_or_create(current_msg.session_key)
                    session.add_message("user", current_msg.content)
                    session.add_message("assistant", "[任务已被用户取消]")
                    self.sessions.save(session)
                
                current_task = None
                current_msg = None
            else:
                # Regular message while busy — send busy reply, queue it
                await self._send_busy_reply(msg)
                pending_queue.append(msg)
            
            # Check if task finished while we were handling the new message
            if current_task is not None and current_task.done():
                self._collect_task(current_task)
                current_task = None
                current_msg = None
    
    def _collect_task(self, task: asyncio.Task[None]) -> None:
        """Collect a finished task, logging any unexpected exceptions."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(f"Task raised unexpected exception: {exc}")
    
    async def _safe_process(self, msg: InboundMessage) -> None:
        """Process a message with busy-state tracking and error handling.
        
        Supports cancellation via asyncio.CancelledError — the error propagates
        up so the caller (run loop) can handle the cancel flow.
        """
        self._processing = True
        self._processing_description = msg.content[:50] if msg.content else ""
        try:
            response = await self._process_message(msg)
            if response:
                await self.bus.publish_outbound(response)
        except asyncio.CancelledError:
            logger.info(f"Processing cancelled for: {self._processing_description}")
            raise  # Re-raise so run() can handle it
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            error_metadata = dict(msg.metadata or {})
            error_metadata["sender_id"] = msg.sender_id
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Sorry, I encountered an error: {str(e)}",
                metadata=error_metadata
            ))
        finally:
            self._processing = False
            self._processing_description = ""
    
    @staticmethod
    def _is_cancel_intent(content: str) -> bool:
        """Check if a message is a cancel/stop request.
        
        Only matches short messages to avoid false positives like
        "请帮我查一下如何停止docker容器".
        """
        text = content.strip().lower()
        if len(text) > 30:
            return False
        return any(kw in text for kw in _CANCEL_KEYWORDS)
    
    async def _send_cancel_reply(
        self, cancel_msg: InboundMessage, cancelled_msg: InboundMessage | None
    ) -> None:
        """Send a confirmation that the current task was cancelled."""
        what = ""
        if cancelled_msg:
            preview = cancelled_msg.content[:30]
            if len(cancelled_msg.content) > 30:
                preview += "..."
            what = f"（{preview}）"
        
        text = f"好的，已停止上一个任务{what}"
        
        outbound_metadata = dict(cancel_msg.metadata or {})
        outbound_metadata["sender_id"] = cancel_msg.sender_id
        await self.bus.publish_outbound(OutboundMessage(
            channel=cancel_msg.channel,
            chat_id=cancel_msg.chat_id,
            content=text,
            metadata=outbound_metadata,
        ))
    
    async def _send_busy_reply(self, msg: InboundMessage) -> None:
        """Send an immediate 'busy' reply when the agent is processing another message.
        
        Uses a cooldown to avoid spamming the user with repeated busy messages.
        """
        chat_key = f"{msg.channel}:{msg.chat_id}"
        now = time.monotonic()
        last_reply = self._busy_reply_timestamps.get(chat_key, 0)
        
        if now - last_reply < _BUSY_REPLY_COOLDOWN:
            logger.debug(f"Busy reply cooldown active for {chat_key}, skipping")
            return
        
        self._busy_reply_timestamps[chat_key] = now
        
        busy_text = "我正在处理上一条消息，稍等一下，处理完了马上回复你～"
        
        outbound_metadata = dict(msg.metadata or {})
        outbound_metadata["sender_id"] = msg.sender_id
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=busy_text,
            metadata=outbound_metadata,
        ))
        logger.info(f"Sent busy reply to {chat_key}")
    
    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a single inbound message.
        
        Args:
            msg: The inbound message to process.
        
        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")
        
        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(msg.channel, msg.chat_id)
        
        # Build initial messages (use get_history for LLM-formatted messages)
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )
        
        # Agent loop
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            # Handle tool calls
            if response.has_tool_calls:
                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)  # Must be JSON string
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # No tool calls, we're done
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "I've completed processing but have no response to give."
        
        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        outbound_metadata = dict(msg.metadata or {})
        outbound_metadata["sender_id"] = msg.sender_id
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=outbound_metadata
        )
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).
        
        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info(f"Processing system message from {msg.sender_id}")
        
        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(origin_channel, origin_chat_id)
        
        # Build messages with the announce content
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
        )
        
        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).
        
        Args:
            content: The message content.
            session_key: Session identifier.
            channel: Source channel (for context).
            chat_id: Source chat ID (for context).
        
        Returns:
            The agent's response.
        """
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )
        
        response = await self._process_message(msg)
        return response.content if response else ""
