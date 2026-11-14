# SPDX-FileCopyrightText: © 2026 Rob Baltzer
# SPDX-License-Identifier: GPL-3.0-or-later
#
# test_generate_seed_words.py - GenerateSeedWordsFlow: the words come from the same
#                               hardware entropy as New Seed, and nothing is stored.
#
# Runs the real flow inside the Unix MicroPython runtime (real trezorcrypto) via the
# headless fixture, with the pages and spinner stubbed. Build the simulator first:
# `just simulator/build color`.
from fixtures.headless import headless  # noqa: F401

SETUP = r'''
import lvgl as lv
lv.init()
import common, trezorcrypto, uasyncio

HW = bytes(range(32))  # deterministic stand-in for the avalanche/MCU/SE bytes

class FakeNoise:
    ALL = 7
    def __init__(self, ok=True):
        self.ok = ok
        self.sources = []
    def random_bytes(self, buf, src):
        self.sources.append(src)
        for i in range(len(buf)):
            buf[i] = HW[i]
        return self.ok

calls = {'saved': 0, 'settings_writes': 0, 'shown': [], 'messages': []}

# Anything that could persist a seed or a setting is counted; the flow must touch none.
import tasks
async def counting_save_seed_task(*args, **kwargs):
    calls['saved'] += 1
tasks.save_seed_task = counting_save_seed_task
def counted_settings_write(*args, **kwargs):
    calls['settings_writes'] += 1
if getattr(common, 'settings', None) is not None:
    for name in ('set', 'save', 'set_volatile'):
        if hasattr(common.settings, name):
            setattr(common.settings, name, counted_settings_write)

import pages
import flows.generate_seed_words_flow as gswf
from flows.generate_seed_words_flow import GenerateSeedWordsFlow

async def fake_spinner(text, task, args=(), **kwargs):
    out = []
    async def done(*result):
        out.append(result)
    await task(done, *args)
    return out[0]
gswf.spinner_task = fake_spinner

# Each page pops its answer from `script`: True/False for Continue/Back on the
# intro; a word count or None for the length chooser; 'dice', 'skip' or None for the
# dice question; a roll string or 'back' for dice entry; True/False for the dice
# confirmation; True/False for the words page.
script = []
class FakeYesNo:
    def __init__(self, **kwargs): pass
    async def show(self): return script.pop(0)
class FakeChooser:
    def __init__(self, **kwargs): pass
    async def show(self): return script.pop(0)
class FakeWords:
    def __init__(self, words=None, **kwargs): self.words = words
    async def show(self):
        calls['shown'].append(list(self.words))
        return script.pop(0)
class FakeMessage:
    def __init__(self, text=None, **kwargs): calls['messages'].append(text)
    async def show(self): return True
class FakeDice:
    def __init__(self, rolls='', **kwargs):
        self.rolls = rolls
        calls.setdefault('dice_prefill', []).append(rolls)
    async def show(self):
        action = script.pop(0)
        if action == 'back':
            return None
        self.rolls = action
        return action
class FakeDiceConfirm:
    def __init__(self, text=None, **kwargs): calls.setdefault('dice_confirm', []).append(text)
    async def show(self): return script.pop(0)
gswf.YesNoChooserPage = FakeYesNo
gswf.SuccessPage = FakeMessage
gswf.ErrorPage = FakeMessage
pages.ChooserPage = FakeChooser
pages.SeedWordsListPage = FakeWords
pages.DiceEntropyPage = FakeDice
pages.LongQuestionPage = FakeDiceConfirm

def expected_words(length, rolls=''):
    h = trezorcrypto.sha256(HW)
    if rolls:
        h.update(rolls.encode())
    entropy = h.digest()[:(length // 3) * 4]
    return trezorcrypto.bip39.from_data(entropy).split(' ')

def run_flow(answers, noise_ok=True):
    common.noise = FakeNoise(noise_ok)
    script[:] = answers
    flow = GenerateSeedWordsFlow()
    result = uasyncio.run(flow.run())
    return flow, result
'''


def _run(headless, body):
    return eval(headless.exec(SETUP + body))


def test_twelve_words_come_from_all_hardware_sources(headless):
    out = _run(headless, r'''
flow, result = run_flow([True, 12, 'skip', True])
return_value.write(repr({
    'result': result,
    'shown': calls['shown'],
    'expected': expected_words(12),
    'sources': common.noise.sources,
    'saved': calls['saved'],
    'settings_writes': calls['settings_writes'],
    'words_dropped': flow.words is None,
    'left_over': script,
}).encode())
''')
    assert out['result'] is True
    assert len(out['shown']) == 1
    assert out['shown'][0] == out['expected']
    assert len(out['shown'][0]) == 12
    assert out['sources'] == [7]           # one read, from noise.ALL (all three sources)
    assert out['saved'] == 0
    assert out['settings_writes'] == 0
    assert out['words_dropped']
    assert out['left_over'] == []


def test_twenty_four_words(headless):
    out = _run(headless, r'''
flow, result = run_flow([True, 24, 'skip', True])
return_value.write(repr((result, calls['shown'], expected_words(24), calls['saved'])).encode())
''')
    result, shown, expected, saved = out
    assert result is True
    assert shown == [expected]
    assert len(expected) == 24
    assert saved == 0


def test_words_stay_until_checkmark(headless):
    """The words page has no Back; dismissing it without the checkmark shows the same words again."""
    out = _run(headless, r'''
flow, result = run_flow([True, 12, 'skip', False, False, True])
return_value.write(repr((result, calls['shown'])).encode())
''')
    result, shown = out
    assert result is True
    assert len(shown) == 3
    assert shown[0] == shown[1] == shown[2]


def test_back_out_before_generating_draws_no_entropy(headless):
    out = _run(headless, r'''
flow, result = run_flow([True, None, False])
return_value.write(repr((result, calls['shown'], common.noise.sources, script)).encode())
''')
    result, shown, sources, left_over = out
    assert result is False
    assert shown == []
    assert sources == []
    assert left_over == []


def test_hardware_entropy_failure_shows_error_and_no_words(headless):
    out = _run(headless, r'''
flow, result = run_flow([True, 12, 'skip'], noise_ok=False)
return_value.write(repr((result, calls['shown'], calls['messages'], calls['saved'])).encode())
''')
    result, shown, messages, saved = out
    assert result is False
    assert shown == []
    assert saved == 0
    assert len(messages) == 1
    assert 'Unable to gather hardware entropy' in messages[0]


def test_dice_rolls_are_mixed_in_like_new_seed(headless):
    """seed = SHA256(hw_entropy || rolls), the same derivation New Seed uses."""
    out = _run(headless, r'''
flow, result = run_flow([True, 12, 'dice', '6152433', True, True])
return_value.write(repr({
    'result': result,
    'shown': calls['shown'],
    'with_dice': expected_words(12, '6152433'),
    'hw_only': expected_words(12),
    'sources': common.noise.sources,
    'saved': calls['saved'],
    'settings_writes': calls['settings_writes'],
    'rolls_dropped': flow.dice_rolls is None,
    'confirm_shown': len(calls.get('dice_confirm', [])),
}).encode())
''')
    assert out['result'] is True
    assert out['shown'] == [out['with_dice']]
    assert out['with_dice'] != out['hw_only']
    assert out['sources'] == [7]           # hardware entropy is still always read
    assert out['saved'] == 0
    assert out['settings_writes'] == 0
    assert out['rolls_dropped']
    assert out['confirm_shown'] == 1


def test_back_from_dice_entry_keeps_rolls(headless):
    """Back from dice entry returns to the dice question; coming forward again restores the rolls."""
    out = _run(headless, r'''
flow, result = run_flow([True, 12, 'dice', 'back', 'dice', '1234', True, True])
return_value.write(repr((result, calls['dice_prefill'], calls['shown'], expected_words(12, '1234'))).encode())
''')
    result, prefill, shown, expected = out
    assert result is True
    assert prefill == ['', '']     # typed rolls are only kept by the real page; the stub types none
    assert shown == [expected]


def test_back_from_dice_confirmation_returns_to_entry(headless):
    out = _run(headless, r'''
flow, result = run_flow([True, 24, 'dice', '55', False, '5566', True, True])
return_value.write(repr((result, calls['dice_prefill'], calls['shown'], expected_words(24, '5566'))).encode())
''')
    result, prefill, shown, expected = out
    assert result is True
    assert prefill == ['', '55']   # confirmation Back pops to entry with the rolls preserved
    assert shown == [expected]


def test_skip_after_typing_rolls_uses_hardware_only(headless):
    """Rolls typed and then abandoned with Back must not leak into a later Skip."""
    out = _run(headless, r'''
flow, result = run_flow([True, 12, 'dice', '33', False, 'back', 'skip', True])
return_value.write(repr((result, calls['shown'], expected_words(12), calls['dice_prefill'])).encode())
''')
    result, shown, hw_only, prefill = out
    assert result is True
    assert shown == [hw_only]
    assert prefill == ['', '33']


def test_back_from_dice_question_returns_to_length(headless):
    out = _run(headless, r'''
flow, result = run_flow([True, 12, None, 24, 'skip', True])
return_value.write(repr((result, calls['shown'], expected_words(24), common.noise.sources)).encode())
''')
    result, shown, expected, sources = out
    assert result is True
    assert shown == [expected]
    assert sources == [7]
