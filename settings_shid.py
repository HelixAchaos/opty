import re
from pathlib import Path
import json

# import pyparsing

def parse_rule(line: str) -> tuple[str]:
    """
    just a parser for strings & escaped. (1) but with two flags: is_str and is_escaped; arrow notation handled too
    :param line:
    :return:
    """
    parts = [""]

    is_str = 0  # 0: no, 1: single, 2: double
    is_escaped = 0  # 0: not_escaped, 1: escaped

    arrow = 0  # 0: none, 1: -, 2: =

    for c in line:
        if c == '\\':
            if is_escaped == 1:
                is_escaped = 0
            else:
                is_escaped = 1
            continue
        elif c == "'":
            if is_str == 0:
                if is_escaped == 1:  # \'
                    raise Exception(f"How did \' get consumed when it's outside a string???\n\n\t{line=}")
                else:
                    is_str = 1  # '
            elif is_str == 1 and is_escaped == 0:  # '...'
                is_str = 0
            else:
                if is_str == 2 and is_escaped == 1:
                    pass
        elif c == '"':
            if is_str == 0:
                if is_escaped == 1:  # \'
                    raise Exception(f"How did \' get consumed when it's outside a string???\n\n\t{line=}")
                else:
                    is_str = 2  # '
            elif is_str == 2 and is_escaped == 0:  # '...'
                is_str = 0
            else:
                if is_str == 1 and is_escaped == 1:
                    pass

        if is_str == 0:
            if c == "=":
                arrow = 2
            elif c == "-":
                arrow = 1
            else:
                if c == '>' and arrow in (1, 2):
                    parts[-1] = parts[-1][:-1]
                    parts.append('')
                    continue
                arrow = 0

        if is_escaped == 1:
            is_escaped = 0

        parts[-1] += c

    return tuple(map(str.strip, parts))


def get_rules(config_path: str) -> tuple[dict, tuple[tuple[str], ...]]:
    with open(config_path, mode='r') as config_f:
        # gets rid of comments and empty lines bc ("" in "#" and "#" in "#")
        # lines = (line.rstrip('\n') for line in config_f if not line.startswith("#") and line != "")
        lines = (line.rstrip('\n') for line in config_f if line[:1] not in "#")
        separator = re.search(r'([\"\'])((\\{2})*|(.*?[^\\](\\{2})*))\1', next(lines).split('=')[1]).groups()[1]

        type_shorts = {}
        for line in iter(lines.__next__, separator):
            k, v = map(str.strip, line.split('='))
            type_shorts[k] = v

        print(f"{type_shorts=}")
        rules = tuple(map(parse_rule, lines))

    return type_shorts, rules


def get_targets(hit_list_path: str) -> tuple[Path]:
    with open(hit_list_path, mode='r') as hit_list_f:
        comment = '#'
        significant_lines = (stripped for line in hit_list_f if (stripped := line.strip()) and not stripped.startswith(comment))

        file_paths = set()
        root = Path('')
        for line in significant_lines:
            if '=' in line:
                root = Path(line.split('=')[1].strip())
                continue
            file_paths.add(root/line)

    return tuple(file_paths)


def get_settings(settings_file_path: str) -> dict[str, str | bool]:
    with open(settings_file_path, 'f') as f:
        return json.load(f)
