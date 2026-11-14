# SPDX-FileCopyrightText: © 2026 Rob Baltzer
# SPDX-License-Identifier: GPL-3.0-or-later
#
# generate_seed_words_flow.py - Generate a seed phrase and display it without storing it.
#
# Uses the same entropy as New Seed: new_seed_task reads all three hardware sources
# (avalanche noise, MCU RNG and secure element) and hashes them with SHA-256, with
# optional dice rolls appended: seed = SHA256(hw_entropy || rolls). The result is
# converted to BIP-39 words and shown once. Nothing is written to the secure element,
# settings or microSD, and the flow has no settings_key, so its state is never saved.

from flows import Flow
from flows.new_seed_flow import NewSeedFlow
from pages import ErrorPage, SuccessPage, YesNoChooserPage
from tasks import new_seed_task
from utils import spinner_task, get_words_from_seed
import lvgl as lv
import microns


class GenerateSeedWordsFlow(Flow):
    # Dice entry and confirmation are New Seed's own states, so both flows behave
    # identically. They rely on self.seed_length and self.dice_rolls, and on this flow
    # having a generate_seed state to continue to.
    enter_dice = NewSeedFlow.enter_dice
    confirm_dice = NewSeedFlow.confirm_dice
    target_rolls = NewSeedFlow.target_rolls

    def __init__(self):
        super().__init__(initial_state=self.show_intro, name='GenerateSeedWordsFlow')
        self.seed_length = None
        self.dice_rolls = None
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
            self.goto(self.ask_dice)

    async def ask_dice(self):
        from pages import ChooserPage

        text = 'Add your own dice rolls? Hardware entropy is always used; dice are optional.'
        options = [{'label': 'Add Dice Rolls', 'value': 'dice'},
                   {'label': 'Skip', 'value': 'skip'}]
        choice = await ChooserPage(text=text,
                                   icon=lv.LARGE_ICON_INFO,
                                   options=options,
                                   left_micron=microns.Back).show()
        if choice is None:
            self.back()
        elif choice == 'dice':
            self.goto(self.enter_dice)
        else:
            # Skipping means hardware entropy only, even if rolls were typed earlier.
            self.dice_rolls = None
            self.goto(self.generate_seed)

    async def generate_seed(self):
        (seed, error) = await spinner_task('Generating Seed', new_seed_task, args=[self.seed_length, self.dice_rolls])
        if error is None:
            (self.words, error) = get_words_from_seed(seed)
        # Drop the entropy and rolls as soon as the words exist. (This does not scrub
        # memory; MicroPython offers no reliable way to zero these buffers.)
        seed = None
        self.dice_rolls = None

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
