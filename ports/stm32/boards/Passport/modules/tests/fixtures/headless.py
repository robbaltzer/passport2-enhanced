# SPDX-FileCopyrightText: © 2026 Rob Baltzer
# SPDX-License-Identifier: GPL-3.0-or-later
#
# headless.py - Run the Passport Unix runtime without the SDL/xterm front-end.
#
# The regular `simulator` fixture launches simulator.py, which needs a display.
# This fixture launches ports/unix/passport-mpy directly with the same pipes the
# GUI would create, in --unit-test mode, so Python can be exec()ed inside the
# real MicroPython runtime (real trezorcrypto, real LVGL bindings, real pages)
# on a headless CI machine.

import os
import socket
import subprocess
import tempfile
import time

import pytest

UNIX_SOCKET_PATH = b'/tmp/passport-simulator.sock'


class HeadlessRuntime:
    def __init__(self, simulator_dir, screen='color'):
        simulator_dir = os.path.realpath(simulator_dir)
        self.simulator_dir = simulator_dir
        self.proc = None
        self.pipe = None
        self.client_path = None

        mpy = os.path.join(simulator_dir, '..', 'ports', 'unix', 'passport-mpy')
        if not os.path.exists(mpy):
            pytest.skip('simulator not built (run `just simulator/build color`)')

        try:
            os.unlink(UNIX_SOCKET_PATH)
        except FileNotFoundError:
            pass
        work = os.path.join(simulator_dir, 'work')
        os.makedirs(os.path.join(work, 'microsd'), exist_ok=True)

        env = os.environ.copy()
        env['MICROPYPATH'] = ':' + os.path.join(simulator_dir, 'sim_modules') + \
            ':' + os.path.realpath(os.path.join(simulator_dir, '../ports/stm32/boards/Passport/modules')) + \
            ':' + os.path.realpath(os.path.join(simulator_dir, '../extmod'))

        oled_r, oled_w = os.pipe()
        led_r, led_w = os.pipe()
        numpad_r, numpad_w = os.pipe()
        cam_cmd_r, cam_cmd_w = os.pipe()
        cam_img_r, cam_img_w = os.pipe()
        # Keep our ends open but unread; the runtime only writes a few bytes in unit-test mode.
        self._keep = [os.fdopen(oled_r, 'rb', buffering=0), os.fdopen(led_r, 'rb', buffering=0),
                      os.fdopen(numpad_w, 'wb', buffering=0), os.fdopen(cam_cmd_r, 'rb', buffering=0),
                      os.fdopen(cam_img_w, 'wb', buffering=0)]

        cmd = ['../../ports/unix/passport-mpy', '-X', 'heapsize=30m', '-i', '../sim_boot.py',
               str(oled_w), str(numpad_r), str(led_w), str(cam_cmd_w), str(cam_img_r),
               screen, '--unit-test']
        self.log = tempfile.NamedTemporaryFile(prefix='passport-headless-', suffix='.log', delete=False)
        self.proc = subprocess.Popen(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                     stdout=self.log, stderr=subprocess.STDOUT,
                                     pass_fds=[oled_w, numpad_r, led_w, cam_cmd_w, cam_img_r])
        for fd in (oled_w, numpad_r, led_w, cam_cmd_w, cam_img_r):
            os.close(fd)

        self.pipe = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        deadline = time.monotonic() + 20
        while True:
            try:
                self.pipe.connect(UNIX_SOCKET_PATH)
                break
            except OSError:
                if self.proc.poll() is not None:
                    raise RuntimeError('runtime exited with %r (log: %s)' % (self.proc.returncode, self.log.name))
                if time.monotonic() > deadline:
                    raise TimeoutError('runtime socket never appeared (log: %s)' % self.log.name)
                time.sleep(0.05)
        with tempfile.NamedTemporaryFile(suffix='.sock', prefix='passport-client.', dir='/tmp') as t:
            self.client_path = t.name
        self.pipe.bind(self.client_path)

    def exec(self, code, timeout=60):
        """exec() `code` inside the runtime. `return_value` is a BytesIO the code may write to."""
        cmd = b'exec'
        text = code.encode()
        self.pipe.send((len(cmd) + len(text)).to_bytes(4, 'big'))
        self.pipe.send(cmd + text)
        self.pipe.settimeout(timeout)
        n = int.from_bytes(self.pipe.recv(4), 'big')
        pkt = self.pipe.recv(n)
        kind, out = pkt[:4].decode(), pkt[4:].decode('utf-8', 'replace')
        if kind == 'excp':
            pytest.fail('Exception inside runtime:\n' + out)
        return out

    def close(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        for f in self._keep:
            f.close()
        for p in (self.client_path,):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        try:
            os.unlink(UNIX_SOCKET_PATH)
        except FileNotFoundError:
            pass


@pytest.fixture
def headless(simulatordir):
    rt = HeadlessRuntime(simulatordir)
    try:
        yield rt
    finally:
        rt.close()
