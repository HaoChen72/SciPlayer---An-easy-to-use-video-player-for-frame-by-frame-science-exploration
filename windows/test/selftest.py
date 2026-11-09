import os, sys, time, numpy as np
os.environ['SCIPLAYER_TEST'] = '1'
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app'))
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import Qt
import sciplayer as sp, sciplayer_io as sio
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(['t'])
nf = 0
def chk(c, m):
    global nf
    print(('PASS  ' if c else 'FAIL  ') + m); nf += (not c)
truth = np.load('truth_u8.npy')
w = sp.Player(); w.resize(1500, 940); w.show(); app.processEvents()
# a recording opens at once from disk and is read into memory in the background (when it fits): most
# checks below look at the result of that, so they wait for it (load_now: the moment it opens)
load_now = w.load_file
def load_wait(*a, **k):
    ok = load_now(*a, **k)
    if ok and k.get('mode', 'auto') == 'auto':
        w.wait_traces()
    return ok
w.load_file = load_wait
# --- every format reads, with the right size and frame rate
for f, fps, exact in [('grey_ffv1.avi', 20, True), ('grey_mjpeg.avi', 20, False), ('colour_h264.mp4', 20, False),
                      ('stack_u16.tif', np.nan, False), ('stack_v5.mat', 20, False), ('stack_v73.mat', 20, True)]:
    ok = w.load_file(os.path.abspath(f)); app.processEvents()
    good = ok and w.N == 120 and (w.H, w.W) == (96, 128) and (np.isnan(fps) and np.isnan(w.fps) or abs(w.fps - fps) < 1e-6)
    extra = ''
    if exact:
        good = good and np.array_equal(w.src.data, truth); extra = ', frames identical to the truth'
    else:
        tr = truth.mean(axis=(1, 2)); cc = np.corrcoef(w.mean_trace, tr)[0, 1]
        good = good and cc > 0.995; extra = ', mean trace follows the truth (r = %.4f)' % cc
    chk(good, '%s: %d frames %s, rgb=%s, fps %s%s' % (f, w.N, w.src.data.shape[1:], w.is_rgb, w.fps, extra))
# MAT v5 picks the 3-D 'movie' (largest), not 'small'
w.load_file(os.path.abspath('stack_v5.mat')); chk(w.finfo['var'] == 'movie' and w.src.data.dtype == np.float32, 'MAT v5: array chosen, single kept')
# --- grey AVI: traces, relative change
w.load_file(os.path.abspath('grey_ffv1.avi'))
tr = truth.reshape(120, -1).mean(1)
chk(np.allclose(w.mean_trace, tr), 'whole-frame trace = truth')
chk(abs(w.x[-1] - 119 / 20) < 1e-9, 'time axis from the frame rate')
w.set_view('relative'); w.set_baseline('1-10'); app.processEvents()
r = w.trace_rows[0]['y']; true_rel = (tr - tr[:10].mean()) / tr[:10].mean() * 100
chk(np.allclose(r, true_rel), 'relative whole-frame trace (global +10 %% -> %.1f %%)' % r[45])
w.goto(80); app.processEvents()
d = w.img2.image
chk(abs(np.nanmean(d[30:41, 50:66]) - 50) < 3 and abs(np.nanmean(d[:20, 100:])) < 2, 'relative-change image: +50 %% square (%.1f)' % np.nanmean(d[30:41, 50:66]))
chk(w.l_range.isEnabled() and w.c_cmap.isEnabled(), 'dF/F controls active in the relative view')
w.set_range('60'); chk(w.clim_dff == (-60, 60), 'range 60 -> [-60 60]'); w.set_range('-5 20'); chk(w.clim_dff == (-5, 20), 'range -5 20')
w.set_range('auto'); chk(w.range_str == 'auto' and w.clim_dff[1] > 0, 'range auto (%.3g)' % w.clim_dff[1])
for c in sp.CMAP_NAMES: w.set_cmap(c)
chk(True, 'all colour maps')
# --- ROIs: scripted drags
w.draw_path('rect', [(51, 31), (55, 35), (60, 39), (66, 41)])
chk(len(w.rois) == 1 and w.rois[0]['mask'].sum() == 16 * 11, 'rect drag -> 16 x 11 px (%d)' % w.rois[0]['mask'].sum())
chk(np.allclose(w.rois[0]['trace'], truth[:, 30:41, 50:66].reshape(120, -1).mean(1)), 'rect ROI trace = truth')
th = np.linspace(0, 2 * np.pi, 120)[:-1]; path = np.c_[90 + 10 * np.cos(th), 50 + 10 * np.sin(th)]
w.draw_path('freehand', path)
m = w.rois[1]['mask']; rr, cc = np.nonzero(m)
chk(abs(m.sum() - np.pi * 100) < 15 and np.hypot(cc + 1 - 90, rr + 1 - 50).max() <= 10.01, 'freehand circle -> disk (%d px, pi r^2 = 314)' % m.sum())
w.draw_path('rect', [(10, 10)]); w.draw_path('freehand', [(10, 10), (11, 10)])
chk(len(w.rois) == 2 and w.drawing is None, 'a click / a stroke without area adds nothing')
w.draw_path('rect', [(-20, -20), (5, 6)]); chk(len(w.rois) == 3 and w.rois[2]['mask'].sum() == 30, 'drag from beside the frame is clipped')
w.draw_path('freehand', path - [40, 0], panel=2); chk(len(w.rois) == 4, 'freehand on the relative panel')
w.remove_roi([2]); chk([r['name'] for r in w.rois] == ['ROI 1', 'ROI 2', 'ROI 4'], 'remove ROI 3')
chk(len(w.trace_rows) == 4, 'one trace row per signal')
# drawing state machine directly: down/move/up via view boxes, Esc cancels
w.draw_start('freehand'); chk(w.title.text().startswith('ROI freehand'), 'title says how to draw'); w.draw_end()
chk(w.drawing is None and w.title.text().startswith('frame'), 'Esc / cancel restores the title')
# --- export
w.export_csv('/tmp/tr.csv'); L = open('/tmp/tr.csv').read().splitlines()
hdr = L[4].split(','); row = L[5 + 80].split(',')
chk(L[1].startswith('% ROI 1 outline x:') and hdr[:4] == ['frame', 'recorded_frame', 'time_s', 'whole_frame_mean'] and len(L) == 5 + 120, 'CSV layout')
chk(abs(float(row[3]) - tr[80]) < 1e-3 and abs(float(row[2]) - 4.0) < 1e-9, 'CSV values')
w.goto(80); chk(w.save_view('/tmp/view_rel.png') and os.path.getsize('/tmp/view_rel.png') > 20000, 'save view PNG')
# --- brightness and contrast: how the original is drawn, never its values
im1, im2, f80 = w.img1.image.copy(), w.img2.image.copy(), w.frame(80).copy()
ys = [r['y'].copy() for r in w.trace_rows]; csv0 = open('/tmp/tr.csv').read()
chk(np.allclose(w.img1.levels, w.clim_raw) and not w.b_look_reset.isEnabled(), 'brightness and contrast at 0: the normal display range')
w.s_bright.setValue(40); w.s_contrast.setValue(50); app.processEvents()
lo, hi = w.clim_raw; wd = (hi - lo) / 2; mid = (lo + hi) / 2 - 0.4 * (hi - lo)
chk(np.allclose(w.img1.levels, (mid - wd / 2, mid + wd / 2)) and w.b_look_reset.isEnabled(),
    'brightness +40, contrast +50: display range %.3g..%.3g (normal %.3g..%.3g)' % (tuple(w.img1.levels) + tuple(w.clim_raw)))
chk(np.array_equal(w.img1.image, im1) and np.array_equal(w.frame(80), f80), 'the drawn values and the frame are unchanged')
chk(np.array_equal(w.img2.image, im2, equal_nan=True) and all(np.array_equal(a, r['y'], equal_nan=True) for a, r in zip(ys, w.trace_rows)),
    'dF/F image and every trace unchanged')
w.export_csv('/tmp/tr_bc.csv'); chk(open('/tmp/tr_bc.csv').read() == csv0, 'exported CSV identical')
w.goto(81); w.goto(80); app.processEvents()
chk(np.allclose(w.img1.levels, (mid - wd / 2, mid + wd / 2)), 'kept while stepping through frames')
w.s_contrast.setValue(-100); lv = w.img1.levels; chk(np.isclose(lv[1] - lv[0], 4 * (hi - lo)), 'contrast -100: 4 x the range (flatter)')
w.s_bright.mouseDoubleClickEvent(QtGui.QMouseEvent(QtCore.QEvent.MouseButtonDblClick, QtCore.QPointF(5, 5), QtCore.QPointF(5, 5),
                                                    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
chk(w.s_bright.value() == 0 and w.s_contrast.value() == -100, 'double-click: that slider back to 0')
w.b_look_reset.click(); chk(np.allclose(w.img1.levels, w.clim_raw) and not w.b_look_reset.isEnabled(), 'Reset: both back to 0')
# --- playback: real time at the frame rate
w.goto(0); t0 = time.perf_counter(); w.play(20)
while w.b_play.isChecked() and time.perf_counter() - t0 < 5: app.processEvents(); time.sleep(0.001)
dt = time.perf_counter() - t0; chk(0.85 < dt < 1.5 and w.cur == 20, 'play 20 frames at 20 Hz: %.2f s' % dt)
w.set_fps('40'); w.goto(0); t0 = time.perf_counter(); w.play(20)
while w.b_play.isChecked() and time.perf_counter() - t0 < 5: app.processEvents(); time.sleep(0.001)
dt = time.perf_counter() - t0; chk(0.4 < dt < 0.9 and abs(w.x[-1] - 119 / 40) < 1e-9, 'one frame rate: 40 Hz plays in %.2f s and rescales time' % dt)
w.set_fps(''); chk(np.isnan(w.fps) and w.play_rate() == 10 and w.x[-1] == 120, 'empty rate: frame numbers, 10 frames/s')
w.goto(119); w.cb_loop.setChecked(True); w.play(3)
while w.b_play.isChecked(): app.processEvents(); time.sleep(0.001)
chk(w.cur == 2, 'loop wraps around')
# --- navigation
s0 = w.split.sizes(); w.split.moveSplitter(int(s0[0] * 0.6), 1); w._split_moved(); app.processEvents(); s1 = w.split.sizes()
w2 = sp.Player(); w2.restore_split(); s2 = w2.split.sizes(); w2.close()
chk(s1[0] < s0[0] and s1[1] > s0[1] and w.tv.height() > 0, 'the edge between frame and traces drags (%s -> %s px) and is remembered' % (s0, s1))
w.split.setSizes(s0); w._split_moved()
w.goto(50); w.step(10); chk(w.cur == 60, 'step'); w.wheel(-120); chk(w.cur == 61, 'wheel down = forward'); w.trace_click(w.x[30]); chk(w.cur == 30, 'click on a trace jumps')
# --- size check and reduction
info = sio.probe(os.path.abspath('grey_ffv1.avi'))
p = sio.suggest_reduction(info, sio.estimate_bytes(info, sio.default_reduction(info)) / 7)
chk(sio.estimate_bytes(info, p) <= sio.estimate_bytes(info, sio.default_reduction(info)) / 7, 'suggested reduction fits (%s)' % sio.reduction_text(info, p))
w.load_file(os.path.abspath('grey_ffv1.avi'), reduction=dict(bin=2, step=3, first=5, last=100))
chk(w.N == 32 and (w.H, w.W) == (48, 64) and w.kept[1] == 8 and w.reduced and 'recorded frame 5' in w.title.text(), 'reduced read (bin 2, every 3rd, 5-100)')
chk(abs(w.play_rate() - 20 / 3) < 1e-9, 'every 3rd frame plays at 20/3 frames/s (real time)')
b = sio.bin_frame(truth[7], 2); chk(np.array_equal(w.src.data[1], b), 'binning = 2 x 2 block mean')
# colour stays colour; colour to grey
w.load_file(os.path.abspath('colour_h264.mp4')); chk(w.is_rgb and w.src.data.shape[-1] == 3, 'colour video kept in colour')
w.draw_path('rect', [(51, 31), (66, 41)]); chk(len(w.rois) == 1, 'ROI on colour video')
w.load_file(os.path.abspath('colour_h264.mp4'), reduction=dict(gray=True)); chk(not w.is_rgb, 'colour to grey')
w.load_file(os.path.abspath('grey_mjpeg.avi')); chk(not w.is_rgb, 'grey video stored as RGB (MJPEG) -> grey')
# colour recordings that start black or grey (a fade-in): colour is looked for over the whole recording
for f in ('colour_fadein.mp4', 'colour_fadein.tif'):
    if os.path.exists(f):
        w.load_file(os.path.abspath(f)); w.goto(30); app.processEvents()
        img = w.img1.image
        chk(w.is_rgb and img.ndim == 3 and abs(float(img[..., 0].mean()) - float(img[..., 2].mean())) > 100,
            '%s: black, then grey first frames, colour after: opens in colour' % f)
w.load_file('/nonexistent.avi'); chk(w.loaded, 'missing file: message, the open recording stays')
with open('/tmp/bad.avi', 'wb') as fh: fh.write(b'nonsense' * 100)
n_before, f_before = w.N, w.file
chk(not w.load_file('/tmp/bad.avi') and w.N == n_before and w.file == f_before, 'unreadable file: message, the open recording stays')

# =============================================================================
# recordings read from disk (decoded as shown): frames, traces, dF/F, ROIs, dragging, sound
# =============================================================================
import threading
import sciplayer_source as ss
from make_stream_data import read_code as _rc
def read_code(img, H=None):
    """the frame number written in a frame, also from its (smaller) scrubbing copy"""
    if H is not None and img.shape[0] != H:
        from PIL import Image
        img = np.asarray(Image.fromarray(img).resize((img.shape[1] * H // img.shape[0], H)))
    return _rc(img)
HD = os.path.abspath('hd_h264_gop250_audio.mp4')
mem = ss.open_source(HD, mode='memory')
w.load_file(HD, mode='disk'); app.processEvents()
chk(not w.src.in_memory and w.src.N == 400 and 'from disk' in w.info.text(), 'large video: read from disk (%s)' % w.src.describe())
mb_cache = w.src.cache.nbytes / 1e6
rng = np.random.default_rng(3); bad = 0
for k in list(rng.integers(0, 400, 25)) + list(range(300, 260, -1)) + list(range(0, 30)):
    w.goto(int(k)); bad += read_code(w.img1.image, 1080) != k
    t0 = time.perf_counter()
    while w.preview and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
    bad += read_code(w._shown[0]) != k or w._shown[0].shape[0] != 1080        # (the exact frame behind what is drawn)
chk(bad == 0, 'every frame shown is the right one, at once and then exact: random jumps, steps back, steps forward (GOP 250, B-frames)')
w.cur = 100; w.slider.setSliderDown(True); w.slider.setValue(201); app.processEvents()
shown = w.cur; drag_ok = read_code(w.img1.image, 1080) == shown and shown in (200, int(w.src.keyframe_before(200)))
w.slider.setSliderDown(False); w.slider.sliderReleased.emit(); app.processEvents()
t0 = time.perf_counter()
while w.preview and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
chk(drag_ok and w.cur == 200 and read_code(w._shown[0]) == 200 and w._shown[0].shape[0] == 1080,
    'dragging before the scrubbing copy is ready: frame %d; release: the exact frame' % (shown + 1))
w.draw_path('rect', [(400, 300), (700, 600)])
chk(w.rois[0]['trace'] is None and w.trace_rows[1]['wait'] is not None, 'ROI on a video from disk: its trace is computed in the background')
chk(w.wait_traces(), 'background traces finish')
chk(w.proxy.complete and 'smooth scrubbing ready' in w.info.text(), 'scrubbing copy of every frame (%d x %d, %.0f MB)' % (w.proxy.pw, w.proxy.ph, w.proxy.nbytes / 1e6))
w.slider.setSliderDown(True); bad = 0; ts = []
for v in list(range(120, 160)) + list(np.linspace(0, 399, 60).astype(int)) + list(rng.integers(0, 400, 40)):
    t1 = time.perf_counter(); w.slider.setValue(int(v) + 1); app.processEvents(); ts.append(time.perf_counter() - t1)
    bad += w.cur != v or read_code(w.img1.image, 1080) != v
w.slider.setSliderDown(False)
chk(bad == 0, 'dragging shows every frame, the right one (slow, fast, random; %.1f ms a move)' % (np.median(ts) * 1e3))
k = w.cur; w._slider_released(); t0 = time.perf_counter()
while w.preview and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
chk(not w.preview and w._shown[0].shape[:2] == (1080, 1920) and read_code(w._shown[0]) == k,
    'when the slider rests: the exact full-resolution frame (after %.0f ms)' % ((time.perf_counter() - t0) * 1e3))
w.goto(5); w.trace_click(w.x[333]); t0 = time.perf_counter()
first = read_code(w.img1.image, 1080)
while w.preview and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
chk(first == 333 and read_code(w.img1.image, w.H) == 333 and not w.preview, 'a click on a trace: that frame at once, then exact')
chk(np.allclose(w.mean_trace, mem.mean_trace), 'whole-frame trace from disk = in memory')
chk(np.allclose(w.rois[0]['trace'], sio.roi_trace(mem.data, w.rois[0]['mask'], False)), 'ROI trace from disk = in memory')
w.set_view('relative'); w.set_baseline('1-10'); w.goto(150)
t0 = time.perf_counter()
while w.preview and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
st_ = w._shown[1]                                   # (drawn as S x S block means: compared at that step)
F0_mem = mem.data[:10].astype(np.float64).mean(0)
blk = lambda a: a[:a.shape[0] // st_ * st_, :a.shape[1] // st_ * st_].reshape(a.shape[0] // st_, st_, a.shape[1] // st_, st_).mean((1, 3))
d_mem = (blk(sio.lum(mem.frame(150)).astype(np.float64)) - blk(F0_mem)) / blk(F0_mem) * 100
chk(w.img2.image.shape == d_mem.shape and np.nanmax(np.abs(w.img2.image - d_mem)) < 1e-3 and w.range_str == 'auto',
    'dF/F image from disk = in memory (%d x %d block means)' % (st_, st_))
w.set_view('original'); w.cb_sound.setChecked(False)
chk(w.export_csv('/tmp/tr_disk.csv') and len(open('/tmp/tr_disk.csv').read().splitlines()) == 3 + 400, 'export from disk')
w.goto(0); t0 = time.perf_counter(); w.play(30)
while w.b_play.isChecked() and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.001)
w.cb_sound.setChecked(False)
dt = time.perf_counter() - t0
chk(w.cur == 30 and dt < 3.0, 'plays from disk (1080p: 30 frames in %.2f s at 30 Hz)' % dt)
chk(w.src.cache.nbytes <= w.src.cache.max_bytes, 'frame cache within its limit (%s of %s)' % (sio.size_text(w.src.cache.nbytes / 1e6), sio.size_text(w.src.cache.max_bytes / 1e6)))
# sound, through a stand-in device that consumes samples in real time and keeps them
class FakeSD:
    heard = []
    def query_devices(self, kind=None):
        return {'default_samplerate': 48000, 'max_output_channels': 2}
    class OutputStream:
        latency = 0.0
        def __init__(self, samplerate, channels, dtype, callback, latency=None):
            self.sr, self.ch, self.cb = samplerate, channels, callback; self.run = False
        def start(self):
            self.run = True
            def loop():
                t0 = time.perf_counter(); n = 0
                while self.run:
                    out = np.zeros((480, self.ch), np.int16); self.cb(out, 480, None, None); FakeSD.heard.append(out.copy()); n += 480
                    time.sleep(max(0, t0 + n / self.sr - time.perf_counter()))
            self.th = threading.Thread(target=loop, daemon=True); self.th.start()
        def abort(self):
            self.run = False; self.th.join()
        def close(self): pass
w.audio_backend = FakeSD()
w.cb_sound.setChecked(True)
w.load_file(HD, mode='disk'); app.processEvents()
chk(w.audio.has_audio and w.audio.ok and w.cb_sound.isEnabled() and 'sound: aac' in w.info.text(), 'sound track found (%s)' % w.audio.desc)
w.goto(45)                                       # t = 1.5 s: loud second (the tone alternates 0.1 / 0.3 every second)
FakeSD.heard = []; t0 = time.perf_counter(); w.play(45)
while w.b_play.isChecked() and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
x = np.concatenate(FakeSD.heard)[:, 0].astype(float) / 32767
rms = lambda a: np.sqrt(np.mean(a ** 2)) * np.sqrt(2)
# 0 - 0.5 s heard = video 1.5 - 2.0 s (loud), 0.5 - 1.5 s = video 2 - 3 s (quiet)
a1, a2 = rms(x[2400:21600]), rms(x[28800:67200])
env = np.sqrt(np.convolve(x ** 2, np.ones(480) / 480, 'same') * 2)
edge = (4800 + np.argmax(env[4800:] < 0.2)) / 48000                  # first drop below the middle after 0.1 s
print('      first sound at %.3f s, envelope at 0.25 s %.2f, at 1.0 s %.2f' % (np.argmax(env > 0.05) / 48000, env[12000], env[48000]))
chk(abs(a1 - 0.3) < 0.03 and abs(a2 - 0.1) < 0.02, 'the sound starts at the frame shown (amplitude %.2f then %.2f: 0.3 then 0.1)' % (a1, a2))
chk(abs(edge - 0.5) < 0.03, 'the sound is in step with the picture (loud-to-quiet step at %.3f s, expected 0.500)' % edge)
chk(w.cur in range(88, 92) and not w.audio.playing, 'the picture followed the sound: frame %d after 45 frames' % (w.cur + 1))
class FastSD(FakeSD):
    class OutputStream(FakeSD.OutputStream):
        def __init__(self, samplerate, channels, dtype, callback, latency=None):
            super().__init__(samplerate * 3, channels, dtype, callback)       # takes sound 3 x too fast
w.audio.sd = FastSD(); w.goto(0); t0 = time.perf_counter(); w.play(30)
while w.b_play.isChecked() and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
dt = time.perf_counter() - t0
chk(0.7 < dt < 1.4, 'a sound device with a wrong clock does not rush the picture (30 frames in %.2f s)' % dt)
w.audio.sd = FakeSD()
w.set_fps('15'); chk(not w.cb_sound.isEnabled(), 'another frame rate: no sound (it would not match the picture)')
w.set_fps('30'); chk(w.cb_sound.isEnabled(), 'its own frame rate: sound again')
w.load_file(os.path.abspath('grey_ffv1.avi')); chk(not w.cb_sound.isEnabled() and w.src.in_memory, 'video without sound: sound off; small video: in memory')
# other formats from disk
for f, n in [('hd_h264_gop250_colour.mkv', 300), ('mjpeg_allintra.avi', 200)]:
    w.load_file(os.path.abspath(f), mode='disk'); bad = 0
    for k in list(rng.integers(0, n, 15)) + [n - 1, 0, 1]:
        w.goto(int(k)); t0 = time.perf_counter()
        while w.preview and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
        bad += read_code(w.img1.image if not w.is_rgb else w.img1.image[..., 0], w.H) != k
    chk(bad == 0 and w.N == n and w.wait_traces(), '%s from disk: right frames, traces' % f)
for f in ['stack_u16.tif', 'stack_v73.mat']:
    w.load_file(os.path.abspath(f), mode='disk'); w.wait_traces()
    tr = truth.reshape(120, -1).mean(1)
    chk(not w.src.in_memory and np.corrcoef(w.mean_trace, tr)[0, 1] > 0.9999 and (np.array_equal(w.frame(57), truth[57]) or f.endswith('.tif')),
        '%s from disk: frames and trace' % f)
# --- a large uncompressed AVI (1.2 GB, OpenDML): opens at once; smooth scrubbing is prepared meanwhile, with a strip
RAW = os.path.abspath('raw_bgr_big.avi')
if os.path.exists(RAW):
    t0 = time.perf_counter(); w.load_file(RAW, mode='disk'); app.processEvents(); t_open = time.perf_counter() - t0
    for _ in range(40): app.processEvents(); time.sleep(0.02)
    strip_txt = w.l_strip.text(); strip_vis = w.strip.isVisible(); eta = w.l_eta.text()
    chk(t_open < 3 and strip_vis and strip_txt.startswith('Preparing smooth scrubbing') and read_code(w.img1.image, w.H) == 0,
        'a 1.2 GB uncompressed AVI opens in %.2f s and shows its first frame; the strip says: %s | %s' % (t_open, strip_txt, eta))
    bad = 0
    for k in [300, 17, 419, 205]:
        w.goto(k); t0 = time.perf_counter()
        while w.preview and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
        bad += read_code(w.img1.image, w.H) != k
    chk(bad == 0, 'its frames are right while smooth scrubbing is being prepared')
    w.wait_traces(); app.processEvents()
    chk(w.proxy.complete and w.l_strip.text() == 'Smooth scrubbing ready', 'then: smooth scrubbing ready')
    t0 = time.perf_counter()
    while w.strip.isVisible() and time.perf_counter() - t0 < 6: app.processEvents(); time.sleep(0.02)
    chk(not w.strip.isVisible(), 'and the strip goes away by itself')
    # the default: it fits in memory, so it opens at once from disk and is read into memory meanwhile
    t0 = time.perf_counter(); load_now(RAW); app.processEvents(); t_open = time.perf_counter() - t0
    chk(t_open < 3 and not w.src.in_memory and w.store is not None and w.e_fps.text() == '30' and w.b_play.isEnabled()
        and read_code(w.img1.image, w.H) == 0,
        'by default it opens at once too (%.2f s), from disk, at 30 Hz, Play available, while it is read into memory' % t_open)
    w.goto(0); p0 = w.scan_progress; from_disk = not w.src.in_memory; w.play(); t0 = time.perf_counter(); p_mid = None
    while time.perf_counter() - t0 < 1.5:
        app.processEvents(); time.sleep(0.002)
        if p_mid is None and time.perf_counter() - t0 > 0.75: p_mid = w.scan_progress
    p1 = w.scan_progress
    eta_play = w.l_eta.text()
    w.stop(); el = time.perf_counter() - t0; k = w.cur
    app.processEvents()
    chk(abs(k - 30 * el) <= 6 and read_code(w.img1.image, w.H) == k and from_disk,
        'meanwhile it plays at its own frame rate: %d frames in %.2f s (30 Hz: %.0f)' % (k, el, 30 * el))
    chk(p1 > p_mid > p0 or (w.store is None and w.src.in_memory),
        'and smooth scrubbing goes on being prepared while it plays: %d %% -> %d %% -> %d %% (strip: %s)'
        % (100 * p0, 100 * p_mid, 100 * p1, eta_play))
    w.add_roi('rect', [[200, 150], [500, 400]])
    w.wait_traces(); app.processEvents()
    r = w.rois[-1]
    ok_tr = r['trace'] is not None and np.allclose(r['trace'], sio.roi_trace(w.src.data, r['mask'], False))
    chk(w.src.in_memory and w.store is None and w.src.data.shape == (420, 760, 1250) and ok_tr
        and w.l_strip.text() == 'Smooth scrubbing ready',
        'then it is in memory (%s), and the ROI drawn meanwhile has its trace' % w.src.describe())
    bad = sum(read_code(w.src.frame(k)) != k for k in (0, 1, 210, 419))
    w.goto(333, fast=True); bad += read_code(w.img1.image, w.H) != 333 or w.preview
    chk(bad == 0, 'every frame from memory, exact while dragging')
    w.clear_rois()

# --- a long-GOP video too large to index at once: frames found by time until the real index is read
ss = sp.ss
ss.VideoSource.GUESS_ABOVE, real_index = 0, ss.VideoSource._real_index
ss.VideoSource._real_index = lambda self: None                # (held back, to look at the time before it)
load_now(HD, mode='disk'); app.processEvents()
prov = w.src.provisional
bad = 0
for k in [250, 3, 399, 120, 121, 122, 60]:
    w.goto(k); t0 = time.perf_counter()
    while w.preview and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
    bad += read_code(w.img1.image, w.H) != k
w.goto(100); w.play(20); t0 = time.perf_counter()
while w.timer.isActive() and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
bad += read_code(w.img1.image, w.H) != w.cur
chk(prov and bad == 0, 'long-GOP H.264: opens without reading the file first; frames right, by time, before the index (%d frames)' % w.N)
real_index(w.src); w._index_check()
w.goto(300); t0 = time.perf_counter()
while w.preview and time.perf_counter() - t0 < 10: app.processEvents(); time.sleep(0.002)
chk(not w.src.provisional and len(w.src.keyframes) > 1 and read_code(w.img1.image, w.H) == 300 and w.N == 400,
    'then its index arrives (%d key frames) and the frames stay right' % len(w.src.keyframes))
ss.VideoSource.GUESS_ABOVE, ss.VideoSource._real_index = 150e6, real_index

# --- a 4000 x 3000 camera recording: the dF/F view drags and plays as smoothly as the original
BIG = os.path.abspath('big_mjpeg_4k.avi')
if os.path.exists(BIG):
    from PySide6 import QtGui
    w.load_file(BIG); w.set_view('original'); app.processEvents()
    fr = [w.src.frame(k) for k in range(10, 20)]
    def show_ms():
        t = time.perf_counter()
        for i, f in enumerate(fr):
            w.cur = 10 + i; w.show_frame(f); w.gv.viewport().repaint()
        return (time.perf_counter() - t) / len(fr) * 1e3
    def play_n(sec=2.0):
        w.goto(0); w.play(); t0 = time.perf_counter(); n, last = 0, 0
        while time.perf_counter() - t0 < sec:
            app.processEvents()
            if w.cur != last: n, last = n + 1, w.cur
        w.stop(); return n
    t_orig = show_ms(); n_orig = play_n()
    w.set_view('relative'); app.processEvents()
    w._display_step = lambda: 1; t_full = show_ms(); del w._display_step     # (as 1.3.2 drew it: every pixel)
    t_rel = show_ms(); n_rel = play_n()
    st_rel = w._shown[1]
    chk(t_rel < 0.5 * t_full and n_rel >= 0.85 * 60 and st_rel > 1 and w.img2.image.shape == (3000 // st_rel, 4000 // st_rel),
        'dF/F of a 4000 x 3000 recording: %.0f ms a frame (every pixel: %.0f ms; original %.0f ms), %d frames played in 2 s '
        'at 30 Hz (original %d); drawn at the resolution shown (%d x %d blocks)' % (t_rel, t_full, t_orig, n_rel, n_orig, st_rel, st_rel))
    w.goto(50); app.processEvents()
    d_all = (sio.lum(w.src.frame(50)) - w.F0) / w.F0 * 100
    blk = d_all[1500:1500 + st_rel, 2000:2000 + st_rel]
    f_b = sio.lum(w.src.frame(50))[1500:1500 + st_rel, 2000:2000 + st_rel].mean(); F0_b = w.F0[1500:1500 + st_rel, 2000:2000 + st_rel].mean()
    chk(abs(w.img2.image[1500 // st_rel, 2000 // st_rel] - (f_b - F0_b) / F0_b * 100) < 1e-3,
        'each block shows the relative change of its mean (%.3f %%)' % w.img2.image[1500 // st_rel, 2000 // st_rel])
    # Ctrl + wheel: zoom where the mouse points, through a real wheel event
    def wheel(view_pt, steps, ctrl=True):
        sp_ = w.vb1.mapViewToScene(QtCore.QPointF(*view_pt)); vp = w.gv.mapFromScene(sp_)
        ev = QtGui.QWheelEvent(QtCore.QPointF(vp), QtCore.QPointF(w.gv.viewport().mapToGlobal(vp)), QtCore.QPoint(0, 0),
                               QtCore.QPoint(0, 120 * steps), Qt.NoButton, Qt.ControlModifier if ctrl else Qt.NoModifier,
                               Qt.NoScrollPhase, False)
        QtWidgets.QApplication.sendEvent(w.gv.viewport(), ev); app.processEvents()
    def settle(t=0.25):
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < t: app.processEvents(); time.sleep(0.01)
    pt = (2600.0, 900.0)
    s0 = w.vb1.mapViewToScene(QtCore.QPointF(*pt))
    k0 = w.cur
    for _ in range(6): wheel(pt, 1)
    settle()
    s1 = w.vb1.mapViewToScene(QtCore.QPointF(*pt)); r = w.vb1.viewRect()
    x0, y0, x1, y1 = w._shown[2]
    chk(w.zoomed and r.width() < 1500 and (s1 - s0).manhattanLength() < 2 and w.cur == k0 and w._shown[1] == 1
        and w.vb2.viewRect() == r and w.img2.image.shape == (y1 - y0, x1 - x0)
        and abs(w.img1.mapToView(QtCore.QPointF(0, 0)).x() - (x0 + 0.5)) < 1e-6,
        'Ctrl + wheel zooms in at the mouse (the point stays under it), both panels, every pixel, only the part in view drawn')
    pix = w.img1.image[1000 - y0, 2700 - x0]
    chk(pix == w.src.frame(w.cur)[1000, 2700], 'zoomed: the pixels where they belong (frame pixel (2701, 1001) = %d)' % pix)
    wheel(pt, -1, ctrl=False); settle(0.05)                    # (wheel towards you: the next frame)
    chk(w.cur == k0 + 1 and w.zoomed, 'the wheel alone still steps frames while zoomed')
    t_z = show_ms(); n_z = play_n()
    chk(n_z >= 0.85 * 60, 'zoomed in, dF/F still plays at 30 Hz (%d frames in 2 s, %.0f ms a frame)' % (n_z, t_z))
    w.set_view('original'); settle()
    r2 = w.vb1.viewRect()
    on = all(lo >= 0.5 - 1e-6 and hi <= n + 0.5 + 1e-6 for lo, hi, size, n in
             ((r2.left(), r2.right(), r2.width(), 4000), (r2.top(), r2.bottom(), r2.height(), 3000)) if size < n)
    chk(w.zoomed and on and abs(r2.height() - r.height()) < 2, 'the zoom stays when the view changes, on the frame')
    w.set_view('relative'); settle(); r3 = w.vb1.viewRect()
    on = all(lo >= 0.5 - 1e-6 and hi <= n + 0.5 + 1e-6 for lo, hi, size, n in
             ((r3.left(), r3.right(), r3.width(), 4000), (r3.top(), r3.bottom(), r3.height(), 3000)) if size < n)
    chk(on, 'and back in the relative view (the panels narrower) it is still on the frame')
    w.set_view('original'); settle()
    for _ in range(4): c = w.vb1.viewRect().center(); wheel((c.x(), c.y()), 1)
    settle()
    w.vb1.setRange(w.vb1.viewRect().translated(-5000, 0), padding=0); w._clamp_view(); settle()
    rv = w.vb1.viewRect()
    chk(abs(rv.left() - 0.5) < 1e-6 and w._shown[2][0] == 0, 'moving the view stops at the edge of the frame, and the newly seen part is drawn')
    for _ in range(40):
        c = w.vb1.viewRect().center(); wheel((c.x(), c.y()), -1)
    settle()
    chk(not w.zoomed and w._shown[2] == (0, 0, 4000, 3000), 'Ctrl + wheel back: the whole frame again')
    for _ in range(3): wheel(pt, 1)
    w.zoom_fit(); settle()
    chk(not w.zoomed, 'double-click / Ctrl+0: the whole frame')
    # played from disk while smooth scrubbing is being prepared, from the middle: the frames playback decodes
    # are prepared too (traces, scrubbing copy) and not read again; the background pass reads on meanwhile
    load_now(BIG, mode='disk'); app.processEvents()
    w.goto(60); w.play(); t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.0: app.processEvents(); time.sleep(0.002)
    w.stop(); last = w.cur; t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.0: app.processEvents(); time.sleep(0.01)
    played = [k for k in range(61, last + 1) if k in w.proxy]
    seq = max([k for k in range(0, 60) if k in w.proxy] or [-1])
    chk(len(played) >= 0.6 * (last - 60) and seq >= 0,
        'from disk, smooth scrubbing is prepared while the video plays: %d of the %d frames played are in the '
        'scrubbing copy already, and the pass read on from the start meanwhile (frame %d)' % (len(played), last - 60, seq + 1))
    w.wait_traces(); app.processEvents()
    ref = [ss.fast_mean(w.src.frame(k), False) for k in (0, 30, 61, 70, last, 119)]
    chk(np.allclose(w.mean_trace[[0, 30, 61, 70, last, 119]], ref) and w.proxy.complete and np.isfinite(w.mean_trace).all(),
        'then the trace is complete and right, also for the frames prepared from playback')
    # the same recording played from disk (as a larger one would be), dF/F view: the next frame is decoded
    # and prepared while the window draws the current one
    w.load_file(BIG, mode='disk'); w.wait_traces(); w.set_view('relative'); app.processEvents()
    w.goto(0); w.play(); t0 = time.perf_counter(); n, last, badp = 0, 0, 0
    while time.perf_counter() - t0 < 2.0:
        app.processEvents()
        if w.cur != last:
            n, last = n + 1, w.cur
            badp += read_code(w._shown[0]) != w.cur
    w.stop()
    chk(n >= 0.65 * 60 and badp == 0, 'played from disk in the dF/F view: %d frames in 2 s at 30 Hz (the rest skipped to keep time), every one the right frame' % n)
    w.set_view('original')

# --- brightness and contrast of a colour video; a new recording starts at 0
w.load_file(os.path.abspath('colour_h264.mp4')); w.goto(5); app.processEvents()
c1 = w.img1.image.copy(); w.s_bright.setValue(-30); w.s_contrast.setValue(25); app.processEvents()
chk(w.is_rgb and np.allclose(w.img1.levels, w.raw_levels((0, 255))) and not np.allclose(w.img1.levels, (0, 255))
    and np.array_equal(w.img1.image, c1), 'colour video: display range %.0f..%.0f, the colours themselves unchanged' % tuple(w.img1.levels))
w.load_file(os.path.abspath('grey_ffv1.avi')); app.processEvents()
chk(w.s_bright.value() == 0 and w.s_contrast.value() == 0 and np.allclose(w.img1.levels, w.clim_raw), 'another recording opens at brightness 0, contrast 0')

# --- languages: every text of the window in 简体中文 and 繁體中文, and back
import re, ast, sciplayer_i18n as i18n
src_txt = open(sp.__file__, encoding='utf-8').read() + open(sp.sa.__file__, encoding='utf-8').read()
keys = set()
for m in re.finditer(r"""\btr\(\s*((?:'[^'\\]*(?:\\.[^'\\]*)*'|"[^"\\]*(?:\\.[^"\\]*)*"\s*)+)\)""", src_txt):
    keys.add(ast.literal_eval('(' + m.group(1) + ')'))
missing = sorted(k for k in keys if k not in i18n.T)
chk(not missing, 'every text the program translates has 简体 and 繁體 translations (%d texts)%s' % (len(keys), (': missing ' + repr(missing[:5])) if missing else ''))
reg_missing = sorted(set(t for _, _, t in w._tr_items if t not in i18n.T and t not in ('ROI', 'Hz')))
chk(not reg_missing, 'every label, button and tooltip is translated%s' % ((': missing ' + repr(reg_missing[:5])) if reg_missing else ''))
w.load_file(HD, mode='disk'); w.wait_traces(); w.goto(20)
for code, frame_word in (('zh_CN', '帧'), ('zh_TW', '格')):
    w.set_language(code)
    ok = (w.title.text().startswith('第') and frame_word in w.title.text() and frame_word in w.info.text()
          and w.b_load.text().strip() in ('打开', '開啟') and w.c_view.buttons[1].text().startswith(('相对', '相對')))
    chk(ok, '%s: %s | %s' % (code, w.title.text(), w.info.text().strip()[:60]))
    w.save_view('/tmp/lang_%s.png' % code)
w.set_language('en'); chk(w.title.text().startswith('frame') and w.b_load.text().strip() == 'Open', 'back to English')
w.close()
print('\n%d failure(s)' % nf)
