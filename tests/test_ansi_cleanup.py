from __future__ import annotations
import pytest
from cli_runner.utils import strip_ansi

def test_strip_ansi_colors():
    raw = "\x1b[31mRed Text\x1b[0m"
    assert strip_ansi(raw) == "Red Text"

def test_strip_ansi_cursor_movement():
    raw = "Hello\x1b[2J\x1b[HWorld"
    assert strip_ansi(raw) == "HelloWorld"

def test_strip_carriage_return():
    raw = "Line 1\rLine 1 overwrites?"
    # Our current implementation removes \r entirely
    assert strip_ansi(raw) == "Line 1Line 1 overwrites?"

def test_strip_other_control_chars():
    # Null byte, Bell, etc. should be stripped
    raw = "Normal\x00\x07Text"
    assert strip_ansi(raw) == "NormalText"

def test_keep_tab_and_newline():
    raw = "Tab\tNewline\nEnd"
    # We keep \t and \n
    assert strip_ansi(raw) == "Tab\tNewline\nEnd"


def test_non_string_input():
    assert strip_ansi(123) == "123"
    assert strip_ansi(None) == "None"


def test_strip_ansi_osc_leak():
    # OSC sequence for setting window title should not leak '0;Title'
    raw = "\x1b]0;My Title\x07Hello"
    assert strip_ansi(raw) == "Hello"


def test_strip_ansi_character_set_leak():
    # \x1b(B -> Select character set should not leak '(B'
    raw = "\x1b(BWorld"
    assert strip_ansi(raw) == "World"


def test_strip_ansi_bytes_direct():
    # Now that strip_ansi handles bytes directly via decode
    data = b"\x1b[31mRed Text\x1b[0m"
    assert strip_ansi(data) == "Red Text"


def test_strip_ansi_bytes_with_osc():
    # Test OSC sequence in bytes
    data = b"\x1b]0;Title\x07Hello"
    assert strip_ansi(data) == "Hello"
