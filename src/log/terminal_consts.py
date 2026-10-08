from frozendict import frozendict

from src.core.structs import BiFrozenDict

ANSI_COLORS: frozendict[str, str] = frozendict({
    "black": "[1;30;49m",
    "red": "[1;31;49m",
    "magenta": "[1;95;49m",
    "green": "[1;92m",
    # "purple_violet_and_magenta": "[1;38;5;93m",
    # "blue": "[1;94;49m",
    # "cyan": "[1;96;49m",
    # --
    "dark_yellow": "[1;38;2;225;185;70m",
    # "dark_cyan": "[1;104m",
    # --
    "container_orange": "[1;38;5;208;51m",
    "container_blue": "[1;94;51m",
    "container_black": "[1;51m",
    "container_purple_violet_and_magenta": "[1;51;38;5;93m",
    "container_bright_cyan": "[1;30;106m",
    # --
    "background_gray": "[1;97;100m",
    "background_green": "[1;30;102m",
    "background_yellow": "[1;30;48;5;220m",
    "background_dark_blue": "[1;30;48;5;20m",
    "background_bright_orange": "[1;30;48;5;208m",
    "background_red": "[1;30;101m",
    "background_cyan": "[1;30;48;5;6m",
    "background_magenta": "[1;30;105m",
    "background_black": "[1;97;40m",
    # --
    "underlined_black": "[1;4;30;49m",
})

LOGGING_LEVELS: BiFrozenDict[str, int] = BiFrozenDict({
    'debug': 10,
    'test': 15,
    'note': 20,
    'dump': 25,
    # --
    'external': 35,
    'system': 40,
    'memory': 45,
    'io': 50,
    # --
    'metric': 55,
    'notify': 60,
    'info': 65,
    'core': 70,
    # --
    'warning': 75,
    'attention': 80,
    'exception': 85,
    # --
    'error': 90,
    'critical': 95,
    'panic': 100,
    'fatal': 105
})

ANSI_COLORED_TERMINAL_LOGGING_LEVELS: frozendict[str, str] = frozendict({
    'debug': "black",
    'test': "dark_yellow",
    'note': "red",
    'dump': "background_gray",
    # --
    'external': "container_orange",
    'system': "container_blue",
    'memory': "container_black",
    'io': "container_purple_violet_and_magenta",
    # --
    'metric': "background_green",
    'notify': "magenta",
    'info': "green",
    'core': "container_bright_cyan",
    # --
    'warning': "background_yellow",
    'attention': "background_dark_blue",
    'exception': "background_bright_orange",
    # --
    'error': "background_red",
    'critical': "background_cyan",
    'panic': "background_magenta",
    'fatal': "background_black"
})

TERMINAL_RESET: str = "[0m"
ANSI_SEQUENCE_ESC = "\x1b"
