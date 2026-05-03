"""Shared Boolean-filter parser for image and tag filter line edits.

Provides a single source of truth for the operator framework (NOT, AND, OR,
implicit AND) so both the image-side and tag-side filters share semantics
while keeping their atom vocabularies distinct.
"""
from functools import reduce
from operator import or_

from pyparsing import (CaselessKeyword, OpAssoc, Optional, ParserElement,
                       QuotedString, Word, infix_notation, printables)


_RESERVED_WORDS = ('NOT', 'AND', 'OR')


def _reserved_word_lookahead() -> ParserElement:
    keywords = [CaselessKeyword(k) for k in _RESERVED_WORDS]
    return ~reduce(or_, keywords)


def optionally_quoted_string() -> ParserElement:
    """Atom for a bare or quoted string, excluding reserved operator words.

    Quoted forms (`"foo bar"`, `'foo bar'`) bypass the reserved-word check, so
    a user can still match the literal text "and"/"or"/"not" by quoting it.
    """
    return (QuotedString(quote_char='"', esc_char='\\')
            | QuotedString(quote_char="'", esc_char='\\')
            | (_reserved_word_lookahead()
               + Word(printables, exclude_chars='()')))


def replace_filter_wildcards(filter_):
    r"""Replace escaped wildcards (``\*``, ``\?``) with fnmatch-safe forms."""
    if isinstance(filter_, str):
        return filter_.replace(r'\*', '[*]').replace(r'\?', '[?]')
    if isinstance(filter_, list):
        return [replace_filter_wildcards(element) for element in filter_]
    return filter_


def build_boolean_parser(atom_expression: ParserElement) -> ParserElement:
    """Wrap an atom-level grammar with NOT / (implicit-or-explicit) AND / OR.

    Precedence (tightest → loosest): NOT, AND/implicit, OR. The implicit-AND
    level uses ``Optional(CaselessKeyword('AND'), default='AND')`` so adjacent
    operands without an explicit operator parse as conjunction; the parsed
    output always materializes ``'AND'`` between operands.
    """
    return infix_notation(
        atom_expression,
        [
            (CaselessKeyword('NOT'), 1, OpAssoc.RIGHT),
            (Optional(CaselessKeyword('AND'), default='AND'),
             2, OpAssoc.LEFT),
            (CaselessKeyword('OR'), 2, OpAssoc.LEFT),
        ],
    )


def format_ast(parsed) -> str:
    """Render a parsed filter tree as an indented Unicode tree."""
    lines: list[str] = []
    _render(parsed, prefix='', is_last=True, is_root=True, lines=lines)
    return '\n'.join(lines)


def _render(node, prefix: str, is_last: bool, is_root: bool,
            lines: list[str]) -> None:
    label, children = _structure(node)
    if is_root:
        lines.append(label)
        child_prefix = ''
    else:
        connector = '└── ' if is_last else '├── '
        lines.append(prefix + connector + label)
        child_prefix = prefix + ('    ' if is_last else '│   ')
    for i, child in enumerate(children):
        _render(child, child_prefix, i == len(children) - 1, False, lines)


def _structure(node) -> tuple[str, list]:
    """Return (label, children_to_render). Empty children → leaf row."""
    if not isinstance(node, list):
        return (_format_atom(node), [])
    if len(node) == 2 and node[0] == 'NOT':
        child = node[1]
        if _is_simple(child):
            return (f'NOT {_format_atom(child)}', [])
        return ('NOT', [child])
    if (len(node) >= 3 and isinstance(node[1], str)
            and node[1] in ('AND', 'OR')):
        return (node[1], list(node[::2]))
    return (_format_atom(node), [])


def _is_simple(node) -> bool:
    """True if ``node`` renders to a single line (atom or NOT-of-simple)."""
    if not isinstance(node, list):
        return True
    if len(node) == 2 and node[0] == 'NOT':
        return _is_simple(node[1])
    if len(node) == 2:
        return True
    if len(node) == 3 and node[1] not in ('AND', 'OR'):
        return True
    return False


def _format_atom(atom) -> str:
    if isinstance(atom, str):
        return f'"{atom}"' if (' ' in atom or not atom) else atom
    if isinstance(atom, list):
        if len(atom) == 2 and atom[0] == 'NOT':
            return f'NOT {_format_atom(atom[1])}'
        if len(atom) == 2:
            key, value = atom
            value_str = str(value)
            if ' ' in value_str:
                value_str = f'"{value_str}"'
            return f'{key}:{value_str}'
        if len(atom) == 3:
            key, op, value = atom
            return f'{key}{op}{value}'
    return str(atom)
