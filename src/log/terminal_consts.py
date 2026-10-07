from enum import Enum

from frozendict import frozendict

from src.core.structs import BiFrozenDict

ANSI_COLORS: frozendict[str, str] = frozendict({
    "black": "\x1b[1;90;107m",
    "bold_black": "\x1b[1;30;49m",
    "underlined_black": "\x1b[1;4;30;49m",
    "background_black": "\x1b[1;97;40m",
    "container_black": "\x1b[51m",
    "red": "\x1b[1;31;49m",
    "green": "\x1b[1;92;49m",
    "yellow": "\x1b[1;93;49m",
    "blue": "\x1b[1;94;49m",
    "magenta": "\x1b[1;95;49m",
    "cyan": "\x1b[1;96;49m",
    "orange": "\x1b[1;38;5;208;49m",
    "dark_cyan": "\x1b[1;38;5;30;49m",
    "background_gray": "\x1b[1;97;100m",
    "background_yellow": "\x1b[1;30;103m",
    "background_red": "\x1b[1;30;101m",
    "background_magenta": "\x1b[1;30;105m",
    "background_blue": "\x1b[1;30;104m",
    "background_green": "\x1b[1;30;102m",
    "background_cyan": "\x1b[1;97;106m",
    "background_orange": "\x1b[1;30;48;5;214m",
})


LOGGING_LEVELS: BiFrozenDict[str, int] = BiFrozenDict({
    'debug': 10,
    'test': 15,
    'note': 20,
    # --
    'external': 25,
    'notify': 30,
    'info': 35,
    'dump': 40,
    'core': 45,
    'system': 50,
    'warning': 55,
    'attention': 60,
    # --
    'exception': 65,
    'error': 70,
    'critical': 75,
    'panic': 80,
    'fatal': 85
})

ANSI_COLORED_TERMINAL_LOGGING_LEVELS: frozendict[str, str] = frozendict({
    'debug': "bold_black",
    'test': "yellow",
    'note': "cyan",
    # --
    'external': "orange",
    'notify': "dark_cyan",
    'info': "green",
    'dump': "background_cyan",
    'core': "background_gray",
    'system': "blue",
    'warning': "magenta",
    'attention': "red",
    # --
    'exception': "background_yellow",
    'error': "background_red",
    'critical': "background_blue",
    'panic': "background_magenta",
    'fatal': "background_black"
})

TERMINAL_RESET: str = "\x1b[0m"

