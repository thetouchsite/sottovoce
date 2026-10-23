"""Recording from the computer (recorder.py), with stand-in devices: no
microphone, no speakers, any system. The real devices are tried by hand on
Windows."""
import time
import wave

import numpy as np
import pytest

import recorder


class Device:
    """Stands in for a soundcard device: a constant level, a block at a time."""

    def __init__(self, value, fail=False):
        self.value, self.fail = value, fail

    def recorder(self, samplerate, channels, blocksize):
        if self.fail:
            raise RuntimeError("device in use")
        device = self

        class Rec:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def record(self, numframes=None):
                n = numframes or 10
                time.sleep(n / recorder.RATE)               # as fast as a real device
                return np.full((n, 1), device.value, dtype="float32")
        return Rec()


def test_the_microphone_goes_left_and_the_call_right(tmp_path):
    c = recorder.Capture(tmp_path / "call.wav", Device(0.1), Device(-0.05))
    c.start()
    time.sleep(0.3)
    assert c.levels[0] > c.levels[1] > 0
    path = c.stop()
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (2, recorder.RATE, 2)
        frames = w.getnframes()
        data = np.frombuffer(w.readframes(frames), "<i2").reshape(-1, 2)
    assert frames > 0
    assert abs(data[:, 0].mean() / 32767 - 0.1) < 0.005
    assert abs(data[:, 1].mean() / 32767 + 0.05) < 0.005
    assert c.seconds == frames / recorder.RATE


def test_a_recording_cut_off_mid_call_is_made_whole(tmp_path):
    f = tmp_path / "cut.wav"
    f.write_bytes(recorder.header(0) + b"\x01\x00\x02\x00" * 10 + b"\x07")     # 10 frames and a stray byte
    assert recorder.repair(f) == 10
    with wave.open(str(f)) as w:
        assert w.getnframes() == 10
    assert f.stat().st_size == recorder.HEADER + 40


def test_a_device_that_does_not_start_stops_the_recording_at_once(tmp_path):
    c = recorder.Capture(tmp_path / "x.wav", Device(0.1), Device(0.1, fail=True))
    with pytest.raises(RuntimeError, match="computer sound"):
        c.start()
    assert not (tmp_path / "x.wav").exists()


def test_levels_follow_the_page_scale():
    assert recorder.level(np.zeros(100, "float32")) == 0
    assert recorder.level(np.full(100, 1.0, "float32")) == 1.0
    assert 0 < recorder.level(np.full(100, 0.05, "float32")) < 1


def test_a_track_is_held_to_the_clock():
    block = np.ones(recorder.BLOCK, "float32")
    # On time, or off by less than the slack: untouched.
    assert len(recorder.on_time(block, 0, recorder.BLOCK + 100)) == recorder.BLOCK
    # Behind: the missing frames are silence, after the block.
    behind = recorder.on_time(block, 0, recorder.BLOCK + 2 * recorder.SLACK)
    assert len(behind) == recorder.BLOCK + 2 * recorder.SLACK and behind[-1] == 0
    # Ahead: the excess goes.
    ahead = recorder.on_time(block, 2 * recorder.SLACK, recorder.BLOCK)
    assert len(ahead) == 0


def test_a_device_that_goes_mid_call_is_opened_again_and_the_gap_is_silence(tmp_path):
    class Flaky(Device):
        """Gives a few blocks, then fails: headphones running flat."""
        def recorder(self, samplerate, channels, blocksize):
            inner = Device.recorder(self, samplerate, channels, blocksize)
            calls = {"n": 0}
            record = inner.record

            def failing(numframes=None):
                calls["n"] += 1
                if calls["n"] > 3:
                    raise RuntimeError("device gone")
                return record(numframes)
            inner.record = failing
            return inner

    mic, gone, back = Device(0.1), Flaky(-0.05), Device(-0.05)
    c = recorder.Capture(tmp_path / "call.wav", mic, gone, resolve=lambda: (mic, back, None))
    c.start()
    time.sleep(1.5)
    path = c.stop()
    assert c.switched >= 1 and c.error is None
    with wave.open(str(path)) as w:
        seconds = w.getnframes() / w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2)
    assert seconds > 1.2                                  # the call side kept the time
    assert (data[-recorder.BLOCK:, 1] < 0).all()         # and came back
