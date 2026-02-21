"""AI Engine: Claude agentic loop (API) or Claude Code CLI (Max subscription)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Optional

from pathlib import Path

from .history import ConversationHistory
from .prompts import build_system_prompt
from .tools import TOOL_DEFINITIONS, get_registry

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10


class AIEngine:
    def __init__(
        self,
        api_key: Optional[str],
        model: str,
        max_tokens: int,
        history: ConversationHistory,
    ):
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._history = history
        self._system_prompt = build_system_prompt()

        if api_key:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
            logger.info("AI backend: Anthropic API (model: %s)", model)
        else:
            self._client = None
            logger.info("AI backend: Claude Code CLI (Max subscription)")

    async def process(
        self,
        conv_id: str,
        text: str,
        media_path: Optional[str],
        sender_id: str,
        channel: str,
        recipient_id: str,
    ) -> str:
        """Process a user message and return the assistant reply."""

        # Build user content blocks
        user_content: list[dict] = []
        if text:
            user_content.append({"type": "text", "text": text})
        if media_path:
            import mimetypes
            mime, _ = mimetypes.guess_type(media_path)
            if mime and mime.startswith("image/") and self._client:
                # Image attachment only supported in API mode
                try:
                    import base64
                    with open(media_path, "rb") as f:
                        data = base64.standard_b64encode(f.read()).decode()
                    user_content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": data},
                    })
                except Exception as e:
                    logger.warning("Could not attach image: %s", e)
                    user_content.append({"type": "text", "text": f"[Attached file: {media_path}]"})
            else:
                user_content.append({"type": "text", "text": f"[Attached file: {media_path}]"})

        if not user_content:
            user_content = [{"type": "text", "text": "(empty message)"}]

        # Persist user message
        await self._history.append(conv_id, "user", user_content, tokens=_estimate_tokens(text))

        # Route: API (with full tool loop) or CLI (Claude Max)
        if self._client:
            history = await self._history.load(
                conv_id, sender_id, channel, summarize_fn=self._summarize_messages
            )
            response = await self._run_api(history, sender_id, channel, recipient_id)
        else:
            history = await self._history.load(
                conv_id, sender_id, channel, summarize_fn=self._summarize_messages
            )
            response = await self._run_cli(history, text or "", sender_id, channel)

        # Persist assistant response
        await self._history.append(conv_id, "assistant", response, tokens=_estimate_tokens(response))
        return response

    async def _run_api(
        self,
        messages: list[dict],
        sender_id: str,
        channel: str,
        recipient_id: str,
    ) -> str:
        """Run the agentic loop against the Claude API."""
        registry = get_registry()

        for iteration in range(MAX_ITERATIONS):
            logger.debug("API iteration %d/%d", iteration + 1, MAX_ITERATIONS)

            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system_prompt,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            # Collect text content from response
            text_parts = [
                block.text for block in resp.content if block.type == "text"
            ]

            if resp.stop_reason == "end_turn":
                return "\n".join(text_parts) if text_parts else "(no response)"

            if resp.stop_reason == "tool_use":
                # Add assistant turn to messages
                messages.append({"role": "assistant", "content": resp.content})

                # Execute all tool calls
                tool_results = []
                for block in resp.content:
                    if block.type != "tool_use":
                        continue
                    tool_name = block.name
                    args = block.input
                    logger.info("Tool call: %s(%s)", tool_name, json.dumps(args)[:200])

                    result = await registry.dispatch(
                        tool_name, args, sender_id, channel, recipient_id
                    )
                    logger.debug("Tool result: %s…", str(result)[:200])

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })

                messages.append({"role": "user", "content": tool_results})
                continue

            # max_tokens or other stop reasons
            text = "\n".join(text_parts)
            if resp.stop_reason == "max_tokens":
                text += "\n…[response truncated]"
            return text if text else "(no response)"

        return "[Error] Maximum tool-use iterations reached. Please try a simpler request."

    async def _summarize_messages(self, messages: list[dict]) -> str:
        """Summarize a chunk of messages into a compact memory block via the CLI."""
        lines = []
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                content = " ".join(text_parts)
            label = "User" if role == "user" else "Assistant"
            if content:
                lines.append(f"{label}: {content[:400]}")

        prompt = (
            "Summarize this conversation chunk in 3-5 bullet points.\n"
            "Focus on: tasks completed, important facts about the user or their system, key decisions.\n"
            "Be very concise. Bullet points only.\n\n"
            "Conversation:\n" + "\n".join(lines) + "\n\nSummary:"
        )

        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        claude_bin = str(Path.home() / ".claude" / "local" / "claude")
        try:
            proc = await asyncio.create_subprocess_exec(
                claude_bin, "--print", "--output-format", "text",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(input=prompt.encode()), timeout=60)
            result = stdout.decode(errors="replace").strip()
            result = re.sub(r"\x1b\[[0-9;]*m", "", result)
            return result or "(summary unavailable)"
        except Exception as e:
            logger.warning("Summarization failed: %s", e)
            return "(summary unavailable)"

    async def _run_cli(self, history: list[dict], current_text: str, sender_id: str = "", channel: str = "") -> str:
        """
        Run via Claude Code CLI using the Max subscription.

        Builds a full prompt with system context + conversation history + current message,
        then pipes it to `claude --print` via stdin.

        Claude Code's built-in tools (Bash, Read, Write, etc.) are available
        via --allowedTools, so the butler can still perform Mac actions.
        """
        butler_home = str(Path(__file__).parent.parent.parent)
        python_bin = str(Path(butler_home) / ".venv" / "bin" / "python")
        tools_cli = f"{python_bin} -m butler.tools_cli"

        cli_tools_section = f"""
## CLI Tools (use via Bash)
You have access to butler's full tool suite by running bash commands from {butler_home}:

Browser:
  {tools_cli} browser_open '{{"url":"https://example.com"}}'   # navigate + screenshot in one step (PREFERRED)
  {tools_cli} browser_navigate '{{"url":"https://example.com"}}'  # navigate only
  {tools_cli} browser_click '{{"selector":"button#submit"}}'
  {tools_cli} browser_type '{{"selector":"input#search","text":"query"}}'
  {tools_cli} browser_get_text '{{"selector":"body"}}'
  {tools_cli} browser_screenshot '{{}}'   # screenshot current page (must be same process as navigate — use browser_open instead)

Screenshots:
  {tools_cli} screenshot '{{"target":"desktop"}}'  # or "browser"

Email (if configured):
  {tools_cli} email_list '{{"count":10}}'                                     # default account
  {tools_cli} email_list '{{"count":10,"account":"work"}}'                    # named account
  {tools_cli} email_read '{{"message_id":"42"}}'
  {tools_cli} email_read '{{"message_id":"42","account":"personal"}}'
  {tools_cli} email_send '{{"to":"x@y.com","subject":"Hi","body":"Hello"}}'
  {tools_cli} email_send '{{"to":"x@y.com","subject":"Hi","body":"Hello","account":"work"}}'

Files:
  {tools_cli} file_read '{{"path":"~/notes.txt"}}'
  {tools_cli} file_list '{{"directory":"~/Desktop"}}'
  {tools_cli} file_write '{{"path":"~/out.txt","content":"hello"}}'

When a tool returns a file path (screenshot, browser_screenshot), use Read to display it.
Always run these from the working directory: {butler_home}
"""

        try:
            # Format conversation history as a readable transcript
            transcript_lines = [self._system_prompt, cli_tools_section, "--- Conversation so far ---"]
            for msg in history[:-1]:  # exclude the just-appended user message
                role = msg.get("role", "?")
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = [
                        b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    content = " ".join(text_parts)
                label = "User" if role == "user" else "Assistant"
                if content:
                    transcript_lines.append(f"{label}: {content}")

            transcript_lines.extend(["", "--- New message ---", f"User: {current_text}"])
            full_prompt = "\n".join(transcript_lines)

            logger.debug("CLI prompt length: %d chars", len(full_prompt))

            # Strip CLAUDECODE env var to allow nested invocation
            env = os.environ.copy()
            env.pop("CLAUDECODE", None)

            # Use absolute path so the daemon finds the right claude version
            claude_bin = str(Path.home() / ".claude" / "local" / "claude")

            proc = await asyncio.create_subprocess_exec(
                claude_bin,
                "--print",
                "--output-format", "text",
                "--allowedTools",
                "Bash,Read,Write,Edit,Glob,Grep",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=butler_home,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=full_prompt.encode()),
                timeout=300,
            )

            output = stdout.decode(errors="replace").strip()
            err = stderr.decode(errors="replace").strip()

            if not output:
                if err:
                    logger.warning("CLI stderr: %s", err[:500])
                    return f"[CLI error] {err[:500]}"
                return "(no response)"

            # Strip any residual ANSI escape codes
            output = re.sub(r"\x1b\[[0-9;]*m", "", output)
            return output

        except asyncio.TimeoutError:
            return "⏰ Request timed out (5 min). Try narrowing your question — e.g. ask about a specific file or function rather than the whole codebase."
        except FileNotFoundError:
            return (
                f"❌ Claude CLI not found at {claude_bin}.\n"
                "Make sure Claude Code is installed: https://claude.ai/download\n"
                "Or set anthropic.api_key in config/butler.yaml to use the API instead."
            )
        except Exception as e:
            logger.error("CLI execution error: %s", e, exc_info=True)
            return f"❌ CLI error: {e}"


def _estimate_tokens(text: str | list) -> int:
    """Rough token estimate (4 chars ≈ 1 token)."""
    if isinstance(text, list):
        text = json.dumps(text)
    return max(1, len(text) // 4)
