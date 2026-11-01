# SPDX-FileCopyrightText: © 2022 Foundation Devices, Inc. <hello@foundation.xyz>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# new_seed_task.py - Task to create a new random seed

import common
import trezorcrypto


async def new_seed_task(on_done, seed_length, extra_entropy=None):
    seed = bytearray(32)
    # Entropy failures invoke the fatal handler before this call can return.
    common.noise.random_bytes(seed, common.noise.ALL)

    # Hash to mitigate any potential bias in RNG sources.
    #
    # If the user supplied additional entropy (e.g. dice rolls), it is appended to the
    # hardware entropy before hashing:  seed = SHA256(hw_entropy || extra_entropy)
    # The hardware entropy is always included, so a weak die cannot weaken the seed
    # below what the hardware alone would produce; conversely, a weak hardware RNG
    # can be compensated for to the extent the dice are fair and independent.
    # extra_entropy is a str of ASCII dice rolls ('1'-'6'), or None.
    h = trezorcrypto.sha256(seed)
    if extra_entropy:
        h.update(extra_entropy.encode())
    seed = h.digest()

    # Math to convert number of words to number of bytes
    seed = seed[0:((seed_length // 3) * 4)]

    # print('create_new_wallet_seed(): New seed = {}'.format(b2a_hex(seed)))

    await on_done(seed, None)
