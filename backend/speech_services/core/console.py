"""
Console utility functions for CodeWhisper
"""


def preview_text(text: str, max_length: int = 120) -> str:
    """Preview text with truncation if needed"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def info(message: str) -> None:
    """Print info message"""
    print(f"ℹ️  {message}")


def debug(message: str) -> None:
    """Print debug message"""
    print(f"🔍 {message}")


def warn(message: str) -> None:
    """Print warning message"""
    print(f"⚠️  {message}")
