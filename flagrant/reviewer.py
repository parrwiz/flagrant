"""Review logic."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Optional

from rich.console import Console

from flagrant.config import AppConfig, PROVIDERS
from flagrant.prompt import build_system_prompt

console = Console()

MAX_LINES_PER_CHUNK = 3000
MAX_RETRIES = 1


@dataclass
class Issue:
    """A single code review issue."""
    severity: str  # high, medium, low
    file: str
    line: Optional[int]
    issue: str
    fix: str
    explanation: Optional[str] = None


def chunk_files(files: list[dict], max_lines: int = MAX_LINES_PER_CHUNK) -> list[str]:
    """Split files into chunks that fit context limits."""
    chunks = []
    current_chunk_lines = 0
    current_chunk_parts = []

    for f in files:
        content = f["content"]
        lines = content.splitlines()
        file_header = f"--- FILE: {f['path']} ---"

        # If single file exceeds max, split it
        if len(lines) > max_lines:
            # Flush current chunk first
            if current_chunk_parts:
                chunks.append("\n".join(current_chunk_parts))
                current_chunk_parts = []
                current_chunk_lines = 0

            for i in range(0, len(lines), max_lines):
                slice_lines = lines[i:i + max_lines]
                part_header = f"{file_header} (lines {i + 1}-{i + len(slice_lines)})"
                chunks.append(part_header + "\n" + "\n".join(slice_lines))
        else:
            # Would adding this file exceed the limit?
            if current_chunk_lines + len(lines) > max_lines and current_chunk_parts:
                chunks.append("\n".join(current_chunk_parts))
                current_chunk_parts = []
                current_chunk_lines = 0

            current_chunk_parts.append(file_header + "\n" + content)
            current_chunk_lines += len(lines)

    # Flush remaining
    if current_chunk_parts:
        chunks.append("\n".join(current_chunk_parts))

    return chunks


def _parse_issues(raw: str) -> list[Issue]:
    """Parse JSON issues from LLM response. Handles messy output."""
    raw = raw.strip()

    # Try direct parse first
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [_dict_to_issue(d) for d in data if isinstance(d, dict)]
    except json.JSONDecodeError:
        pass

    # Try to extract JSON array from surrounding text
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return [_dict_to_issue(d) for d in data if isinstance(d, dict)]
        except json.JSONDecodeError:
            pass

    # If we got markdown-wrapped JSON, strip it
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = cleaned.strip().rstrip("`")
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return [_dict_to_issue(d) for d in data if isinstance(d, dict)]
    except json.JSONDecodeError:
        pass

    return []


def _dict_to_issue(d: dict) -> Issue:
    return Issue(
        severity=d.get("severity", "low").lower().strip(),
        file=d.get("file", "unknown"),
        line=d.get("line"),
        issue=d.get("issue", ""),
        fix=d.get("fix", ""),
        explanation=d.get("explanation"),
    )


def _call_claude(
    app_config: AppConfig,
    system_prompt: str,
    user_content: str,
) -> str:
    """Call Anthropic Claude API."""
    from anthropic import Anthropic

    client = Anthropic(api_key=app_config.api_key)
    response = client.messages.create(
        model=app_config.effective_model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text


def _call_openai(
    app_config: AppConfig,
    system_prompt: str,
    user_content: str,
) -> str:
    """Call OpenAI API."""
    from openai import OpenAI

    client = OpenAI(api_key=app_config.api_key)
    response = client.chat.completions.create(
        model=app_config.effective_model,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content


def _call_gemini(
    app_config: AppConfig,
    system_prompt: str,
    user_content: str,
) -> str:
    """Call Google Gemini API."""
    from google import genai

    client = genai.Client(api_key=app_config.api_key)
    response = client.models.generate_content(
        model=app_config.effective_model,
        contents=user_content,
        config=genai.types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=4096,
        ),
    )
    return response.text


def _call_deepseek(
    app_config: AppConfig,
    system_prompt: str,
    user_content: str,
) -> str:
    """Call DeepSeek API (OpenAI-compatible)."""
    from openai import OpenAI

    client = OpenAI(
        api_key=app_config.api_key,
        base_url="https://api.deepseek.com",
    )
    response = client.chat.completions.create(
        model=app_config.effective_model,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content


PROVIDER_CALLERS = {
    "claude": _call_claude,
    "openai": _call_openai,
    "gemini": _call_gemini,
    "deepseek": _call_deepseek,
}


def _call_llm(
    app_config: AppConfig,
    system_prompt: str,
    user_content: str,
) -> str:
    """Call the configured provider. Retries once on failure."""
    caller = PROVIDER_CALLERS.get(app_config.provider)
    if not caller:
        raise ValueError(f"Unknown provider: {app_config.provider}")

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return caller(app_config, system_prompt, user_content)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                console.print(f"[yellow]warning: API call failed, retrying... ({e})[/yellow]")
                time.sleep(2)

    raise RuntimeError(
        f"API call failed after {MAX_RETRIES + 1} attempts: {last_error}"
    )


def review_code(
    files: list[dict],
    app_config: AppConfig,
    strict: bool = False,
    explain: bool = False,
    diff_mode: bool = False,
    language: str = "auto",
) -> list[Issue]:
    """Review files. Chunks large inputs, calls the LLM, parses results."""
    if not files:
        return []

    system_prompt = build_system_prompt(
        strict=strict,
        explain=explain,
        diff_mode=diff_mode,
        language=language,
    )

    chunks = chunk_files(files)
    all_issues: list[Issue] = []
    has_error = False

    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            console.print(
                f"[dim]  scanning chunk {i + 1}/{len(chunks)}...[/dim]"
            )

        user_msg = "Review the following code:\n\n" + chunk
        try:
            raw = _call_llm(app_config, system_prompt, user_msg)
            issues = _parse_issues(raw)
            all_issues.extend(issues)
        except RuntimeError as e:
            console.print(f"[red]error: {e}[/red]")
            has_error = True

    if has_error and not all_issues:
        raise RuntimeError("Review failed, could not reach the API.")

    return all_issues


def review_diff(
    diff_text: str,
    app_config: AppConfig,
    strict: bool = False,
    explain: bool = False,
    language: str = "auto",
) -> list[Issue]:
    """Review a git diff string."""
    system_prompt = build_system_prompt(
        strict=strict,
        explain=explain,
        diff_mode=True,
        language=language,
    )

    user_msg = "Review the following git diff:\n\n" + diff_text

    try:
        raw = _call_llm(app_config, system_prompt, user_msg)
        return _parse_issues(raw)
    except RuntimeError as e:
        console.print(f"[red]error: {e}[/red]")
        raise
