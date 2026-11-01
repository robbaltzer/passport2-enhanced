# SPDX-FileCopyrightText: © 2026 Rob Baltzer
# SPDX-License-Identifier: GPL-3.0-or-later
#
# test_dice_entropy.py - Deterministic vectors for dice-roll entropy mixing in
#                        new_seed_task, plus DiceEntropyPage input handling.
#
# Runs inside the real Unix MicroPython runtime (real trezorcrypto) via the
# headless fixture. Build the simulator first: `just simulator/build color`.

import hashlib

from fixtures.headless import headless  # noqa: F401

HW = bytes(range(32))  # deterministic stand-in for the avalanche/MCU/SE bytes


SETUP = r'''
import common, trezorcrypto, uasyncio
from ubinascii import hexlify

class FakeNoise:
    ALL = 7
    def random_bytes(self, buf, src):
        for i in range(len(buf)):
            buf[i] = HW[i]
HW = bytes(range(32))
common.noise = FakeNoise()

from tasks.new_seed_task import new_seed_task

def gen(seed_length, rolls=None):
    out = {}
    async def done(seed, err):
        out['seed'] = seed; out['err'] = err
    uasyncio.run(new_seed_task(done, seed_length, rolls))
    assert out['err'] is None, out['err']
    return hexlify(out['seed']).decode()
'''


def _run(headless, body):
    return headless.exec(SETUP + body)


def _expected(rolls, seed_length):
    digest = hashlib.sha256(HW + rolls.encode()).hexdigest()
    return digest[: (seed_length // 3) * 4 * 2]


def test_hardware_only_matches_stock_derivation(headless):
    """No dice -> SHA256(hw) truncated, byte-identical to original firmware."""
    out = _run(headless, "return_value.write(gen(24).encode())")
    assert out == hashlib.sha256(HW).hexdigest()
    out = _run(headless, "return_value.write(gen(12).encode())")
    assert out == hashlib.sha256(HW).hexdigest()[:32]


def test_empty_rolls_equals_hardware_only(headless):
    out = _run(headless, "return_value.write((gen(24, '') + ' ' + gen(24)).encode())")
    a, b = out.split()
    assert a == b


def test_dice_mixed_as_sha256_hw_concat_rolls(headless):
    for rolls in ('123456', '1' * 50, '654321' * 16 + '6543'):  # 6, 50, 100 rolls
        for seed_length in (12, 24):
            out = _run(headless, "return_value.write(gen(%d, %r).encode())" % (seed_length, rolls))
            assert out == _expected(rolls, seed_length), (rolls, seed_length)


def test_same_hw_different_dice_differ(headless):
    out = _run(headless, "return_value.write((gen(12, '111111') + ' ' + gen(12, '111112')).encode())")
    a, b = out.split()
    assert a != b


def test_different_hw_same_dice_differ(headless):
    body = r'''
a = gen(24, '123456')
HW2 = bytes(31) + b'\x01'
class FakeNoise2:
    ALL = 7
    def random_bytes(self, buf, src):
        for i in range(len(buf)):
            buf[i] = HW2[i]
common.noise = FakeNoise2()
b = gen(24, '123456')
return_value.write((a + ' ' + b).encode())
'''
    a, b = _run(headless, body).split()
    assert a != b


def test_twelve_words_is_prefix_of_twenty_four(headless):
    out = _run(headless, "return_value.write((gen(12, '123456') + ' ' + gen(24, '123456')).encode())")
    a, b = out.split()
    assert b.startswith(a) and len(a) == 32 and len(b) == 64


PAGE_SETUP = r'''
import lvgl as lv
lv.init()
from pages import DiceEntropyPage
from keys import KEY_0, KEY_1, KEY_6, KEY_7, KEY_9

def press(p, k):
    p.on_key(k, True); p.on_key(k, False)
'''


def test_page_accepts_only_one_to_six(headless):
    out = headless.exec(PAGE_SETUP + r'''
p = DiceEntropyPage()
for k in (KEY_1, KEY_6, KEY_0, KEY_7, KEY_9, KEY_1 + 2, lv.KEY.UP, lv.KEY.LEFT):
    press(p, k)
return_value.write(p.rolls.encode())
''')
    assert out == '163'


def test_page_backspace_and_release_handling(headless):
    out = headless.exec(PAGE_SETUP + r'''
p = DiceEntropyPage(rolls='16')
press(p, lv.KEY.BACKSPACE)
a = p.rolls
press(p, lv.KEY.BACKSPACE); press(p, lv.KEY.BACKSPACE)
b = p.rolls
p.on_key(KEY_1, False)   # release alone must do nothing
c = p.rolls
return_value.write(repr((a, b, c)).encode())
''')
    assert eval(out) == ('1', '', '')


def test_page_cap_and_counter(headless):
    out = headless.exec(PAGE_SETUP + r'''
p = DiceEntropyPage(target_rolls=50)
for i in range(300):
    press(p, KEY_1 + (i % 6))
cap = (len(p.rolls), p.counter_view.text)
lo = DiceEntropyPage(rolls='1'*49, target_rolls=50).counter_view.text
hi = DiceEntropyPage(rolls='1'*50, target_rolls=50).counter_view.text
bits99 = DiceEntropyPage(rolls='1'*99).bits()
return_value.write(repr((cap, lo, hi, bits99, p.extend_timeout)).encode())
''')
    (n, cap_text), lo, hi, bits99, ext = eval(out)
    assert n == 256 and '(max)' in cap_text
    assert lo == '49 rolls  ~126 bits / 50'
    assert hi.startswith('#00bb00 ') and '50 rolls  ~129 bits / 50' in hi
    assert bits99 == 255
    assert ext is True


def test_page_grouping_aligned_with_ellipsis(headless):
    out = headless.exec(PAGE_SETUP + r'''
return_value.write((DiceEntropyPage(rolls='1234561234').rolls_view.text + '|' +
                    DiceEntropyPage(rolls='123456' * 20).rolls_view.text).encode())
''')
    short, long = out.split('|')
    assert short == '12345 61234'
    rolls = '123456' * 20
    expected = '... ' + ' '.join(rolls[40:][i:i + 5] for i in range(0, 80, 5))
    assert long == expected


def test_page_results(headless):
    out = headless.exec(PAGE_SETUP + r'''
p = DiceEntropyPage(rolls='654321')
p.right_action(True); a = p.result
p.right_action(False); b = p.result
q = DiceEntropyPage(rolls='654321')
q.left_action(False); c = q.result
return_value.write(repr((a, b, c, q.rolls)).encode())
''')
    assert eval(out) == (None, '654321', None, '654321')


def test_flow_targets(headless):
    out = headless.exec(r'''
from flows.new_seed_flow import NewSeedFlow
f = NewSeedFlow()
f.seed_length = 12; a = f.target_rolls()
f.seed_length = 24; b = f.target_rolls()
return_value.write(repr((a, b, f.dice_rolls)).encode())
''')
    assert eval(out) == (50, 100, None)


def test_flow_back_from_confirm_does_not_trap(headless):
    """Regression for the confirm <-> entry Back loop (PR #5).

    Drives NewSeedFlow's enter_dice/confirm_dice states with the pages stubbed,
    and checks the real Flow history stack: Back from confirm must pop to entry
    (not push), so a second Back leaves the dice screens entirely.
    """
    out = headless.exec(r'''
import lvgl as lv
lv.init()
import uasyncio
import pages, flows.new_seed_flow as nsf
from flows.new_seed_flow import NewSeedFlow

# Stub the two pages: DiceEntropyPage returns None (Back) or rolls (checkmark);
# LongQuestionPage returns False (Back) or True (Continue).
script = []
class FakeDice:
    def __init__(self, rolls='', **kw):
        self.rolls = rolls
    async def show(self):
        action = script.pop(0)
        if action == 'back':
            return None
        self.rolls = action
        return action
class FakeConfirm:
    def __init__(self, **kw): pass
    async def show(self):
        return script.pop(0) == 'continue'
pages.DiceEntropyPage = FakeDice
pages.LongQuestionPage = FakeConfirm

f = NewSeedFlow()
f.seed_length = 12
f.state = f.confirm_generate
f.prev_states = [f.check_for_seed, f.pick_length]
depth0 = len(f.prev_states)

async def step(state):
    f.state = state
    await state()

async def run():
    # user types rolls, reaches confirm
    script[:] = ['1234']
    f.goto(f.enter_dice); await step(f.enter_dice)
    assert f.state.__name__ == 'confirm_dice', f.state.__name__
    d1 = len(f.prev_states)
    # Back on confirm -> entry, stack must shrink (pop), not grow
    script[:] = ['back']
    await step(f.confirm_dice)
    assert f.state.__name__ == 'enter_dice', f.state.__name__
    d2 = len(f.prev_states)
    assert f.dice_rolls == '1234', f.dice_rolls
    # Back on entry -> leaves the dice screens entirely
    script[:] = ['back']
    await step(f.enter_dice)
    assert f.state.__name__ == 'confirm_generate', f.state.__name__
    d3 = len(f.prev_states)
    # rolls preserved for a forward trip
    assert f.dice_rolls == '1234', f.dice_rolls
    return_value.write(repr((depth0, d1, d2, d3)).encode())

uasyncio.run(run())
''')
    depth0, d1, d2, d3 = eval(out)
    assert d1 == depth0 + 2          # confirm_generate, enter_dice pushed
    assert d2 == depth0 + 1          # Back popped, did not push
    assert d3 == depth0              # second Back pops to confirm_generate
