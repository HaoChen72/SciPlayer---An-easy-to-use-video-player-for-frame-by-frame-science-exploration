"""SciPlayer - reading recordings: videos (FFmpeg through PyAV), TIFF stacks and MAT-files.

Frames are numbered from 1 as in the MATLAB version. A frame is a numpy array
[H x W] (grey) or [H x W x 3] (colour); a loaded recording is [n x H x W] or
[n x H x W x 3] (frames first, so that one frame is one contiguous block).
"""
import os
import threading

import numpy as np

VIDEO_EXT = ['.avi', '.mp4', '.m4v', '.mov', '.mkv', '.wmv', '.mpg', '.mpeg', '.mj2', '.mjpg', '.mjpeg',
             '.webm', '.flv', '.ogv', '.3gp', '.ts', '.mts', '.m2ts', '.vob', '.gif']
STACK_EXT = ['.tif', '.tiff', '.mat']
ALL_EXT = VIDEO_EXT + STACK_EXT
FPS_NAMES = ['fps', 'frame_rate', 'FrameRate', 'framerate', 'fs']
NUMERIC = ('uint8', 'uint16', 'uint32', 'int8', 'int16', 'int32', 'single', 'double', 'float32', 'float64', 'logical', 'bool')


class ReadError(Exception):
    pass


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def bytes_per(dtype):
    return np.dtype(dtype).itemsize


def lum(f):
    """luminance of a colour frame (float32); a grey frame as float32"""
    if f.ndim == 3 and f.shape[2] >= 3:
        f = f.astype(np.float32, copy=False)
        return 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]
    return f.astype(np.float32, copy=False)


def shrink(a, s, exact=False):
    """the mean of every S x S block of pixels (a frame drawn at the resolution it is shown at: the
    screen cannot show more, and drawing 12 megapixels into a few hundred thousand on every frame made
    dragging and playing slow). The edge beyond whole blocks (< S pixels) is left out. 8-bit frames
    come back rounded to whole grey levels (for the eye), unless EXACT (float32: for dF/F, where half a
    grey level of a dim pixel is several %)."""
    if s <= 1:
        return a
    h, w = a.shape[0] // s, a.shape[1] // s
    if h < 1 or w < 1:
        return a
    a = a[:h * s, :w * s]
    rest = a.shape[2:]
    if not exact and a.dtype == np.uint8 and (a.ndim == 2 or a.shape[2] == 3):
        from PIL import Image
        return np.asarray(Image.fromarray(np.ascontiguousarray(a)).reduce(s))
    if a.dtype == np.float32 and a.ndim == 2:
        from PIL import Image
        return np.asarray(Image.fromarray(np.ascontiguousarray(a)).reduce(s))
    # rows of each block first (contiguous memory: fast), then its columns; exact integer sums
    if a.dtype == np.uint8 and s <= 257:
        acc1, acc2 = np.uint16, np.uint32
    elif a.dtype.kind in 'ui' and a.dtype.itemsize <= 2 and s <= 255:
        acc1, acc2 = np.uint32, np.uint32
    elif a.dtype.kind in 'ui':
        acc1, acc2 = np.uint64, np.uint64
    else:
        acc1 = acc2 = np.float64
    acc = _scratch((h,) + a.shape[1:], acc1)      # the S rows of every block, added slice by slice
    np.copyto(acc, a[0::s], casting='unsafe')
    for i in range(1, s):
        np.add(acc, a[i::s], out=acc, casting='unsafe')
    b = _scratch((h, w) + rest, acc2, 1)          # then its S columns
    np.copyto(b, acc[:, 0::s], casting='unsafe')
    for i in range(1, s):
        np.add(b, acc[:, i::s], out=b, casting='unsafe')
    return (b / float(s * s)).astype(np.float32)


_tls = threading.local()


def _scratch(shape, dtype, slot=0):
    """a working array kept for the next frame (per thread): a new large array on every frame costs as
    much as the sums themselves (Windows maps fresh memory page by page)"""
    d = getattr(_tls, 'd', None)
    if d is None:
        d = _tls.d = {}
    key = (slot, shape, np.dtype(dtype).str)
    a = d.get(key)
    if a is None:
        for k in [k for k in d if k[0] == slot]:
            del d[k]
        a = d[key] = np.empty(shape, dtype)
    return a


GREY_LOOKS = 9                                   # frames looked at, spread over the recording


def spread(n, m=GREY_LOOKS):
    """M frame indices (0-based) spread evenly over N frames, first and last included"""
    return sorted(set(np.round(np.linspace(0, max(0, n - 1), min(max(n, 1), m))).astype(int).tolist()))


def all_grey(frames):
    """a grey recording stored as colour: every frame looked at, spread over the recording, has channels
    that agree. One frame in colour keeps the colour: a colour video often starts black or grey (a
    fade-in, a dark first frame, a title), and its first frame alone made it grey (before 1.3.5)"""
    for f in frames:
        f = _rgb(f)
        st = max(1, int(np.sqrt(f.shape[0] * f.shape[1] / 250000.0)))
        if not is_grey(f[::st, ::st]):
            return False
    return True


def is_grey(f):
    """a colour frame whose channels agree (grey video stored as RGB; lossy codecs leave
    a few levels of difference): mean |R-G| + |R-B| within 2 % of the range, maximum within 5 %"""
    if f.ndim != 3 or f.shape[2] < 3:
        return True
    if np.issubdtype(f.dtype, np.integer):
        r = float(np.iinfo(f.dtype).max)
    else:
        r = max(1e-12, float(np.nanmax(np.abs(f))))
    a = f.astype(np.float32)
    d = np.abs(a[..., 0] - a[..., 1]) + np.abs(a[..., 0] - a[..., 2])
    return d.mean() <= 0.02 * r and d.max() <= 0.05 * r


def bin_frame(f, b):
    """b x b block average, in the frame's own type"""
    if b <= 1:
        return f
    H = (f.shape[0] // b) * b
    W = (f.shape[1] // b) * b
    x = f[:H, :W].astype(np.float32)
    if x.ndim == 2:
        x = x.reshape(H // b, b, W // b, b).mean(axis=(1, 3))
    else:
        x = x.reshape(H // b, b, W // b, b, x.shape[2]).mean(axis=(1, 3))
    if np.issubdtype(f.dtype, np.integer):
        x = np.rint(x)
    return x.astype(f.dtype)


def to_grey(f):
    """colour frame -> grey frame in its own type"""
    g = lum(f)
    if np.issubdtype(f.dtype, np.integer):
        g = np.clip(np.rint(g), np.iinfo(f.dtype).min, np.iinfo(f.dtype).max)
    return g.astype(f.dtype)


def size_text(mb):
    return '%.2f GB' % (mb / 1000) if mb >= 1000 else '%.0f MB' % mb


def is_v73(path):
    try:
        with open(path, 'rb') as fh:
            hdr = fh.read(116)
        return b'MATLAB 7.3' in hdr
    except OSError:
        return False


# ---------------------------------------------------------------------------
# MAT-files
# ---------------------------------------------------------------------------
def mat_arrays(path):
    """arrays with 3 or more dimensions in a MAT-file: [(name, matlab_shape, class)], largest first"""
    out = []
    if is_v73(path):
        import h5py
        with h5py.File(path, 'r') as h:
            for k, v in h.items():
                if isinstance(v, h5py.Dataset) and v.ndim >= 3:
                    cls = v.attrs.get('MATLAB_class', b'')
                    cls = cls.decode() if isinstance(cls, bytes) else str(cls)
                    if cls in NUMERIC or (not cls and v.dtype.kind in 'uifb'):
                        out.append((k, tuple(v.shape[::-1]), cls or str(v.dtype)))
    else:
        import scipy.io
        for name, shape, cls in scipy.io.whosmat(path):
            if len(shape) >= 3 and cls in NUMERIC:
                out.append((name, tuple(shape), cls))
    out.sort(key=lambda t: -int(np.prod(t[1])))
    return out


def _mat_fps(path):
    try:
        if is_v73(path):
            import h5py
            with h5py.File(path, 'r') as h:
                for nm in FPS_NAMES:
                    if nm in h and isinstance(h[nm], h5py.Dataset) and h[nm].size == 1:
                        v = float(np.asarray(h[nm]).ravel()[0])
                        if v > 0:
                            return v
        else:
            import scipy.io
            names = [w[0] for w in scipy.io.whosmat(path)]
            for nm in FPS_NAMES:
                if nm in names:
                    v = scipy.io.loadmat(path, variable_names=[nm])[nm]
                    if np.size(v) == 1 and float(np.ravel(v)[0]) > 0:
                        return float(np.ravel(v)[0])
    except Exception:
        pass
    return float('nan')


# ---------------------------------------------------------------------------
# what a file holds, without reading it all
# ---------------------------------------------------------------------------
def probe(path, var=None):
    ext = os.path.splitext(path)[1].lower()
    info = dict(file=path, type='', H=0, W=0, C=1, Cs=1, N=0, dtype='uint8', fps=float('nan'), var='',
                rgb_is_grey=False, pix_fmt='')
    if ext in ('.tif', '.tiff'):
        import tifffile
        with tifffile.TiffFile(path) as t:
            npages = len(t.pages)
            if npages > 1:
                f1 = t.pages[0].asarray()
                info.update(type='tiff_pages', N=npages)
                look = lambda: [t.pages[k].asarray() for k in spread(npages)]
            else:
                a = t.asarray()
                if a.ndim == 2 or (a.ndim == 3 and a.shape[2] in (3, 4)):
                    info.update(type='tiff_array', N=1)
                    f1 = a
                    look = lambda: [a]
                else:
                    info.update(type='tiff_array', N=a.shape[0])
                    f1 = a[0]
                    look = lambda: [a[k] for k in spread(a.shape[0])]
            f1 = _rgb(f1)
            looked = look() if (f1.ndim == 3 and all_grey([f1])) else [f1]
    elif ext == '.mat':
        arrs = mat_arrays(path)
        if not arrs:
            raise ReadError('The MAT-file holds no numeric array with 3 or more dimensions.')
        if var is None:
            var = arrs[0][0]
        name, shape, cls = [a for a in arrs if a[0] == var][0]
        info.update(type='mat', var=name)
        if len(shape) == 4 and shape[2] == 3:
            info.update(N=shape[3], C=3)
        else:
            info.update(N=int(np.prod(shape[2:])), C=1)
        info.update(H=shape[0], W=shape[1], Cs=info['C'], fps=_mat_fps(path))
        f1 = mat_frame(info, 1)
        info['dtype'] = str(f1.dtype)
        if info['C'] == 3:
            looked = [f1]
            if all_grey([f1]):                       # the rest of the recording too
                if is_v73(path):
                    looked = [mat_frame(info, k + 1) for k in spread(info['N'])]
                else:
                    import scipy.io
                    a = scipy.io.loadmat(path, variable_names=[name])[name]
                    looked = [_mat_slice(a, info, k + 1) for k in spread(info['N'])]
            info['rgb_is_grey'] = all_grey(looked)
            info['Cs'] = 1 if info['rgb_is_grey'] else 3
        return info
    else:
        import av
        try:
            c = av.open(path)
        except Exception as e:
            raise ReadError('FFmpeg cannot open it: %s' % e)
        try:
            if not c.streams.video:
                raise ReadError('The file holds no video stream.')
            s = c.streams.video[0]
            fps = float(s.average_rate or s.base_rate or s.guessed_rate or 0) or float('nan')
            n = int(s.frames or 0)
            if n <= 0:
                dur = None
                if s.duration is not None and s.time_base is not None:
                    dur = float(s.duration * s.time_base)
                elif c.duration:
                    dur = c.duration / 1e6
                n = int(round(dur * fps)) if (dur and np.isfinite(fps)) else 0
            pf = s.codec_context.pix_fmt or ''
            v0 = float(s.start_time * s.time_base) if (s.start_time is not None and s.time_base is not None) else 0.0
            info.update(type='video', fps=fps, N=n, pix_fmt=pf, v0=v0)
            f1 = None
            for fr in c.decode(s):
                f1 = _video_array(fr, pf)
                break
            if f1 is None:
                raise ReadError('No frame could be decoded.')
        finally:
            c.close()
        looked = [f1]
        if f1.ndim == 3 and f1.shape[2] >= 3 and all_grey([f1]) and n > 1:
            looked += _video_looks(path, n, fps)           # grey so far: the rest of the video too
        if info['N'] <= 0:
            info['N'] = 1
    info.update(H=f1.shape[0], W=f1.shape[1], C=f1.shape[2] if f1.ndim == 3 else 1, dtype=str(f1.dtype))
    info['rgb_is_grey'] = info['C'] == 3 and all_grey(looked)
    info['Cs'] = 3 if (info['C'] == 3 and not info['rgb_is_grey']) else 1
    return info


def _video_looks(path, n, fps, budget_s=0.35, m=6, ahead=12):
    """M frames spread over a video, as small copies (enough to see colour), within BUDGET_S. After a seek
    it decodes on towards the frame wanted (at most AHEAD frames): a long group of pictures starts with a key
    frame that may be from the black or grey start of the video. MJPEG is decoded at 1/8 size (almost free)."""
    import time, av
    out = []
    c = av.open(path)
    try:
        s = c.streams.video[0]
        if (s.codec_context.name or '') == 'mjpeg':
            s.codec_context.options = {'lowres': '3'}
        s.thread_type = 'AUTO'
        tb = float(s.time_base)
        t0 = int(s.start_time) if s.start_time is not None else 0
        if s.duration:
            span = int(s.duration)
        elif np.isfinite(fps) and fps > 0:
            span = int(n / fps / tb)
        else:
            return out
        end = time.perf_counter() + budget_s
        for k in spread(n, m)[1:]:
            if time.perf_counter() > end:
                break
            target = t0 + int(span * k / float(n))
            c.seek(target, stream=s, backward=True, any_frame=False)
            got, j = None, 0
            for fr in c.decode(s):
                got, j = fr, j + 1
                if (fr.pts is not None and fr.pts >= target) or j >= ahead or time.perf_counter() > end:
                    break
            if got is not None:
                sc = min(1.0, 480.0 / max(1, got.width, got.height))
                out.append(got.reformat(width=max(2, int(got.width * sc) // 2 * 2),
                                        height=max(2, int(got.height * sc) // 2 * 2), format='rgb24').to_ndarray())
    except Exception:
        pass
    finally:
        c.close()
    return out


def _rgb(f):
    if f.ndim == 3 and f.shape[2] == 4:
        f = f[..., :3]
    if f.ndim == 3 and f.shape[2] == 1:
        f = f[..., 0]
    return f


def _video_array(fr, pf, cs=3):
    """a decoded frame as an array; CS = 1: grey, converted by FFmpeg (the luma, scaled to the full
    range: the same as the luminance of the RGB frame within rounding, and ~100 times faster)"""
    hi = any(t in pf for t in ('48', '64', '16le', '16be', 'p10', 'p12', 'p16', '10le', '12le'))
    if pf.startswith('gray') or cs == 1:
        return fr.to_ndarray(format='gray16le' if (hi or (pf.startswith('gray') and pf != 'gray')) else 'gray')
    if any(t in pf for t in ('48', '64', '16le', '16be', 'p10', 'p12', 'p16')):
        return fr.to_ndarray(format='rgb48le')
    return fr.to_ndarray(format='rgb24')


def mat_frame(info, k):
    """frame k (1-based) of a MAT-file array"""
    if is_v73(info['file']):
        import h5py
        with h5py.File(info['file'], 'r') as h:
            ds = h[info['var']]
            if info['C'] == 3:
                return np.asarray(ds[k - 1]).transpose(2, 1, 0)     # h5: [N 3 W H]
            return np.asarray(ds[k - 1]).T                           # h5: [N W H]
    import scipy.io
    a = scipy.io.loadmat(info['file'], variable_names=[info['var']])[info['var']]
    return _mat_slice(a, info, k)


def _mat_slice(a, info, k):
    if info['C'] == 3:
        return a[:, :, :, k - 1]
    return a.reshape(a.shape[0], a.shape[1], -1, order='F')[:, :, k - 1]


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def estimate_bytes(info, p):
    n = len(range(p['first'], p['last'] + 1, p['step']))
    cs = 1 if p['gray'] else info['Cs']
    return (info['H'] // p['bin']) * (info['W'] // p['bin']) * cs * n * bytes_per(info['dtype'])


def default_reduction(info):
    return dict(bin=1, step=1, first=1, last=info['N'], gray=info['Cs'] == 1)


def suggest_reduction(info, limit_bytes):
    """2 x 2 (then 4 x 4) binning first, then every n-th frame, to fit the limit"""
    p = default_reduction(info)
    for b in (1, 2, 4):
        p['bin'] = b
        if estimate_bytes(info, p) <= limit_bytes:
            break
    p['step'] = max(1, int(np.ceil(estimate_bytes(info, p) / limit_bytes)))
    return p


def reduction_text(info, p):
    c = []
    if p['bin'] > 1:
        c.append('%d x %d binning' % (p['bin'], p['bin']))
    if p['step'] > 1:
        c.append('every %d-th frame' % p['step'])
    if p['first'] > 1 or p['last'] < info['N']:
        c.append('frames %d-%d' % (p['first'], p['last']))
    if info['Cs'] == 3 and p['gray']:
        c.append('grey')
    return ', '.join(c)


def read(info, p, progress=None):
    """read the frames kept by P into memory. Returns (data, mean_trace, kept); kept = recorded
    frame numbers (1-based). PROGRESS(fraction) returning True cancels (returns None)."""
    idx = list(range(p['first'], p['last'] + 1, p['step']))
    n = len(idx)
    Hb, Wb = info['H'] // p['bin'], info['W'] // p['bin']
    cs = 1 if p['gray'] else info['Cs']
    dt = np.dtype(info['dtype'])
    shape = (n, Hb, Wb, 3) if cs == 3 else (n, Hb, Wb)
    data = np.zeros(shape, dt)
    mtr = np.full(n, np.nan)
    kept = np.zeros(n, int)
    i = 0

    def put(f, k):
        nonlocal i
        f = _rgb(f)
        if f.ndim == 3 and cs == 1:
            f = to_grey(f)
        f = bin_frame(f, p['bin'])
        if f.dtype != dt:
            f = f.astype(dt)
        h_, w_ = min(Hb, f.shape[0]), min(Wb, f.shape[1])
        data[i, :h_, :w_] = f[:h_, :w_]
        mtr[i] = float(lum(data[i]).mean()) if cs == 3 else float(data[i].mean(dtype=np.float64))
        kept[i] = k
        i += 1

    def tick():
        return progress is not None and i % 25 == 0 and progress(i / max(1, n))

    if info['type'] == 'video':
        import av
        c = av.open(info['file'])
        try:
            s = c.streams.video[0]
            s.thread_type = 'AUTO'
            k = 0
            for fr in c.decode(s):
                k += 1
                if k > p['last'] or i >= n:
                    break
                if k < p['first'] or (k - p['first']) % p['step']:
                    continue
                put(_video_array(fr, info['pix_fmt'], cs), k)
                if tick():
                    return None
        finally:
            c.close()
    elif info['type'] == 'tiff_pages':
        import tifffile
        with tifffile.TiffFile(info['file']) as t:
            for k in idx:
                put(t.pages[k - 1].asarray(), k)
                if tick():
                    return None
    elif info['type'] == 'tiff_array':
        import tifffile
        a = tifffile.imread(info['file'])
        if info['N'] == 1:
            a = a[None]
        for k in idx:
            put(a[k - 1], k)
            if tick():
                return None
    elif info['type'] == 'mat':
        if is_v73(info['file']):
            import h5py
            with h5py.File(info['file'], 'r') as h:
                ds = h[info['var']]
                for k in idx:
                    f = np.asarray(ds[k - 1])
                    put(f.transpose(2, 1, 0) if info['C'] == 3 else f.T, k)
                    if tick():
                        return None
        else:
            # a MAT-file before v7.3 cannot be read in parts: the array is loaded once
            import scipy.io
            a = scipy.io.loadmat(info['file'], variable_names=[info['var']])[info['var']]
            for k in idx:
                put(_mat_slice(a, info, k), k)
                if tick():
                    return None
            del a
    if i < n:
        data, mtr, kept = data[:i], mtr[:i], kept[:i]
    return data, mtr, kept


# ---------------------------------------------------------------------------
# frames, ROI masks
# ---------------------------------------------------------------------------
def parse_frames(s, N):
    """'1-10', '1:10', '1-10, 200-210', '5 7 9' -> sorted frame numbers within 1..N"""
    import re
    out = set()
    for tok in re.split(r'[,;\s]+', s.strip()):
        if not tok:
            continue
        v = [float(x) for x in re.findall(r'\d+(?:\.\d*)?', tok)]
        if len(v) == 1:
            out.add(int(round(v[0])))
        elif len(v) >= 2:
            out.update(range(int(round(v[0])), int(round(v[-1])) + 1))
    return sorted(b for b in out if 1 <= b <= N)


def segments(b):
    """contiguous runs of frame numbers -> [(first, last), ...]"""
    b = sorted(b)
    segs = []
    for v in b:
        if segs and v == segs[-1][1] + 1:
            segs[-1][1] = v
        else:
            segs.append([v, v])
    return [tuple(s) for s in segs]


def polygon_mask(xy, H, W):
    """pixels (centres at 1..W, 1..H, as in MATLAB) inside or on the closed outline XY ([n x 2]);
    even-odd rule, like MATLAB's inpolygon, by scanlines"""
    xy = np.asarray(xy, float)
    mask = np.zeros((H, W), bool)
    x0, y0 = xy[:, 0], xy[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    r0 = max(1, int(np.floor(y0.min())))
    r1 = min(H, int(np.ceil(y0.max())))
    eps = 1e-9
    for r in range(r0, r1 + 1):
        y = float(r)
        cond = ((y0 <= y) & (y1 > y)) | ((y1 <= y) & (y0 > y))
        if cond.any():
            xc = x0[cond] + (y - y0[cond]) * (x1[cond] - x0[cond]) / (y1[cond] - y0[cond])
            xc.sort()
            for a, b in zip(xc[0::2], xc[1::2]):
                c0 = max(1, int(np.ceil(a - eps)))
                c1 = min(W, int(np.floor(b + eps)))
                if c1 >= c0:
                    mask[r - 1, c0 - 1:c1] = True
    # points on the outline itself (horizontal edges and vertices on a pixel row)
    for xa, ya, xb, yb in zip(x0, y0, x1, y1):
        if abs(ya - yb) < eps and abs(ya - round(ya)) < eps and 1 <= round(ya) <= H:
            c0 = max(1, int(np.ceil(min(xa, xb) - eps)))
            c1 = min(W, int(np.floor(max(xa, xb) + eps)))
            if c1 >= c0:
                mask[int(round(ya)) - 1, c0 - 1:c1] = True
    return mask


def roi_trace(data, mask, is_rgb):
    """mean inside MASK in every frame (luminance for colour), in blocks of frames"""
    n = data.shape[0]
    tr = np.zeros(n)
    idx = np.flatnonzero(mask.ravel())
    bs = max(1, int(2e7 // max(1, idx.size)))
    for k0 in range(0, n, bs):
        blk = data[k0:k0 + bs]
        if is_rgb:
            X = blk.reshape(blk.shape[0], -1, 3)[:, idx, :].astype(np.float32)
            tr[k0:k0 + bs] = (0.299 * X[..., 0] + 0.587 * X[..., 1] + 0.114 * X[..., 2]).mean(axis=1)
        else:
            tr[k0:k0 + bs] = blk.reshape(blk.shape[0], -1)[:, idx].mean(axis=1, dtype=np.float64)
    return tr
