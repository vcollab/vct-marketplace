"""Lenient coercion for array-typed tool parameters.

Some MCP clients serialize an array tool-argument as a *string* (a JSON array like
``'["Displacement","Stress"]'`` or a plain comma/newline list like ``"Displacement, Stress"``)
instead of a real JSON array. Strict ``list[...]`` validation then rejects it. These
``BeforeValidator``s coerce such strings into lists, so both well-behaved and string-serializing
clients work. The declared type is unchanged, so the JSON schema still advertises an array.
"""

from __future__ import annotations

import json
import re
from typing import Annotated

from pydantic import BeforeValidator

_SPLIT_RE = re.compile(r"[,\n]")


def _coerce_str_list(value: object) -> object:
    """A list passes through; a JSON-array / comma / newline string becomes a list of strings."""
    if value is None or isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                parsed = json.loads(s)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        return [part.strip() for part in _SPLIT_RE.split(s) if part.strip()]
    return value  # let Pydantic reject anything else


def _coerce_float_list(value: object) -> object:
    """A list passes through; a JSON-array / comma / whitespace string becomes a list of floats."""
    if value is None or isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                parsed = json.loads(s)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                return parsed
        try:
            return [float(part) for part in re.split(r"[,\s]+", s) if part.strip()]
        except ValueError:
            return value  # let Pydantic surface a clear type error
    return value


# Optional list of strings (results/parts/instances, input/output path lists).
StrList = Annotated[list[str] | None, BeforeValidator(_coerce_str_list)]
# Required list of strings (e.g. caxmerge inputs).
RequiredStrList = Annotated[list[str], BeforeValidator(_coerce_str_list)]
# Optional list of floats (image background color).
FloatList = Annotated[list[float] | None, BeforeValidator(_coerce_float_list)]
