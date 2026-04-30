"""Utilities for AI Weekly task framework."""

import os
import re
import logging
import string
from pathlib import Path

logger = logging.getLogger(__name__)

MD_CODE_BLOCK_PATTERN = r"```(?:markdown)?\s*\n([\s\S]*?)```"


def get_task_result(chat_history: list, name: str) -> str:
    """Extract the last result from a specific agent in chat history."""
    for obj in chat_history[::-1]:
        if obj.get('name') == name:
            return obj['content']
    raise ValueError(f"Agent '{name}' not found in chat history")


def format_prompt(template: str, **kwargs) -> str:
    """Format a prompt template with named parameters."""
    try:
        result = template.format(**kwargs)
        logger.debug("Formatted prompt with keys: %s", list(kwargs.keys()))
        return result
    except KeyError as e:
        logger.error("Missing prompt placeholder: %s", e)
        raise ValueError(f"Missing required prompt placeholder: {e}")


def format_prompt_safe(template: str, **kwargs) -> str:
    """Like format_prompt but leaves unfilled placeholders intact."""

    class SafeDict(dict):
        def __missing__(self, key):
            return '{' + key + '}'

    formatter = string.Formatter()
    return formatter.vformat(template, (), SafeDict(**kwargs))


def extract_markdown_content(text: str) -> str:
    """Extract markdown content from code blocks."""
    match = re.search(MD_CODE_BLOCK_PATTERN, text)
    if match:
        return match.group(1).strip()
    return text.strip()


def create_work_dir(work_dir: str | Path, name: str) -> Path:
    """Create stage-specific working directory."""
    work_dir = os.path.join(str(work_dir), f"{name}_generation_output")
    os.makedirs(work_dir, exist_ok=True)
    return Path(work_dir)


def extract_clean_markdown(text: str) -> str:
    """Extract markdown from code blocks and strip HTML comments."""
    MD_CLEAN_PATTERN = r"```[ \t]*(?:markdown)[ \t]*\r?\n(.*)\r?\n[ \t]*```"
    matches = re.findall(MD_CLEAN_PATTERN, text, flags=re.DOTALL)
    if matches:
        extracted = matches[0]
        clean = re.sub(r'^<!--.*?-->\s*\n', '', extracted)
        return clean
    return text.strip()


def input_check(str_input: str) -> str:
    """Check if input is string content or path to .md file."""
    if str_input.endswith(".md"):
        with open(str_input, 'r') as f:
            return f.read()
    elif isinstance(str_input, str):
        return str_input
    else:
        raise ValueError("Input must be a string or a path to a markdown file.")


def extract_file_paths(content: str) -> list[str]:
    """Extract file paths from content."""
    path_pattern = r'(?:/[\w./-]+)'
    return re.findall(path_pattern, content)


def check_file_paths(content: str) -> None:
    """Validate file paths are absolute and exist."""
    paths = extract_file_paths(content)
    for p in paths:
        if not os.path.isabs(p):
            raise ValueError(
                f"File path '{p}' is not absolute. Use absolute paths to avoid hallucination risk."
            )
        if not os.path.exists(p):
            raise FileNotFoundError(
                f"File path '{p}' does not exist. Verify data paths to avoid hallucination risk."
            )
