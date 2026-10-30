# SPDX-FileCopyrightText: © 2022 Foundation Devices, Inc. <hello@foundation.xyz>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# dice_entropy_page.py - Collect user-supplied dice rolls (keys 1-6) as additional
#                        entropy to be mixed into a newly generated seed.

import lvgl as lv
from pages import Page
from styles import Stylize
from styles.colors import TEXT_GREY, FD_BLUE
from styles.font_sizes import FONT_SMALL
from views import Label
from keys import KEY_1, KEY_6
import microns
import common

from public_constants import DICE_BITS_PER_ROLL_MILLI as BITS_PER_ROLL_MILLI

# Hard cap so the roll string can't grow without bound on-device
MAX_DICE_ROLLS = 256


class DiceEntropyPage(Page):
    """Lets the user type dice rolls with the 1-6 keys.

    * Keys 1-6 append a roll.  All other digit keys are ignored.
    * Backspace (the '*' key) removes the last roll.
    * Right select (checkmark) finishes and returns the roll string.
    * Left select (back) cancels and returns None.
    """

    def __init__(self,
                 rolls='',
                 card_header=None,
                 statusbar=None,
                 left_micron=microns.Back,
                 right_micron=microns.Checkmark):
        super().__init__(card_header=card_header,
                         statusbar=statusbar,
                         left_micron=left_micron,
                         right_micron=right_micron)

        self.rolls = rolls

        with Stylize(self) as default:
            default.pad_row(6)
            default.pad(left=8, right=8)

        self.title_view = Label(text='Roll a die and press the\nmatching key (1-6).\nSelect the checkmark when done.',
                                color=TEXT_GREY, center=True)
        self.title_view.set_width(lv.pct(100))
        self.add_child(self.title_view)

        self.counter_view = Label(text='', color=FD_BLUE, center=True)
        self.counter_view.set_width(lv.pct(100))
        self.add_child(self.counter_view)

        self.rolls_view = Label(text='', color=TEXT_GREY, font=FONT_SMALL, center=True,
                                long_mode=lv.label.LONG.WRAP)
        self.rolls_view.set_width(lv.pct(100))
        self.add_child(self.rolls_view)

        self.update_views()

    def bits(self):
        return (len(self.rolls) * BITS_PER_ROLL_MILLI) // 1000

    def update_views(self):
        n = len(self.rolls)
        self.counter_view.set_text('{} roll{}  ~{} bits'.format(n, '' if n == 1 else 's', self.bits()))

        # Group rolls in blocks of 5 for readability; show only the tail if it gets long
        shown = self.rolls
        if len(shown) > 100:
            shown = '...' + shown[-100:]
        grouped = ' '.join(shown[i:i + 5] for i in range(0, len(shown), 5))
        self.rolls_view.set_text(grouped)

    def right_action(self, is_pressed):
        if not is_pressed:
            self.set_result(self.rolls)

    def left_action(self, is_pressed):
        if not is_pressed:
            self.set_result(None)

    def attach(self, group):
        super().attach(group)
        group.add_obj(self.lvgl_root)
        common.keypad.set_intercept_key_cb(self.on_key)

    def detach(self):
        common.keypad.set_intercept_key_cb(None)
        lv.group_remove_obj(self.lvgl_root)
        super().detach()

    def on_key(self, key, pressed):
        if not pressed:
            return

        # Hardware delivers the '*' key as lv.KEY.BACKSPACE; the desktop simulator's
        # keypad shim delivers the raw '*' character instead, so accept both.
        if key == lv.KEY.BACKSPACE or key == ord('*'):
            if len(self.rolls) > 0:
                self.rolls = self.rolls[:-1]
                self.update_views()
            return

        if KEY_1 <= key <= KEY_6:
            if len(self.rolls) < MAX_DICE_ROLLS:
                self.rolls += chr(key)
                self.update_views()
            return

        # Ignore 0, 7, 8, 9, arrows, and everything else
