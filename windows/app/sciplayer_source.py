"""SciPlayer - frame sources: where the frames come from while the player runs.

A recording that fits comfortably in memory is read into it (ArraySource): every frame is
there at once. A larger one stays on disk and its frames are decoded when they are shown
(VideoSource, TiffSource, H5Source), at full resolution, with a cache of recent frames:

  * videos: the packets are indexed once (no decoding), so frame k is found by its time
    stamp. Stepping forward decodes the next frame; any other jump seeks to the key frame
    before it and decodes forward, keeping the frames it passes in the cache, so stepping
    back afterwards is immediate. While the slider is dragged, frame_fast() shows the
    nearest key frame when the exact frame would need a long decode.
  * TIFF stacks (one page per frame) and MAT v7.3 files: frames are read directly.

Traces (whole-frame and ROI means) need every frame: scan() decodes the recording once,
start to end, with its own reader (so it can run in a background thread while the player
keeps going) and computes all requested traces in the same pass.

Frame numbers are 0-based here; the player shows them 1-based.
"""
import bisect
import collections
import os
import threading
import time

import numpy as np

import sciplayer_io as sio


# ---------------------------------------------------------------------------
# memory
# ---------------------------------------------------------------------------
def memory_bytes():
    """(total, available) physical memory in bytes (fallbacks: 8 GB / 4 GB)"""
    try:
        if os.name == 'nt':
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                            ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                            ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                            ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                            ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.ullTotalPhys), int(m.ullAvailPhys)
        info = {}
        with open('/proc/meminfo') as fh:
            for line in fh:
                k, v = line.split(':', 1)
                info[k] = int(v.split()[0]) * 1024
        return info['MemTotal'], info.get('MemAvailable', info['MemFree'])
    except Exception:
        return 8 << 30, 4 << 30


def default_memory_limit(cap_gb=2.0):
    """largest recording read wholly into memory: 2 GB, or 30 % of the free memory if less"""
    _, avail = memory_bytes()
    return int(min(cap_gb * 1e9, 0.3 * avail))


def default_cache_bytes():
    """frame cache of a recording that stays on disk (exact frames around the current one; the
    scrubbing copy covers the rest): 10 % of the free memory, 256 - 800 MB"""
    _, avail = memory_bytes()
    return int(min(8e8, max(256e6, 0.10 * avail)))


class FrameCache:
    """least-recently-used frames, limited in bytes"""

    def __init__(self, max_bytes):
        self.max_bytes = max(1, int(max_bytes))
        self.d = collections.OrderedDict()
        self.nbytes = 0

    def get(self, k):
        f = self.d.get(k)
        if f is not None:
            self.d.move_to_end(k)
        return f

    def put(self, k, f):
        if k in self.d:
            self.d.move_to_end(k)
            return
        self.d[k] = f
        self.nbytes += f.nbytes
        while self.nbytes > self.max_bytes and len(self.d) > 1:
            _, g = self.d.popitem(last=False)
            self.nbytes -= g.nbytes

    def __contains__(self, k):
        return k in self.d

    def frames_capacity(self, frame_bytes):
        return max(1, self.max_bytes // max(1, frame_bytes))

    def clear(self):
        self.d.clear()
        self.nbytes = 0


def prepare(f, cs, dtype):
    """a frame as the player keeps it: grey (H x W) or colour (H x W x 3), in the recording's type"""
    f = sio._rgb(f)
    if f.ndim == 3 and cs == 1:
        f = sio.to_grey(f)
    if f.dtype != dtype:
        f = f.astype(dtype)
    return f


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------
class Source:
    in_memory = False
    kind = ''

    def __init__(self, info):
        self.info = info
        self.file = info['file']
        self.fps = info['fps']
        self.cs = 1 if info.get('gray_forced') else info['Cs']
        self.is_rgb = self.cs == 3
        self.dtype = np.dtype(info['dtype'])
        self.H, self.W = info['H'], info['W']
        self.N = info['N']
        self.kept = np.arange(1, self.N + 1)
        self.times = None                    # seconds of every frame, when the file has time stamps
        self.mean_trace = None               # filled by the source (in memory) or by a scan
        self.reduced = False
        self.lock = threading.RLock()

    @property
    def frame_bytes(self):
        return self.H * self.W * self.cs * self.dtype.itemsize

    def frame(self, k):
        raise NotImplementedError

    def frame_fast(self, k):
        """(frame, index shown): exact unless that is slow (videos: then the key frame before it)"""
        return self.frame(k), k

    def iter_frames(self, stop=None):
        """(k, frame) for every frame, start to end, with a reader of its own (thread-safe)"""
        for k in range(self.N):
            if stop is not None and stop.is_set():
                return
            yield k, self.frame(k)

    def describe(self):
        return 'in memory' if self.in_memory else 'read from disk as shown'

    def close(self):
        pass


class ArraySource(Source):
    """the whole recording in memory"""
    in_memory = True
    kind = 'memory'

    def __init__(self, info, data, mean_trace, kept, reduced=False):
        super().__init__(info)
        self.data = data
        self.cs = 3 if data.ndim == 4 else 1
        self.is_rgb = self.cs == 3
        self.dtype = data.dtype
        self.N, self.H, self.W = data.shape[0], data.shape[1], data.shape[2]
        self.kept = np.asarray(kept)
        self.mean_trace = np.asarray(mean_trace, float)
        self.reduced = reduced

    def frame(self, k):
        return self.data[k]

    def iter_frames(self, stop=None):
        for k in range(self.N):
            if stop is not None and stop.is_set():
                return
            yield k, self.data[k]

    def describe(self):
        return '%s in memory' % sio.size_text(self.data.nbytes / 1e6)


class VideoSource(Source):
    """a video decoded on demand (see the module help)"""
    kind = 'video'
    EXACT_GOP = 12                        # while dragging: exact when the key frame is this close
    KEEP = 120                            # frames before the target kept in the cache (stepping back)
    MARGIN = 40                           # frames before the kept ones decoded in full (decoder delay)

    provisional = False                   # the frame times are predicted; the real index is read in the background
    index_changed = False                 # the background index found other frames than predicted (the window follows)

    def __init__(self, info, cache_bytes=None):
        super().__init__(info)
        import av
        self.av = av
        self._from = 0
        self._index()
        self.cache = FrameCache(cache_bytes or default_cache_bytes())
        self.c = av.open(self.file)
        self.s = self.c.streams.video[0]
        self.s.thread_type = 'AUTO'
        self._gen = None
        self._last = -1                   # index of the frame the decoder gave last
        if self.provisional:
            threading.Thread(target=self._real_index, daemon=True).start()

    # codecs whose every frame is a key frame: their frames are found by time at once, without
    # reading the file (an uncompressed AVI can be tens of GB: reading it to index it took minutes)
    INTRA = {'rawvideo', 'mjpeg', 'mjpegb', 'ljpeg', 'jpegls', 'prores', 'dnxhd', 'huffyuv', 'ffvhuff', 'utvideo',
             'magicyuv', 'png', 'apng', 'tiff', 'bmp', 'targa', 'jpeg2000', 'v210', 'v410', 'r210', 'r10k', 'cfhd',
             'qoi', 'y41p', 'yuv4', 'ayuv', 'v308', 'v408', 'zlib', 'mszh', 'sgi', 'pam', 'ppm', 'pgm'}

    def _fast_index(self):
        """an intra-only video: frame k at start + k frame durations (checked at the first and last frames)"""
        c = self.av.open(self.file)
        try:
            s = c.streams.video[0]
            if (s.codec_context.name or '') not in self.INTRA or not s.time_base:
                return False
            tb = float(s.time_base)
            rate = s.average_rate or s.base_rate or s.guessed_rate
            n = int(s.frames or 0)
            if not rate or float(rate) <= 0:
                return False
            if n <= 0:
                dur = float(s.duration * s.time_base) if s.duration else (c.duration / 1e6 if c.duration else 0)
                n = int(round(dur * float(rate)))
            if n <= 1:
                return False
            step = 1.0 / (float(rate) * tb)
            if abs(step - round(step)) > 1e-6:
                return False
            step = int(round(step))
            t0 = int(s.start_time) if s.start_time is not None else 0
            pts = t0 + step * np.arange(n, dtype=np.int64)

            def first_pts(target):
                c.seek(int(target), stream=s, backward=True, any_frame=False)
                for fr in c.decode(s):
                    return fr.pts if fr.pts is not None else getattr(fr, 'dts', None)
                return None
            if first_pts(pts[-1]) != pts[-1] or first_pts(pts[1]) != pts[1]:
                return False
            self.tb = tb
        except Exception:
            return False
        finally:
            c.close()
        self.pts = pts
        self.seekable = True
        self.keyframes = np.arange(n)
        self._set_n(n)
        return True

    GUESS_ABOVE = 150e6                   # bytes: smaller files are indexed from their packets at once (< ~0.3 s)

    def _guess_index(self):
        """a long-GOP video (H.264, HEVC, ...) at a constant frame rate: frame k at start + k frame
        durations, at once (checked on the first frames and the last one). Reading the packets for the
        real index (where the key frames are) reads the whole file, which takes long for a large one:
        that runs in the background, and the video plays meanwhile (frames found by seeking by time)."""
        try:
            if os.path.getsize(self.file) < self.GUESS_ABOVE:   # read quickly: the real index at once
                return False
        except OSError:
            return False
        c = self.av.open(self.file)
        try:
            s = c.streams.video[0]
            if not s.time_base:
                return False
            tb = float(s.time_base)
            rate = s.average_rate or s.base_rate or s.guessed_rate
            if not rate or float(rate) <= 0:
                return False
            n = int(s.frames or 0)
            if n <= 0:
                dur = float(s.duration * s.time_base) if s.duration else (c.duration / 1e6 if c.duration else 0)
                n = int(round(dur * float(rate)))
            if n <= 2:
                return False
            step = 1.0 / (float(rate) * tb)
            if abs(step - round(step)) > 1e-6:
                return False
            step = int(round(step))
            t0 = int(s.start_time) if s.start_time is not None else 0
            pts = t0 + step * np.arange(n, dtype=np.int64)
            s.thread_type = 'AUTO'
            got = []
            for fr in c.decode(s):                      # the first frames come at the predicted times
                got.append(fr.pts)
                if len(got) >= min(n, 8):
                    break
            if got != pts[:len(got)].tolist():
                return False
            c.seek(int(pts[-1]), stream=s, backward=True, any_frame=False)
            last, m = None, 0
            for p in c.demux(s):                        # and the last one is where predicted (the packets of
                if p.size == 0:                         # the last GOP: not decoded)
                    continue
                t = p.pts if p.pts is not None else p.dts
                if t is not None:
                    last = t if last is None else max(last, int(t))
                m += 1
                if m > 5000:
                    return False
            if last != pts[-1]:
                return False
            self.tb = tb
        except Exception:
            return False
        finally:
            c.close()
        self.pts = pts
        self.seekable = True
        self.keyframes = np.array([0])
        self.provisional = True
        self._set_n(n)
        return True

    def _read_index(self):
        """(pts in presentation order, seekable, key frames) from the packets (reads the whole file)"""
        c = self.av.open(self.file)
        try:
            s = c.streams.video[0]
            ts, keys = [], []
            for p in c.demux(s):
                if p.size == 0:
                    continue
                t = p.pts if p.pts is not None else p.dts
                if t is None:
                    continue
                ts.append(int(t))
                keys.append(bool(p.is_keyframe))
            tb = float(s.time_base) if s.time_base is not None else 1.0
        finally:
            c.close()
        if not ts:
            raise sio.ReadError('The video has no time stamps to find its frames by.')
        ts = np.asarray(ts, np.int64)
        order = np.argsort(ts, kind='stable')
        pts = ts[order]
        seekable = bool(np.all(np.diff(pts) > 0))
        key_ts = ts[np.asarray(keys)]
        kf = np.flatnonzero(np.isin(pts, key_ts)) if seekable else np.array([0])
        if kf.size == 0 or kf[0] != 0:
            kf = np.r_[0, kf]
        return pts, seekable, kf, tb

    def _real_index(self):
        try:
            pts, seekable, kf, tb = self._read_index()
        except Exception:
            return                                       # the predicted index stays (it was checked)
        with self.lock:
            changed = len(pts) != self.N or not np.array_equal(pts, self.pts)
            self.pts, self.seekable, self.keyframes = pts, seekable, kf
            self._set_n(len(pts))
            if changed:
                self.cache.clear()
                self._gen = None
                self.index_changed = True
            self.provisional = False

    def _index(self):
        """time stamps of all frames (presentation order) and the key frames"""
        if self._fast_index() or self._guess_index():
            return
        self.pts, self.seekable, self.keyframes, self.tb = self._read_index()
        self._set_n(len(self.pts))

    def _set_n(self, n):
        self.N = n
        self.kept = np.arange(1, n + 1)
        self.times = (self.pts - self.pts[0]) * self.tb if self.seekable else None
        self._pts_list = self.pts.tolist()

    def adopt_index(self, pts):
        """the time stamps the decoder actually gave (from a scan) replace the packet index"""
        pts = np.asarray(pts, np.int64)
        if self.provisional or (len(pts) == self.N and np.array_equal(pts, self.pts)):
            return False
        with self.lock:
            key_ts = self.pts[self.keyframes]
            self.pts = pts
            self.seekable = bool(np.all(np.diff(pts) > 0))
            kf = np.flatnonzero(np.isin(pts, key_ts))
            self.keyframes = kf if (kf.size and kf[0] == 0) else np.r_[0, kf]
            self._set_n(len(pts))
            self.cache.clear()
            self._gen = None
        return True

    def describe(self):
        return 'decoded from disk as shown (cache %s)' % sio.size_text(self.cache.max_bytes / 1e6)

    def keyframe_before(self, k):
        if self.provisional:
            return k
        i = int(np.searchsorted(self.keyframes, k, side='right')) - 1
        return int(self.keyframes[max(0, i)])

    def _k_of(self, t):
        if t is None:
            return self._last + 1
        i = bisect.bisect_left(self._pts_list, t)
        if i < self.N and self._pts_list[i] == t:
            return i
        if i <= 0:
            return 0
        if i >= self.N:
            return self.N - 1
        return i if (self._pts_list[i] - t) < (t - self._pts_list[i - 1]) else i - 1

    def _seek(self, kf):
        self._gen = None
        if not self.seekable:
            self._reopen()
            kf = 0
        else:
            self.c.seek(int(self.pts[max(0, kf)]), stream=self.s, backward=True, any_frame=False)
        self._gen = self.c.decode(self.s)
        self._last = -1
        # predicted index: the seek lands on the key frame before kf, wherever it is; the first frame
        # decoded marks it (frames shown before it belong to the GOP before: not trusted)
        self._from = None if self.provisional else kf

    def _reopen(self):
        self.c.close()
        self.c = self.av.open(self.file)
        self.s = self.c.streams.video[0]
        self.s.thread_type = 'AUTO'

    def _skip(self, on):
        try:
            self.s.codec_context.skip_frame = 'NONREF' if on else 'DEFAULT'
        except Exception:
            pass

    def _advance_to(self, k, skip=True):
        """decode forward to frame k; the KEEP frames before k are kept in the cache. Frames long before
        k that no other frame refers to (B-frames) are not decoded at all (SKIP), which makes a jump
        into a long group of pictures 2 - 3 times faster."""
        keep = min(self.KEEP, self.cache.frames_capacity(self.frame_bytes) // 2)
        pf = self.info['pix_fmt']
        lo = self._last if self._last >= 0 else (self._from if self._from is not None else k)
        skipping = skip and self.seekable and not self.provisional and (k - lo) > keep + self.MARGIN
        self._skip(skipping)
        try:
            for fr in self._gen:
                t = fr.pts if fr.pts is not None else getattr(fr, 'dts', None)
                idx = self._k_of(t) if self.seekable else self._last + 1
                self._last = idx
                if self._from is None:
                    self._from = idx
                if skipping and idx >= k - keep - self.MARGIN:
                    skipping = False
                    self._skip(False)
                if idx < self._from:              # leading frames of an open GOP: not trusted
                    continue
                if idx > k:
                    return None                   # (the seek went too far, or k was skipped)
                if k - idx < keep or idx == k:
                    f = prepare(sio._video_array(fr, pf, self.cs), self.cs, self.dtype)
                    self.cache.put(idx, f)
                    if idx == k:
                        return f
            self._gen = None
            return None
        finally:
            if skipping:
                self._skip(False)

    def frame(self, k):
        k = int(k)
        with self.lock:
            f = self.cache.get(k)
            if f is not None:
                return f
            kf = self.keyframe_before(k)
            if self.provisional:                   # key frames not known yet: go on when close, else seek by time
                if not (self._gen is not None and self._last < k <= self._last + self.EXACT_GOP):
                    self._seek(k)
            elif not (self._gen is not None and self._last < k and (kf <= self._last or k - self._last <= 2)):
                self._seek(kf)                     # (the next frame or two: read on, never seek; playing an
                                                   # intra-only video would otherwise seek before every frame)
            f = self._advance_to(k)
            if f is None:                          # the seek landed after k, or k was skipped: again, in full
                self._seek(kf)
                f = self._advance_to(k, skip=False)
            if f is None:                          # start earlier
                i = int(np.searchsorted(self.keyframes, kf)) - 1
                self._seek(int(self.keyframes[i]) if i >= 0 else 0)
                f = self._advance_to(k, skip=False)
            if f is None:
                self._seek(0)
                f = self._advance_to(k, skip=False)
            if f is None:
                raise sio.ReadError('Frame %d could not be decoded.' % (k + 1))
            return f

    def frame_fast(self, k):
        k = int(k)
        with self.lock:
            f = self.cache.get(k)
            if f is not None:
                return f, k
            if self.provisional:                   # key frames not known yet: the frame the seek lands on
                if self._gen is not None and self._last < k <= self._last + self.EXACT_GOP:
                    return self.frame(k), k
                self._seek(k)
                for fr in self._gen:
                    t = fr.pts if fr.pts is not None else getattr(fr, 'dts', None)
                    idx = self._k_of(t)
                    self._last = self._from = idx
                    f = prepare(sio._video_array(fr, self.info['pix_fmt'], self.cs), self.cs, self.dtype)
                    self.cache.put(idx, f)
                    return f, idx
                return self.frame(k), k
            kf = self.keyframe_before(k)
            near = (self._gen is not None and kf <= self._last < k and k - self._last <= self.EXACT_GOP)
            if near or k - kf <= self.EXACT_GOP:
                return self.frame(k), k
            return self.frame(kf), kf

    def cached(self, k):
        """frame k if it is in the cache, without waiting for a decode in progress (else None)"""
        if not self.lock.acquire(blocking=False):
            return None
        try:
            return self.cache.get(int(k))
        finally:
            self.lock.release()

    def is_cheap(self, k):
        """frame k comes at once: in the cache, or a few frames ahead of the decoder"""
        if k in self.cache:
            return True
        return self._gen is not None and self._last < k <= self._last + self.EXACT_GOP

    def iter_frames(self, stop=None, pts_out=None, small=None, skip=None):
        """(k, frame) start to end; with SMALL = (width, height) also the frame scaled down by FFmpeg
        (area averaging): (k, frame, small frame). Frames for which SKIP(k) is true (prepared already, from
        playback) are left out: an intra-only video does not even decode them, any other is decoded (the
        frames after need it) but not converted."""
        c = self.av.open(self.file)
        try:
            s = c.streams.video[0]
            s.thread_type = 'AUTO'
            pf = self.info['pix_fmt']

            def out(k, fr):
                f = prepare(sio._video_array(fr, pf, self.cs), self.cs, self.dtype)
                if small is None:
                    return k, f
                sm = fr.reformat(width=small[0], height=small[1], format='gray' if self.cs == 1 else 'rgb24',
                                 interpolation='AREA').to_ndarray()
                return k, f, sm
            intra = (skip is not None and not self.provisional and self.seekable and len(self.keyframes) == self.N)
            if intra:                              # one packet, one frame: skip the packet itself
                def frames():
                    for p in c.demux(s):
                        if stop is not None and stop.is_set():
                            return
                        t = p.pts if p.pts is not None else p.dts
                        if p.size and t is not None and skip(self._k_of(t)):
                            if pts_out is not None:
                                pts_out.append(int(t))
                            continue
                        for fr in p.decode():
                            yield fr
                for fr in frames():
                    if stop is not None and stop.is_set():
                        return
                    t = fr.pts if fr.pts is not None else getattr(fr, 'dts', None)
                    if pts_out is not None:
                        pts_out.append(t)
                    yield out(self._k_of(t), fr)
                if pts_out is not None:            # (in time order again)
                    pts_out.sort(key=lambda v: (v is None, v or 0))
                return
            k = 0
            for fr in c.decode(s):
                if stop is not None and stop.is_set():
                    return
                if pts_out is not None:
                    t = fr.pts if fr.pts is not None else getattr(fr, 'dts', None)
                    pts_out.append(t)
                if skip is None or not skip(k):
                    yield out(k, fr)
                k += 1
        finally:
            c.close()

    def close(self):
        try:
            self.c.close()
        except Exception:
            pass


class TiffSource(Source):
    """a TIFF stack, one page per frame, read page by page"""
    kind = 'tiff'

    def __init__(self, info, cache_bytes=None):
        super().__init__(info)
        import tifffile
        self.tifffile = tifffile
        self.t = tifffile.TiffFile(self.file)
        self.cache = FrameCache(cache_bytes or default_cache_bytes())

    def frame(self, k):
        k = int(k)
        with self.lock:
            f = self.cache.get(k)
            if f is None:
                f = prepare(self.t.pages[k].asarray(), self.cs, self.dtype)
                self.cache.put(k, f)
            return f

    def iter_frames(self, stop=None):
        with self.tifffile.TiffFile(self.file) as t:
            for k in range(self.N):
                if stop is not None and stop.is_set():
                    return
                yield k, prepare(t.pages[k].asarray(), self.cs, self.dtype)

    def close(self):
        try:
            self.t.close()
        except Exception:
            pass


class H5Source(Source):
    """an array in a MAT v7.3 (HDF5) file, read frame by frame"""
    kind = 'h5'

    def __init__(self, info, cache_bytes=None):
        super().__init__(info)
        import h5py
        self.h5py = h5py
        self.h = h5py.File(self.file, 'r')
        self.ds = self.h[info['var']]
        self.cache = FrameCache(cache_bytes or default_cache_bytes())

    def _get(self, ds, k):
        f = np.asarray(ds[k])
        return f.transpose(2, 1, 0) if self.info['C'] == 3 else f.T

    def frame(self, k):
        k = int(k)
        with self.lock:
            f = self.cache.get(k)
            if f is None:
                f = prepare(self._get(self.ds, k), self.cs, self.dtype)
                self.cache.put(k, f)
            return f

    def iter_frames(self, stop=None):
        with self.h5py.File(self.file, 'r') as h:
            ds = h[self.info['var']]
            for k in range(self.N):
                if stop is not None and stop.is_set():
                    return
                yield k, prepare(self._get(ds, k), self.cs, self.dtype)

    def close(self):
        try:
            self.h.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# the scrubbing copy: every frame, small and compressed, in memory
# ---------------------------------------------------------------------------
class ProxyStore:
    """Every frame of a video on disk, scaled to about the size it is shown at and JPEG-compressed
    (quality 90) in memory: ~100 - 200 KB a frame, decoded in a few ms. Dragging the slider shows
    these, so every frame appears as smoothly as from a recording in memory; the exact full-resolution
    frame replaces it as soon as the slider rests. (Video editors call this a proxy: a copy made
    for scrubbing, because long-GOP video can only be decoded from its key frames.)"""

    BITS_PER_PIXEL = {1: 0.9, 3: 1.3}               # JPEG q90, measured on 1080p video
    MAX_SIDE = 1280                               # about the size a frame is shown at

    def __init__(self, W, H, N, cs, budget_bytes=None):
        if budget_bytes is None:
            _, avail = memory_bytes()
            budget_bytes = int(min(1.2e9, 0.2 * avail))
        self.W, self.H, self.N, self.cs = W, H, N, cs
        bpp = self.BITS_PER_PIXEL[cs]
        for sc in (1.0, 0.75, 2 / 3., 0.5, 0.4, 1 / 3., 0.25, 0.2):
            if max(W, H) * sc <= self.MAX_SIDE and W * H * sc * sc * bpp / 8 * N <= budget_bytes:
                break
        self.scale = sc
        self.pw = max(2, int(round(W * sc / 2)) * 2)
        self.ph = max(2, int(round(H * sc / 2)) * 2)
        self.d = {}
        self.nbytes = 0
        self.lock = threading.Lock()
        from PIL import Image
        self.Image = Image

    def put(self, k, a):
        import io
        b = io.BytesIO()
        self.Image.fromarray(a).save(b, 'JPEG', quality=90)
        v = b.getvalue()
        with self.lock:
            if k not in self.d:
                self.d[k] = v
                self.nbytes += len(v)

    def put_full(self, k, f):
        """the scrubbing copy of a full-size frame (one the player decoded while playing)"""
        if k in self.d or f.dtype != np.uint8:
            return
        im = self.Image.fromarray(np.ascontiguousarray(f))
        r = int(min(f.shape[1] / self.pw, f.shape[0] / self.ph))
        if r > 1:
            im = im.reduce(r)
        if im.size != (self.pw, self.ph):
            im = im.resize((self.pw, self.ph), self.Image.BILINEAR)
        self.put(k, np.asarray(im))

    def get(self, k):
        import io
        v = self.d.get(k)
        if v is None:
            return None
        return np.asarray(self.Image.open(io.BytesIO(v)))

    def __contains__(self, k):
        return k in self.d

    def __len__(self):
        return len(self.d)

    @property
    def complete(self):
        return len(self.d) >= self.N


class SideFrames:
    """Frames the player decoded anyway (while playing, stepping), handed to the background pass: it
    prepares them (traces, scrubbing copy, memory) without decoding them again, and leaves them out when
    its own reading gets there. So preparing goes on, and gains, while the video plays."""
    MAX = 8                                       # waiting at most (frames are large)

    def __init__(self):
        self.q = collections.deque()
        self.lock = threading.Lock()
        self.done = None                          # (the pass's: frame k prepared)

    def offer(self, k, f):
        d = self.done
        if d is None or not (0 <= k < len(d)) or d[k]:
            return
        with self.lock:
            if len(self.q) < self.MAX and all(j != k for j, _ in self.q):
                self.q.append((k, f))

    def take_all(self):
        with self.lock:
            items = list(self.q)
            self.q.clear()
        return items


class MemoryStore:
    """The whole recording at full resolution, filled by the background pass while the video already
    plays from disk. When it is complete the window moves to it: every frame exact and instant while
    dragging, as with a recording read into memory before it is shown (1.0.0), without the wait."""

    def __init__(self, N, H, W, cs, dtype):
        self.N = N
        self.data = np.empty((N, H, W, 3) if cs == 3 else (N, H, W), dtype)
        self.have = np.zeros(N, bool)
        self.n = 0
        self.lock = threading.Lock()                 # (the background pass and the player both put frames)

    def put(self, k, f):
        if not (0 <= k < self.N) or self.have[k] or f.shape != self.data.shape[1:]:
            return
        with self.lock:
            if not self.have[k]:
                self.data[k] = f
                self.have[k] = True
                self.n += 1

    def get(self, k):
        return self.data[k] if (0 <= k < self.N and self.have[k]) else None

    def __contains__(self, k):
        return 0 <= k < self.N and bool(self.have[k])

    def __len__(self):
        return self.n

    @property
    def complete(self):
        return self.n >= self.N


# ---------------------------------------------------------------------------
# opening
# ---------------------------------------------------------------------------
def open_source(path, var=None, mode='auto', mem_limit=None, cache_bytes=None, reduction=None, progress=None):
    """open a recording. MODE 'auto': videos, TIFF stacks and v7.3 MAT-files open from disk at once
    (fits_memory: the window then reads them into memory in the background, when they fit under
    MEM_LIMIT bytes); 'memory' reads into memory first; 'disk' stays on disk. Files that cannot be read
    frame by frame (v5 MAT-files, single-array TIFFs) and REDUCTION (binning, every n-th frame, range,
    grey) are read into memory first. PROGRESS(fraction) -> True cancels (returns None)."""
    info = sio.probe(path, var)
    p = sio.default_reduction(info)
    if reduction:
        p.update(reduction)
    reduced = p['bin'] > 1 or p['step'] > 1 or p['first'] > 1 or p['last'] < info['N'] or (info['Cs'] == 3 and p['gray'])
    est = sio.estimate_bytes(info, p)
    if mem_limit is None:
        mem_limit = default_memory_limit()
    streamable = info['type'] in ('video', 'tiff_pages') or (info['type'] == 'mat' and sio.is_v73(path))
    if reduced or not streamable or mode == 'memory':
        out = sio.read(info, p, progress)
        if out is None:
            return None
        data, mtr, kept = out
        if len(kept) == 0:
            raise sio.ReadError('No frame could be read.')
        if info['type'] == 'video' and len(kept) != info['N']:
            info['N'] = len(kept)
        src = ArraySource(info, data, mtr, kept, reduced)
        src.info_p = p
        return src
    if info['type'] == 'video':
        src = VideoSource(info, cache_bytes)
    elif info['type'] == 'tiff_pages':
        src = TiffSource(info, cache_bytes)
    else:
        src = H5Source(info, cache_bytes)
    src.fits_memory = mode == 'auto' and est <= mem_limit
    return src


# ---------------------------------------------------------------------------
# traces: one pass over every frame
# ---------------------------------------------------------------------------
def fast_mean(a, rgb):
    """mean of an array (rgb: luminance 0.299 R + 0.587 G + 0.114 B), channel by channel with exact
    integer sums (~10 times faster than a mean over the colour axis)"""
    acc = np.uint64 if np.issubdtype(a.dtype, np.integer) else np.float64
    if rgb:
        n = a.size // 3
        return (0.299 * float(a[..., 0].sum(dtype=acc)) + 0.587 * float(a[..., 1].sum(dtype=acc))
                + 0.114 * float(a[..., 2].sum(dtype=acc))) / max(1, n)
    return float(a.sum(dtype=acc)) / max(1, a.size)


def sample_stride(H, W, target=50000):
    return max(1, int(np.sqrt(H * W / float(target))))


def sample_indices(N, n=30):
    return set(np.unique(np.round(np.linspace(0, N - 1, min(n, N))).astype(int)).tolist())


def scan(src, masks=(), want_mean=True, want_samples=True, progress=None, stop=None, proxy=None, store=None, pause=None,
         side=None):
    """decode every frame once: the whole-frame mean, the mean inside every mask, ~30 evenly spaced
    frames (subsampled luminance) for display ranges, and (PROXY, a ProxyStore) the scrubbing copy of
    every frame, or (STORE, a MemoryStore) every frame itself. SIDE (SideFrames): frames the player has
    decoded meanwhile, prepared here as they come and not read again. While PAUSE (an Event) is set the
    pass reads nothing itself (the player is short of time), but still prepares those. PROGRESS(fraction
    of the frames prepared). Returns a dict, or None when stopped."""
    idxs = [np.flatnonzero(m.ravel()) for m in masks]
    N = src.N
    mean = np.full(N, np.nan) if want_mean else None
    rois = [np.full(N, np.nan) for _ in masks]
    done = np.zeros(N, bool)
    if side is not None:
        side.done = done
    samples = {}
    st = sample_stride(src.H, src.W)
    want = sample_indices(N) if want_samples else set()
    pts = [] if isinstance(src, VideoSource) else None
    kw = {'pts_out': pts} if pts is not None else {}
    pool, pending = None, collections.deque()
    use_proxy = proxy is not None and isinstance(src, VideoSource) and not proxy.complete
    if use_proxy:
        kw['small'] = (proxy.pw, proxy.ph)
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=max(1, min(4, (os.cpu_count() or 2) - 1)))
    state = dict(cap=N, n_seen=0, n_done=0, mean=mean, rois=rois, done=done)

    def process(k, f, sm=None):
        if k >= state['cap']:                    # more frames than the index said: grow
            grow = max(16, N // 10)
            state['cap'] += grow
            if state['mean'] is not None:
                state['mean'] = np.r_[state['mean'], np.full(grow, np.nan)]
            state['rois'] = [np.r_[r, np.full(grow, np.nan)] for r in state['rois']]
            state['done'] = np.r_[state['done'], np.zeros(grow, bool)]
            if side is not None:
                side.done = state['done']
        if state['done'][k]:
            return
        if store is not None:
            store.put(k, f)
        if pool is not None and k not in proxy:          # JPEG encoding in other threads
            pending.append(pool.submit(proxy.put, k, sm) if sm is not None else pool.submit(proxy.put_full, k, f))
            while len(pending) > 32:
                pending.popleft().result()
        rgb = src.is_rgb
        flat = f.reshape(-1, 3) if rgb else f.ravel()
        if state['mean'] is not None:
            state['mean'][k] = fast_mean(f, rgb)
        for r, ix in zip(state['rois'], idxs):
            r[k] = fast_mean(flat[ix], rgb)
        if k in want:
            samples[k] = sio.lum(f[::st, ::st]).copy()
        state['done'][k] = True
        state['n_done'] += 1
        state['n_seen'] = max(state['n_seen'], k + 1)
        if progress is not None and state['n_done'] % 20 == 0:
            progress(min(1.0, state['n_done'] / max(1, N)))

    def drain():
        if side is not None:
            for k, f in side.take_all():
                if f is not None and f.shape[:2] == (src.H, src.W):
                    process(k, f)

    skip = (lambda k: 0 <= k < len(state['done']) and bool(state['done'][k]))
    if isinstance(src, VideoSource):
        kw['skip'] = skip
    for item in src.iter_frames(stop=stop, **kw):
        drain()
        while pause is not None and pause.is_set() and not (stop is not None and stop.is_set()):
            drain()
            time.sleep(0.01)
        k, f = item[0], item[1]
        if skip(k):
            state['n_seen'] = max(state['n_seen'], k + 1)
            continue
        process(k, f, item[2] if len(item) > 2 else None)
    drain()
    if pool is not None:
        for fu in pending:
            fu.result()
        pool.shutdown()
    if stop is not None and stop.is_set():
        return None
    if side is not None:
        side.done = None
    n_seen = max(state['n_seen'], len(pts) if pts else 0)
    mean = state['mean'][:n_seen] if state['mean'] is not None else None
    rois = [r[:n_seen] for r in state['rois']]
    return dict(mean=mean, rois=rois, samples=samples, stride=st, n=n_seen, pts=pts)
