# SPDX-FileCopyrightText: © 2022 Foundation Devices, Inc. <hello@foundation.xyz>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# new_seed_flow.py - Create a new random seed

from flows import Flow
from pages import ErrorPage, QuestionPage, SuccessPage, YesNoChooserPage
from tasks import new_seed_task, save_seed_task
from utils import has_secrets, spinner_task
import lvgl as lv
import microns


class NewSeedFlow(Flow):
    def __init__(self, refresh_cards_when_done=False, autobackup=True, full_backup=False):
        super().__init__(initial_state=self.check_for_seed, name='NewSeedFlow')
        self.refresh_cards_when_done = refresh_cards_when_done
        self.autobackup = autobackup
        self.full_backup = full_backup
        self.seed_length = None
        self.skip_seed_prompt = False
        self.dice_rolls = None

    async def check_for_seed(self):
        # Ensure we don't overwrite an existing seed
        if has_secrets():
            await ErrorPage(text='Passport already has a seed!').show()
            self.set_result(False)
            return

        self.goto(self.pick_length)

    async def pick_length(self):
        from public_constants import SEED_LENGTHS
        from pages import ChooserPage

        options = []
        for length in SEED_LENGTHS:
            options.append({'label': '{} Words'.format(length), 'value': length})

        self.seed_length = await ChooserPage(card_header={'title': 'Seed Length'}, options=options).show()
        if not self.seed_length:
            self.set_result(False)
        else:
            self.goto(self.confirm_generate)

    async def confirm_generate(self):
        # result = await QuestionPage(text='Generate a new seed phrase now?').show()
        text = 'Passport will create and back up a new {}-word seed phrase.'.format(self.seed_length)
        result = await YesNoChooserPage(text=text,
                                        yes_text='Continue',
                                        no_text='Back',
                                        icon=lv.LARGE_ICON_INFO,
                                        left_micron=microns.Back).show()
        if result:
            self.goto(self.enter_dice)
        else:
            self.back()

    async def enter_dice(self):
        from pages import DiceEntropyPage

        page = DiceEntropyPage(rolls=self.dice_rolls or '',
                               target_rolls=self.target_rolls(),
                               card_header={'title': 'Dice Entropy'})
        rolls = await page.show()
        if rolls is None:
            # User backed out of dice entry: keep whatever was typed so far so it
            # is restored if the user comes forward again.
            self.dice_rolls = page.rolls or None
            self.back()
            return

        self.dice_rolls = rolls
        self.goto(self.confirm_dice)

    def target_rolls(self):
        # Enough fair d6 rolls (~2.585 bits each) to match the seed's own entropy:
        # 12 words = 128 bits -> 50 rolls, 24 words = 256 bits -> 100 rolls.
        from public_constants import DICE_BITS_PER_ROLL_MILLI
        seed_bits = (self.seed_length // 3) * 32
        return (seed_bits * 1000 + DICE_BITS_PER_ROLL_MILLI - 1) // DICE_BITS_PER_ROLL_MILLI

    async def confirm_dice(self):
        import trezorcrypto
        from pages import LongQuestionPage
        from utils import b2a_hex
        from public_constants import DICE_BITS_PER_ROLL_MILLI

        n = len(self.dice_rolls)
        bits = (n * DICE_BITS_PER_ROLL_MILLI) // 1000
        target = self.target_rolls()
        rolls_hash = b2a_hex(trezorcrypto.sha256(self.dice_rolls.encode()).digest()).decode()

        if n == 0:
            text = ('No dice rolls were entered.\n\nThe seed will be generated from '
                    'hardware entropy only. Continue?')
        else:
            # NOTE: this hash covers the dice rolls only. It lets the user confirm the
            # rolls were received exactly as typed; it does not reveal the hardware
            # entropy and so cannot be used to recompute the final seed.
            text = ('{} roll{} entered (~{} bits).\n\n'
                    'SHA-256 of rolls as typed:\n{}\n{}\n\n'
                    'Continue?').format(n, '' if n == 1 else 's', bits,
                                        rolls_hash[:32], rolls_hash[32:])
            if n < target:
                text = ('WARNING: Only {} roll{} (~{} bits). {} rolls are recommended to match '
                        'a {}-word seed.\n\n'
                        'SHA-256 of rolls as typed:\n{}\n{}\n\n'
                        'Continue anyway?').format(n, '' if n == 1 else 's', bits, target,
                                                   self.seed_length,
                                                   rolls_hash[:32], rolls_hash[32:])

        result = await LongQuestionPage(text=text,
                                        card_header={'title': 'Dice Entropy'},
                                        left_micron=microns.Back,
                                        right_micron=microns.Checkmark).show()
        if result:
            self.goto(self.generate_seed)
        else:
            # Go back to dice entry with rolls preserved so they can be edited
            self.goto(self.enter_dice)

    async def generate_seed(self):
        (seed, error) = await spinner_task('Generating Seed',
                                           new_seed_task,
                                           args=[self.seed_length, self.dice_rolls])
        if error is None:
            # Don't keep the rolls around any longer than necessary
            self.dice_rolls = None
            self.seed = seed
            self.goto(self.save_seed)
        else:
            self.error = error
            self.goto(self.show_error)

    async def save_seed(self):
        (error,) = await spinner_task('Saving Seed', save_seed_task, args=[self.seed])
        if error is None:
            self.goto(self.do_backup)
        else:
            self.error = 'Unable to save seed.'
            self.goto(self.show_error)

    async def do_backup(self):
        from flows import AutoBackupFlow, BackupFlow

        backup_flow = None

        if self.full_backup:
            backup_flow = BackupFlow(initial_backup=True)
        elif self.autobackup:
            backup_flow = AutoBackupFlow(offer=True)

        if backup_flow is None:
            self.goto(self.show_seed_words)
            return

        # Run whichever backup flow is used, and
        # determine if the seed can be skipped
        self.skip_seed_prompt = await backup_flow.run()
        self.goto(self.show_seed_words)

    async def show_seed_words(self):
        from flows import ViewSeedWordsFlow
        await ViewSeedWordsFlow(initial=True,
                                allow_skip=self.skip_seed_prompt).run()
        self.goto(self.show_success)

    async def show_success(self):
        import common

        await SuccessPage(text='New seed created and saved.').show()

        if self.refresh_cards_when_done:
            common.ui.full_cards_refresh()

            await self.wait_to_die()
        else:
            self.set_result(True)

    async def show_error(self):
        await ErrorPage(self.error).show()
        self.set_result(False)
