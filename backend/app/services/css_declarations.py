"""Split author declarations without breaking strings or functional values."""
from __future__ import annotations


def split_css_declarations(value: str) -> list[str]:
    declarations: list[str] = []
    start = 0
    depth = 0
    quote = ""
    escaped = False
    comment = False
    index = 0
    while index < len(value):
        char = value[index]
        following = value[index:index + 2]
        if comment:
            if following == "*/":
                comment = False
                index += 2
                continue
        elif escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif quote:
            if char == quote:
                quote = ""
        elif following == "/*":
            comment = True
            index += 2
            continue
        elif char in {"'", '"'}:
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == ";" and not depth:
            declarations.append(value[start:index])
            start = index + 1
        index += 1
    declarations.append(value[start:])
    return declarations
