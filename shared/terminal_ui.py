"""Shared, accessible terminal presentation for BIS and BRNS.

Rich styles are used only on an interactive terminal. Redirected output and
test captures remain ordinary text, including the same labels and numbering.
"""

import re
import sys

from rich.console import Console
from rich.rule import Rule
from rich.text import Text


COLORS = {
    "brand": "bold cyan3",
    "user": "bold deep_sky_blue3",
    "heading": "bold cyan",
    "prompt": "#d9a5c5",
    "match": "bold green",
    "alternative": "bold yellow",
    "bypass": "bold dark_orange",
    "help": "bold green",
    "success": "green",
    "warning": "yellow",
    "error": "bold red",
    "label": "cyan",
    "muted": "dim",
    "body": "",
}

_color_enabled = True


def set_color_enabled(enabled):
    """Apply one account's saved terminal preference to this process."""
    global _color_enabled
    _color_enabled = bool(enabled)


def colors_enabled():
    return _color_enabled


def _console():
    # Create a console at the point of use so stdout capture and redirection work.
    return Console(file=sys.stdout, highlight=False, markup=False,
                   soft_wrap=True)


def _interactive():
    return _color_enabled and sys.stdout.isatty()


def _content(value, role, highlight_commands=False):
    """Style semantic text; highlight all commands on help pages."""
    value = str(value)
    rendered = Text(value, style=COLORS[role])
    pattern = (r"(?<!\w)/[a-z][a-z-]*\b" if highlight_commands
               else r"/help\b")
    for match in re.finditer(pattern, value):
        rendered.stylize(COLORS["help"], match.start(), match.end())
    return rendered


def line(value="", role="body", highlight_commands=False):
    """Print one styled line, with identical plain text when redirected."""
    value = str(value)
    if _interactive():
        _console().print(_content(value, role, highlight_commands))
    else:
        print(value)


def message(value, role="body"):
    """Display a BiteFinder message with a consistent colored prefix."""
    value = str(value)
    if _interactive():
        rendered = Text()
        rendered.append("BiteFinder: ", style=COLORS["brand"])
        rendered.append(_content(value, role))
        _console().print(rendered)
    else:
        print(f"BiteFinder: {value}")


def section(title, role="heading"):
    """Mark a new part of the conversation or a result category."""
    if _interactive():
        _console().print()
        _console().print(Rule(title, style=COLORS[role]))
    else:
        print(f"\nBiteFinder: {title}")


def field(label, value, indent=2, role="body"):
    """Print a labeled fact, retaining a useful text form in logs."""
    prefix = " " * indent
    if _interactive():
        rendered = Text(prefix)
        rendered.append(f"{label}: ", style=COLORS["label"])
        rendered.append(_content(value, role))
        _console().print(rendered)
    else:
        print(f"{prefix}{label}: {value}")


def item(number, value, indent=2, role="body"):
    prefix = " " * indent
    if _interactive():
        rendered = Text(prefix)
        rendered.append(f"{number}. ", style=COLORS["label"])
        rendered.append(_content(value, role))
        _console().print(rendered)
    else:
        print(f"{prefix}{number}. {value}")


def read_input(prompt):
    """Color only the prompt; preserve Python input behavior and /help flow."""
    if _interactive():
        if prompt.startswith("You:"):
            rendered = Text()
            rendered.append("You:", style=COLORS["user"])
            rendered.append(_content(prompt[4:], "user"))
        else:
            rendered = _content(prompt, "prompt")
        _console().print(rendered, end="")
        return input()
    return input(prompt)
