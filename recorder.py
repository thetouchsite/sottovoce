"""Recording a call from the computer itself: your microphone and everything
the computer plays, on two tracks.

    left    the microphone: you
    right   what comes out of the speakers or headphones: the others

The same two tracks the page records from a browser tab, so the server tells
who spoke the same way (transcribe.label_speakers). Here nothing is shared on
screen and any call works: Meet in a browser, the Teams or Zoom apps, a phone
call through the computer. Windows only for now, through WASAPI and its
loopback of the output device, with soundcard (BSD-3).

The file is a stereo WAV written as it goes, its header brought up to date
every few seconds: a computer that switches off mid-call leaves a recording
that repair() makes whole again, as the page's pieces do for the browser.
"""
import pathlib
import queue
import struct
import threading
import time
import warnings

import numpy as np

RATE = 48000
BLOCK = RATE // 10                 # a tenth of a second, the step of everything here
HEADER = 44
SYNC_EVERY = 30                    # blocks: the header is right to within three seconds
SLACK = RATE // 4                  # how far a track may drift from the clock before it is put back


def available() -> bool:
    """Whether this computer can record its own sound: soundcard, and Windows."""
    import sys
    if sys.platform != "win32":
        return False
    try:
        import soundcard  # noqa: F401
    except Exception:
        return False
    return True


# --- the file ---------------------------------------------------------------------

def header(frames: int, channels: int = 2, rate: int = RATE) -> bytes:
    """A 16-bit PCM WAV header for this many frames."""
    data = frames * channels * 2
    return (b"RIFF" + struct.pack("<I", 36 + data) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * channels * 2, channels * 2, 16)
            + b"data" + struct.pack("<I", data))


def repair(path: pathlib.Path) -> int:
    """Sets the header from the file's real length: a recording cut off
    mid-call says it is shorter than it is. Returns the frames."""
    size = path.stat().st_size
    frames = max(0, size - HEADER) // 4
    with path.open("r+b") as f:
        f.write(header(frames))
        f.truncate(HEADER + frames * 4)            # half a frame at the end, if any, goes
    return frames


class Wav:
    """Stereo 16-bit, appended to, its header kept close to the truth."""

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.f = path.open("wb")
        self.f.write(header(0))
        self.frames = 0
        self._since = 0

    def write(self, left: np.ndarray, right: np.ndarray):
        both = np.stack([left, right], axis=1)
        pcm = (np.clip(both, -1, 1) * 32767).astype("<i2")
        self.f.write(pcm.tobytes())
        self.frames += len(pcm)
        self._since += 1
        if self._since >= SYNC_EVERY:
            self.sync()

    def sync(self):
        here = self.f.tell()
        self.f.seek(0)
        self.f.write(header(self.frames))
        self.f.seek(here)
        self.f.flush()
        self._since = 0

    def close(self):
        self.sync()
        self.f.close()


# --- the capture --------------------------------------------------------------------

def on_time(block: np.ndarray, made: int, due: int):
    """The block, padded or cut so the track has `due` frames in all.

    `made` frames came before it. A safety net, not the timing itself: a
    track behind the clock by more than SLACK (a device that stalled) gets
    silence for the frames it never delivered; one ahead loses the excess.
    Within SLACK nothing changes."""
    have = made + len(block)
    if due - have > SLACK:
        return np.concatenate([block, np.zeros(due - have, dtype=block.dtype)])
    if have - due > SLACK:
        return block[:max(0, len(block) - (have - due))]
    return block


def level(block: np.ndarray) -> float:
    """0 to 1, as the page's meters show it: the same scale as the browser's."""
    if not len(block):
        return 0.0
    return float(min(1.0, np.sqrt(np.mean(block * block)) * 6))


def devices():
    """(microphone, loopback of the output, the output): Windows' defaults, now."""
    import soundcard as sc
    speaker = sc.default_speaker()
    return sc.default_microphone(), sc.get_microphone(speaker.id, include_loopback=True), speaker


class Capture:
    """Two devices recorded block by block into one stereo file.

    Each device has its own thread; a third writes what both have.

    When the computer plays nothing, Windows sends nothing from the loopback.
    soundcard then guesses the silent time and returns zeros, but the guess
    drifts: measured here, the loopback lost 0.08 s in two minutes of sound
    that came and went, and the computer track ended up tenths of a second
    away from the microphone. So while recording, the output plays silence
    (inaudible), as OBS does: Windows keeps sending, and both tracks run on
    their devices' own clocks, with nothing to guess. on_time() stays as a
    net for a device that stalls.

    Devices change mid-call: headphones run flat, or get plugged in. A
    device that goes away is opened again as Windows' new default, and one
    that Windows stops using (checked every two seconds) is left for the new
    one. The gap is silence on that track, so the two stay aligned; the
    recording is never lost.
    """

    def __init__(self, path: pathlib.Path, mic=None, call=None, speaker=None, resolve=None):
        self.path = path
        self._devices = (mic, call, speaker) if mic is not None and call is not None else None
        # Where to find the devices again when one goes: Windows' defaults,
        # or what a test gives.
        self._resolve = resolve if resolve is not None else (None if self._devices else devices)
        self._moved = [threading.Event(), threading.Event()]
        self._ids = [None, None]
        self.switched = 0                  # devices opened again mid-call
        self.levels = [0.0, 0.0]
        self.corrected = [0, 0]            # frames on_time() added or cut, per track: should stay 0
        self.error = None
        self.started = None
        self._queues = [queue.Queue(), queue.Queue()]
        self._stop = threading.Event()
        self._threads = []
        self._wav = None

    @property
    def seconds(self) -> float:
        return self._wav.frames / RATE if self._wav else 0.0

    def start(self):
        mic, call, speaker = self._devices or devices()
        self._wav = Wav(self.path)
        ready = threading.Barrier(3)
        self._threads = [threading.Thread(target=self._take, args=(i, d, ready), daemon=True)
                         for i, d in enumerate((mic, call))]
        self._threads.append(threading.Thread(target=self._write, daemon=True))
        if speaker is not None:
            self._threads.append(threading.Thread(target=self._keep_sending, args=(speaker,), daemon=True))
        for t in self._threads:
            t.start()
        try:
            ready.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
        # A device that can't start is a recording that would miss a side:
        # better to say so now than after the call.
        if self.error or not all(t.is_alive() for t in self._threads[:2]):
            self.stop()
            self.path.unlink(missing_ok=True)
            raise RuntimeError(self.error or "the sound devices did not start")
        self.started = time.time()

    def _take(self, track, device, ready):
        which = "microphone" if track == 0 else "computer sound"
        started, start, made = False, 0.0, 0

        def keep_time(block):
            nonlocal made
            fixed = on_time(block, made, int((time.perf_counter() - start) * RATE))
            self.corrected[track] += abs(len(fixed) - len(block))
            made += len(fixed)
            if len(fixed):
                self._queues[track].put(fixed)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")          # "data discontinuity": a dropped packet, not an error
            while not self._stop.is_set():
                try:
                    with device.recorder(samplerate=RATE, channels=1, blocksize=BLOCK) as r:
                        r.record(numframes=None)     # what the device kept from before
                        self._ids[track] = getattr(device, "id", None)
                        if not started:
                            ready.wait(timeout=10)
                            start, started = time.perf_counter(), True
                        self._moved[track].clear()
                        while not self._stop.is_set() and not self._moved[track].is_set():
                            keep_time(r.record(numframes=BLOCK)[:, 0])
                except threading.BrokenBarrierError:
                    break
                except Exception as e:               # unplugged, taken by another program
                    self.error = f"{which}: {e}"
                    if not started or self._resolve is None:
                        if not started:
                            try:
                                ready.wait(timeout=0.1)
                            except threading.BrokenBarrierError:
                                pass
                        break
                if self._stop.is_set():
                    break
                # Gone, or no longer Windows' choice: the new default, after a breath.
                time.sleep(0.3)
                keep_time(np.zeros(0, dtype="float32"))     # the gap, as silence
                try:
                    device = self._resolve()[track]
                    self.switched += 1
                    self.error = None
                except Exception as e:
                    self.error = f"{which}: {e}"
        self._queues[track].put(None)

    def _keep_sending(self, speaker):
        """Silence on the output, so the loopback never stops sending; and,
        every two seconds, whether Windows moved to another device."""
        silence = np.zeros(BLOCK, dtype="float32")
        while not self._stop.is_set():
            try:
                with speaker.player(samplerate=RATE, channels=1, blocksize=BLOCK) as p:
                    played = 0
                    while not self._stop.is_set():
                        p.play(silence)
                        played += 1
                        if self._resolve is None or played % 20:
                            continue
                        mic, _, now = self._resolve()
                        if getattr(mic, "id", None) != self._ids[0]:
                            self._moved[0].set()
                        if getattr(now, "id", None) != getattr(speaker, "id", None):
                            speaker = now
                            self._moved[1].set()
                            break
            except Exception:
                if self._resolve is None:
                    return                 # then soundcard's guess and on_time() keep the time
                time.sleep(0.5)
                try:
                    speaker = self._resolve()[2]
                    self._moved[1].set()
                except Exception:
                    pass

    def _write(self):
        """Writes as far as both tracks go; a track that ended is silent."""
        held = [np.zeros(0, dtype="float32"), np.zeros(0, dtype="float32")]
        ended = [False, False]
        while not all(ended):
            for i, q in enumerate(self._queues):
                if ended[i]:
                    continue
                try:
                    b = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if b is None:
                    ended[i] = True
                    continue
                if len(b):
                    self.levels[i] = level(b)
                held[i] = np.concatenate([held[i], b])
            for i in (0, 1):
                if ended[i] and not ended[1 - i]:
                    held[i] = np.concatenate([held[i], np.zeros(max(0, len(held[1 - i]) - len(held[i])), "float32")])
            n = min(len(held[0]), len(held[1]))
            if n:
                self._wav.write(held[0][:n], held[1][:n])
                held = [held[0][n:], held[1][n:]]

    def stop(self) -> pathlib.Path:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)
        if self._wav:
            self._wav.close()
        return self.path
