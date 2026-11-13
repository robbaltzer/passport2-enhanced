# SPDX-FileCopyrightText: © 2026 Rob Baltzer
# SPDX-License-Identifier: GPL-3.0-or-later
#
# generate_seed_words_flow.py - Generate a seed phrase and display it without storing it.
#
# Uses the same entropy as New Seed: new_seed_task reads all three hardware sources
# (avalanche noise, MCU RNG and secure element) and hashes them with SHA-256. The
# result is converted to BIP-39 words and shown once. Nothing is written to the
# secure element, settings or microSD, and the flow has no settings_key, so its
# state is never saved either.

from flows import Flow
from pages import ErrorPage, SuccessPage, YesNoChooserPage
from tasks import new_seed_task
from utils import spinner_task, get_words_from_seed
import lvgl as lv
import microns


class GenerateSeedWordsFlow(Flow):
    def __init__(self):
        super().__init__(initial_state=self.show_intro, name='GenerateSeedWordsFlow')
        self.seed_length = None
        self.words = None
        self.error = None

    async def show_intro(self):
        text = 'Create a new seed phrase that is displayed once. It is not saved on this Passport.'
        result = await YesNoChooserPage(text=text,
                                        yes_text='Continue',
                                        no_text='Back',
                                        icon=lv.LARGE_ICON_SEED,
                                        left_micron=microns.Back).show()
        if result:
            self.goto(self.pick_length)
        else:
            self.set_result(False)

    async def pick_length(self):
        from public_constants import SEED_LENGTHS
        from pages import ChooserPage

        options = [{'label': '{} Words'.format(length), 'value': length} for length in SEED_LENGTHS]
        self.seed_length = await ChooserPage(card_header={'title': 'Seed Length'}, options=options).show()
        if not self.seed_length:
            self.back()
        else:
            self.goto(self.generate_words)

    async def generate_words(self):
        (seed, error) = await spinner_task('Generating Seed', new_seed_task, args=[self.seed_length])
        if error is None:
            (self.words, error) = get_words_from_seed(seed)
        # Drop the entropy as soon as the words exist. (This does not scrub memory;
        # MicroPython offers no reliable way to zero these buffers.)
        seed = None

        if error is not None:
            self.error = error
            self.goto(self.show_error)
        else:
            self.goto(self.show_words)

    async def show_words(self):
        from pages import SeedWordsListPage

        # No Back here: going back would mean generating a different phrase, so the
        # only way out is the checkmark once the words have been written down.
        result = False
        while not result:
            result = await SeedWordsListPage(words=self.words).show()

        self.words = None
        self.goto(self.show_done)

    async def show_done(self):
        await SuccessPage(text='Seed words cleared from the screen. Nothing was saved.').show()
        self.set_result(True)

    async def show_error(self):
        await ErrorPage(text='Unable to generate seed: {}'.format(self.error)).show()
        self.set_result(False)
