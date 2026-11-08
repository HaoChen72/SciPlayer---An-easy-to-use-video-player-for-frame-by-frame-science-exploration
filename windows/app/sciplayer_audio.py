"""SciPlayer - the sound of a video, played with it.

The audio track is decoded while it plays (a feeder thread with its own reader, from the
moment playback starts), resampled to the sound device's rate and sent to it through
PortAudio (sounddevice). The device's position is the playback clock: the video shows the
frame whose time is being heard, so picture and sound stay together.

Sound plays only when the video runs in real time at its own frame rate (with another rate
typed in, or every n-th frame kept, the picture would run faster or slower than the sound).
"""
import collections
import threading
import time

import numpy as np


def audio_info(path):
    """(has_audio, description) of a file's first audio stream, without decoding it"""
    try:
        import av
        c = av.open(path)
        try:
            if not c.streams.audio:
                return False, ''
            a = c.streams.audio[0]
            ch = a.codec_context.channels if hasattr(a.codec_context, 'channels') else a.channels
            return True, '%s, %d Hz, %d ch' % (a.codec_context.name, a.codec_context.sample_rate or 0, ch or 0)
        finally:
            c.close()
    except Exception:
        return False, ''


class AudioPlayer:
    """play the audio of PATH from a video time on; clock() = the video time being heard"""

    BUFFER_S = 1.0                      # decoded ahead of the device

    def __init__(self, path, video_t0=0.0, backend=None):
        self.path = path
        self.v0 = float(video_t0 or 0.0)          # absolute time of the video's first frame (s)
        self.has_audio, self.desc = audio_info(path)
        self.ok, self.reason = False, 'no sound track'
        self.reason_fmt, self.reason_arg = 'no sound track', None
        self.sd = backend
        self.stream = None
        self.thread = None
        self.stop_ev = None
        self.lock = threading.Lock()
        if not self.has_audio:
            return
        try:
            if self.sd is None:
                import sounddevice
                self.sd = sounddevice
            dev = self.sd.query_devices(kind='output')
            self.sr = int(round(dev['default_samplerate'])) or 48000
            self.ch = max(1, min(2, int(dev['max_output_channels'])))
            self.ok, self.reason = True, ''
        except Exception as e:
            self._fail('no sound device (%s)', str(e).splitlines()[0][:80])

    def _fail(self, fmt, arg):
        self.ok, self.reason = False, fmt % arg
        self.reason_fmt, self.reason_arg = fmt, arg

    def reason_text(self):
        """why there is no sound, in the window's language"""
        try:
            from sciplayer_i18n import tr
        except Exception:
            return self.reason
        return tr(self.reason_fmt) % self.reason_arg if self.reason_arg is not None else tr(self.reason_fmt)

    # ------------------------------------------------------------------ playing
    def start(self, t):
        """start the sound at video time T (s)"""
        self.stop()
        if not self.ok:
            return False
        self.t_start = float(t)
        self.played = 0
        self.buf = collections.deque()
        self.buf_n = 0
        self.head = 0                    # samples of buf[0] already sent
        self.ended = False
        self.played_real = None
        self.bad_clock = False
        self.t_wall = time.perf_counter()
        self.stop_ev = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._feed, args=(self.t_start, self.stop_ev), daemon=True)
        self.thread.start()
        self.ready.wait(1.0)              # some sound decoded before the device starts
        try:
            self.stream = self.sd.OutputStream(samplerate=self.sr, channels=self.ch, dtype='int16',
                                               callback=self._callback, latency='low')
            self.stream.start()
            self.latency = float(getattr(self.stream, 'latency', 0.0) or 0.0)
            self.t_wall = time.perf_counter()
        except Exception as e:
            self._fail('the sound device does not open (%s)', str(e).splitlines()[0][:80])
            self.stop()
            return False
        return True

    def stop(self):
        if self.stop_ev is not None:
            self.stop_ev.set()
        if self.stream is not None:
            try:
                self.stream.abort()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None

    @property
    def playing(self):
        return self.stream is not None

    def clock(self):
        """video time (s) of the sound being heard now; None when not playing, when the sound has ended,
        or when the device's clock does not keep time (bad_clock)"""
        if self.stream is None:
            return None
        with self.lock:
            if self.ended and self.buf_n == 0 and self.played_real is not None and self.played >= self.played_real:
                return None
            played = self.played
        t = self.t_start + max(0.0, played / self.sr - self.latency)
        # a device that takes sound faster or slower than it plays it (no real output, a broken
        # driver) would drag the picture along: then the wall clock leads
        wall = self.t_start + (time.perf_counter() - self.t_wall)
        if abs(t - wall) > 0.25:
            self.bad_clock = True
            return None
        return t

    # ------------------------------------------------------------------ the device
    def _callback(self, out, frames, time_info, status):
        n = 0
        with self.lock:
            while n < frames and self.buf:
                a = self.buf[0]
                take = min(frames - n, len(a) - self.head)
                out[n:n + take] = a[self.head:self.head + take]
                n += take
                self.head += take
                self.buf_n -= take
                if self.head >= len(a):
                    self.buf.popleft()
                    self.head = 0
            if n < frames:
                out[n:] = 0
            self.played += frames

    # ------------------------------------------------------------------ decoding
    def _push(self, a, stop):
        while not stop.is_set():
            with self.lock:
                if self.buf_n < self.BUFFER_S * self.sr:
                    self.buf.append(a)
                    self.buf_n += len(a)
                    if self.buf_n >= 0.1 * self.sr:
                        self.ready.set()
                    return
            time.sleep(0.01)

    def _feed(self, t, stop):
        self.played_real = None
        try:
            import av
            c = av.open(self.path)
        except Exception:
            self.ended = True
            self.ready.set()
            return
        try:
            a = c.streams.audio[0]
            tb = float(a.time_base)
            T = self.v0 + t                              # absolute time to start from
            if T > 0:
                c.seek(int(T / tb), stream=a, backward=True, any_frame=False)
            rs = av.AudioResampler(format='s16', layout='stereo' if self.ch == 2 else 'mono', rate=self.sr)
            pos = None                                   # absolute time of the next resampled sample
            sent = 0

            def emit(arr):
                nonlocal pos, sent
                arr = arr.reshape(-1, self.ch)
                if pos is not None and pos < T:          # before the start: drop
                    drop = int(round((T - pos) * self.sr))
                    pos += min(drop, len(arr)) / self.sr
                    arr = arr[drop:]
                if len(arr):
                    self._push(np.ascontiguousarray(arr), stop)
                    sent += len(arr)
                    pos = (pos if pos is not None else T) + len(arr) / self.sr

            for fr in c.decode(a):
                if stop.is_set():
                    return
                if pos is None:
                    ft = fr.pts * tb if fr.pts is not None else T
                    if ft > T:                           # the sound starts after T: silence first
                        emit(np.zeros((int(round((ft - T) * self.sr)), self.ch), np.int16))
                    pos = ft if ft <= T else pos
                for r in rs.resample(fr):
                    emit(r.to_ndarray())
            for r in rs.resample(None):
                emit(r.to_ndarray())
            with self.lock:
                self.played_real = self.played + self.buf_n
        except Exception:
            pass
        finally:
            self.ended = True
            self.ready.set()
            c.close()
