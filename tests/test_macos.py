import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from keyboard import KEYS, host_key
from machine import default_runtime


class Event:
    def __init__(self, keysym, char='', state=0, keycode=0):
        self.keysym = keysym
        self.char = char
        self.state = state
        self.keycode = keycode


class KeyboardTests(unittest.TestCase):
    def test_command_and_option_do_not_reach_guest(self):
        self.assertIsNone(host_key(Event('s', 's', state=0x8)))  # Command
        self.assertIsNone(host_key(Event('a', 'å', state=0x10)))  # Option

    def test_shifted_digits_map_to_number_row(self):
        for symbol, digit in zip('!@#$%^&*()', '1234567890'):
            with self.subTest(symbol=symbol):
                self.assertEqual(host_key(Event('', symbol)), KEYS[digit])

    def test_letters_arrows_and_keypad(self):
        self.assertEqual(host_key(Event('a', 'a')), KEYS['a'])
        self.assertEqual(host_key(Event('A', 'A')), KEYS['A'])
        self.assertEqual(host_key(Event('Prior')), KEYS['Prior'])
        self.assertEqual(host_key(Event('Next')), KEYS['Next'])
        self.assertEqual(host_key(Event('KP_Enter')), KEYS['Return'])

    def test_runtime_override_wins(self):
        with patch.dict(os.environ, {'BBK7980_RUNTIME': '/tmp/bbk7980-test'}):
            self.assertEqual(default_runtime(), Path('/tmp/bbk7980-test'))


if __name__ == '__main__':
    unittest.main()
