"""SciPlayer - a video player for scientific recordings: scrub, play, relative change and ROI traces.

Windows edition of the MATLAB sciplayer.m (same window, same behaviour):

  * Load video... (or drop a file on the window, or open it with SciPlayer from
    Explorer) reads a video (anything FFmpeg reads), a multi-page TIFF stack,
    or a MAT-file holding an [H x W x frames] (or [H x W x 3 x frames]) array,
    at full resolution. A recording up to 2 GB (or 30 % of the free memory)
    is read into memory; a larger one stays on disk and each frame is decoded
    when it is shown (sciplayer_source.py), so a 100 MB video stays ~100 MB
    plus a frame cache, and the traces are computed in the background.
  * The sound of a video plays with it (sciplayer_audio.py).
  * The frame fills most of the window; the slider scrubs, the arrows and the
    keyboard step (Shift: 10), the mouse wheel scrolls, Space plays/pauses.
  * View "Relative change" shows (frame - F0) / F0 in % beside the original,
    F0 = mean of the baseline frames you type (1-10, or 1-10, 200-210).
  * One frame rate (Hz), at the top: the time axis, and Play in real time.
  * Traces below: the whole frame's mean, then one row per ROI (rectangle:
    drag corner to corner; freehand: trace the outline, release to close).
  * Export traces (CSV), Save view (PNG).

    sciplayer.py [file]
"""
import os
import sys
import collections
import threading
import time
import traceback

APP_NAME = 'SciPlayer'
APP_VERSION = '1.4.0'
HERE = os.path.dirname(os.path.abspath(__file__))

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
import pyqtgraph as pg

import sciplayer_io as sio
import sciplayer_source as ss
import sciplayer_audio as sa
import sciplayer_theme as theme
import sciplayer_i18n as i18n
from sciplayer_i18n import tr

pg.setConfigOptions(imageAxisOrder='row-major', background='w', foreground='k', antialias=True)

ROI_COLOURS = theme.ROI_COLOURS
CMAP_NAMES = ['blue-white-red', 'jet', 'hot', 'gray', 'viridis']
DRAW_COLOUR = (255, 217, 0)
ACCENT = '#d9541a'


def cmap_lut(name, n=256):
    x = np.linspace(0, 1, n)
    if name == 'jet':
        c = np.stack([np.clip(1.5 - np.abs(4 * x - 3), 0, 1), np.clip(1.5 - np.abs(4 * x - 2), 0, 1),
                      np.clip(1.5 - np.abs(4 * x - 1), 0, 1)], 1)
    elif name == 'hot':
        c = np.stack([np.clip(3 * x, 0, 1), np.clip(3 * x - 1, 0, 1), np.clip(3 * x - 2, 0, 1)], 1)
    elif name == 'gray':
        c = np.stack([x, x, x], 1)
    elif name == 'viridis':
        return pg.colormap.get('viridis')
    else:                                                     # blue - white - red
        h = n // 2
        a = np.linspace(0, 1, h)
        b = np.linspace(0, 1, n - h)[::-1]
        c = np.concatenate([np.stack([a, a, np.ones(h)], 1), np.stack([np.ones(n - h), b, b], 1)])
    return pg.ColorMap(np.linspace(0, 1, n), (c * 255).astype(np.uint8))


def fmt_g(v):
    return '%.4g' % v


def fmt_tick(v):
    """a short axis label: 10723 (not 1.072e+04), 107.2, 9.978, 0.0188"""
    a = abs(v)
    if a >= 1e6 or (0 < a < 1e-3):
        return '%.3g' % v
    if a >= 1000:
        return '%.0f' % v
    if a >= 100:
        return '%.1f' % v
    return '%.4g' % v


# =============================================================================
# view boxes that hand the mouse to the player
# =============================================================================
class ElideLabel(QtWidgets.QLabel):
    """a one-line label that ends in "..." where its text does not fit (the whole text as its tooltip),
    instead of being cut off in the middle of a word"""

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        r = self.contentsRect()
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        p.drawText(r, int(self.alignment()) | int(Qt.TextSingleLine),
                   self.fontMetrics().elidedText(self.text(), Qt.ElideRight, r.width()))
        p.end()


class FrameBox(pg.ViewBox):
    """a frame panel: the mouse draws ROIs, the wheel scrolls frames, Ctrl + wheel zooms at the cursor;
    zoomed in, dragging moves the view and a double-click shows the whole frame again"""

    def __init__(self, player, panel):
        super().__init__(lockAspect=True, invertY=True, enableMouse=False, enableMenu=False, defaultPadding=0)
        self.player = player
        self.panel = panel

    def mouseDragEvent(self, ev, axis=None):
        if not self.player.drawing and self.player.zoomed and ev.button() in (Qt.LeftButton, Qt.MiddleButton):
            ev.accept()                                       # zoomed in: drag the view
            if ev.isStart():
                self.player._pan_rect = self.player.vb1.viewRect()
            r = self.player._pan_rect
            d = self.mapSceneToView(ev.buttonDownScenePos()) - self.mapSceneToView(ev.scenePos())
            if r is not None:
                self.player.vb1.setRange(r.translated(d.x(), d.y()), padding=0)
                self.player._clamp_view()
            return
        if not self.player.drawing or ev.button() != Qt.LeftButton:
            ev.ignore()
            return
        ev.accept()
        p = self.mapSceneToView(ev.scenePos())
        if ev.isStart():
            q = self.mapSceneToView(ev.buttonDownScenePos())
            self.player.draw_step('down', (q.x(), q.y()), self.panel)
        self.player.draw_step('up' if ev.isFinish() else 'move', (p.x(), p.y()), self.panel)

    def mouseClickEvent(self, ev):
        if not self.player.drawing:
            if ev.double() and ev.button() == Qt.LeftButton and self.player.zoomed:
                ev.accept()
                self.player.zoom_fit()
            else:
                ev.ignore()
            return
        ev.accept()
        if ev.button() == Qt.RightButton:
            self.player.draw_end()
        elif ev.button() == Qt.LeftButton:                    # a click is no drag: too small
            p = self.mapSceneToView(ev.scenePos())
            self.player.draw_step('down', (p.x(), p.y()), self.panel)
            self.player.draw_step('up', (p.x(), p.y()), self.panel)

    def wheelEvent(self, ev, axis=None):
        ev.accept()
        if ev.modifiers() & Qt.ControlModifier:
            p = self.mapSceneToView(ev.scenePos())
            self.player.zoom(ev.delta(), (p.x(), p.y()))
        else:
            self.player.wheel(ev.delta())


class TraceBox(pg.ViewBox):
    """a trace row: no pan / zoom; a click jumps to that time, the wheel scrolls frames"""

    def __init__(self, player):
        super().__init__(enableMouse=False, enableMenu=False)
        self.player = player

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            ev.accept()
            self.player.trace_click(self.mapSceneToView(ev.scenePos()).x())
        else:
            ev.ignore()

    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == Qt.LeftButton:
            ev.accept()
            self.player.trace_click(self.mapSceneToView(ev.scenePos()).x())   # dragging scrubs
        else:
            ev.ignore()

    def wheelEvent(self, ev, axis=None):
        ev.accept()
        self.player.wheel(ev.delta())


class GraphView(pg.GraphicsLayoutWidget):
    def __init__(self, player):
        super().__init__()
        self.player = player
        self.setFocusPolicy(Qt.ClickFocus)


# =============================================================================
# traces computed in the background (recordings read from disk)
# =============================================================================
class Scanner(QtCore.QObject):
    """runs sciplayer_source.scan in a thread; results come back to the window through signals"""
    progress = QtCore.Signal(int, float)
    done = QtCore.Signal(int, object)

    def __init__(self):
        super().__init__()
        self.job = 0
        self.thread = None
        self.stop_ev = None
        self.pause_ev = threading.Event()
        self.side = None
        self.paused_s = 0.0                          # time spent paused in this pass
        self._paused_at = None

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, src, masks, want_mean, want_samples, proxy=None, store=None):
        self.cancel()
        self.job += 1
        job = self.job
        self.stop_ev = stop = threading.Event()
        self.pause_ev = pause = threading.Event()
        self.paused_s, self._paused_at = 0.0, None
        self.side = side = ss.SideFrames()             # frames the player decodes meanwhile: prepared, not read again

        def run():
            try:
                res = ss.scan(src, masks, want_mean, want_samples, progress=lambda f: self.progress.emit(job, f), stop=stop,
                              proxy=proxy, store=store, pause=pause, side=side)
            except Exception as e:
                res = e
            self.done.emit(job, res)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return job

    def offer(self, k, f):
        """a frame the player decoded: the pass prepares it without reading it again"""
        if self.side is not None and self.busy:
            self.side.offer(k, f)

    def set_paused(self, on):
        """hold the pass's own reading for a moment (playback is dropping frames: the player first); the
        frames the player decodes are still prepared"""
        if on and not self.pause_ev.is_set():
            self.pause_ev.set()
            self._paused_at = time.perf_counter()
        elif not on and self.pause_ev.is_set():
            self.pause_ev.clear()
            if self._paused_at is not None:
                self.paused_s += time.perf_counter() - self._paused_at
            self._paused_at = None

    @property
    def paused(self):
        return self.pause_ev.is_set() and self.busy

    def paused_time(self):
        return self.paused_s + (time.perf_counter() - self._paused_at if self._paused_at is not None else 0.0)

    def cancel(self):
        if self.stop_ev is not None:
            self.stop_ev.set()
        self.set_paused(False)
        if self.thread is not None:
            self.thread.join(timeout=5)
        self.thread = None
        self.job += 1


class ResetSlider(QtWidgets.QSlider):
    """a slider from -100 to 100 that goes back to 0 on a double-click"""
    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setRange(-100, 100)
        self.setValue(0)
        self.setFocusPolicy(Qt.NoFocus)                  # (the arrow keys step through frames)

    def mouseDoubleClickEvent(self, ev):
        self.setValue(0)
        ev.accept()


class Segmented(QtWidgets.QFrame):
    """a flat segmented switch (like a combo box: currentIndex, setCurrentIndex, currentIndexChanged)"""
    currentIndexChanged = QtCore.Signal(int)

    def __init__(self, labels):
        super().__init__()
        self.setObjectName('segment')
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.group = QtWidgets.QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for i, t in enumerate(labels):
            b = QtWidgets.QToolButton()
            b.setText(t)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self._clicked)
        self._i = 0

    def set_labels(self, labels):
        for b, t in zip(self.buttons, labels):
            b.setText(t)

    def _clicked(self, i):
        if i != self._i:
            self._i = i
            self.currentIndexChanged.emit(i)

    def currentIndex(self):
        return self._i

    def setCurrentIndex(self, i):
        self._i = i
        self.buttons[i].setChecked(True)
        if not self.signalsBlocked():
            self.currentIndexChanged.emit(i)


class Refiner(QtCore.QObject):
    """decodes the exact frame in a thread while the window shows its scrubbing copy: the slider and
    the keys never wait for the decoder. Only the latest request counts."""
    ready = QtCore.Signal(int, int, object)          # generation, frame, array (or an exception)

    def __init__(self):
        super().__init__()
        self.cv = threading.Condition()
        self.want = None                             # (generation, src, k)
        self.gen = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def request(self, src, k):
        with self.cv:
            self.gen += 1
            self.want = (self.gen, src, k)
            self.cv.notify()

    def cancel(self):
        with self.cv:
            self.gen += 1
            self.want = None

    busy = False

    def _run(self):
        while True:
            with self.cv:
                while self.want is None:
                    self.cv.wait()
                gen, src, k = self.want
                self.want = None
                self.busy = True
            try:
                f = src.frame(k)
            except Exception as e:
                f = e
            self.busy = False
            self.ready.emit(gen, k, f)


class Ahead:
    """While the video plays, a small pipeline runs ahead of the playback clock. One thread reads (decodes)
    the coming frames in order, skipping ahead when it cannot keep the pace. A second thread makes each one
    ready to draw (S x S block means of the part in view). The window only draws the newest ready frame that
    is due, so decoding, preparing and drawing overlap, as in a video player. It never shows a frame other
    than the exact one for its time."""

    DEPTH = 3                                        # frames read or ready ahead

    def __init__(self):
        self.cv = threading.Condition()
        self.gen = 0
        self.plan = None                             # (key, get(k) -> frame, drawable(f) -> g, due(dt) -> k, N)
        self.next_k = 0
        self.read_q = collections.deque()            # (gen, k, frame) read, not yet ready to draw
        self.ready = {}                              # k -> (frame, drawable)
        self.read_s, self.draw_s = 0.03, 0.01        # time to read / prepare one (running means)
        for fn in (self._reader, self._drawer):
            threading.Thread(target=fn, daemon=True).start()

    @property
    def key(self):
        p = self.plan
        return p[0] if p is not None else None

    def start(self, key, get, drawable, due, k_from, N):
        with self.cv:
            self.gen += 1
            self.plan = (key, get, drawable, due, N)
            self.next_k = k_from
            self.read_q.clear()
            self.ready = {}
            self.cv.notify_all()

    def stop(self):
        with self.cv:
            self.gen += 1
            self.plan = None
            self.read_q.clear()
            self.ready = {}
            self.cv.notify_all()

    def take(self, due_k, cur):
        """(k, frame, drawable) of the newest ready frame after CUR that is due by DUE_K; else None"""
        with self.cv:
            ks = [k for k in self.ready if cur < k <= due_k]
            if not ks:
                return None
            k = max(ks)
            f, g = self.ready[k]
            for j in [j for j in self.ready if j <= k]:
                del self.ready[j]
            self.cv.notify_all()
            return k, f, g

    def pending(self, cur):
        """frames after CUR are being read or prepared (or wait, ready but not yet due)"""
        with self.cv:
            return self.plan is not None and (self.next_k < self.plan[4] or bool(self.read_q) or
                                              any(k > cur for k in self.ready))

    def _reader(self):
        while True:
            with self.cv:
                while self.plan is None or len(self.read_q) + len(self.ready) >= self.DEPTH or \
                        self.next_k >= self.plan[4]:
                    self.cv.wait(0.1)
                gen, (key, get, drawable, due, N) = self.gen, self.plan
                k = self.next_k
            try:                                     # the frame due when this one could be shown
                k = min(N - 1, max(k, due(self.read_s + self.draw_s)))
            except Exception:
                pass
            t0 = time.perf_counter()
            try:
                f = get(k)
            except Exception:
                f = None
            self.read_s = 0.7 * self.read_s + 0.3 * (time.perf_counter() - t0)
            with self.cv:
                if gen == self.gen:
                    self.next_k = k + 1
                    if f is not None:
                        self.read_q.append((gen, k, f))
                    self.cv.notify_all()

    def _drawer(self):
        while True:
            with self.cv:
                while not self.read_q:
                    self.cv.wait(0.1)
                gen, k, f = self.read_q.popleft()
                plan = self.plan if gen == self.gen else None
            if plan is None:
                continue
            t0 = time.perf_counter()
            try:
                g = plan[2](f)
            except Exception:
                g = None
            self.draw_s = 0.7 * self.draw_s + 0.3 * (time.perf_counter() - t0)
            with self.cv:
                if gen == self.gen and g is not None:
                    self.ready[k] = (f, g)
                self.cv.notify_all()


# =============================================================================
# the player
# =============================================================================
class Player(QtWidgets.QMainWindow):
    def __init__(self, mem_limit_gb=2.0):
        super().__init__()
        self.mem_limit_gb = mem_limit_gb
        self.src = None
        self.audio = None
        self.samples = None
        self.mean_trace = None
        self.scan_progress = 0.0
        self.scanner = Scanner()
        self.scanner.progress.connect(self._scan_progress)
        self.scanner.done.connect(self._scan_done)
        self.proxy = None
        self.store = None                            # the recording being read into memory in the background
        self.F0p = self.F0okp = None
        self.preview = False                         # the frame shown is the scrubbing copy
        self._pre = None                             # (k, frame, drawable, key) from the playback pipeline
        self._drops = collections.deque()            # (time, frames dropped) while playing
        self._backoff_until = 0.0
        self.zoomed = False                          # Ctrl + wheel: a part of the frame fills the panel
        self._zoom_rect = None
        self._pan_rect = None
        self._shown = None                           # (full-size frame, step) drawn last
        self._F0s = {}                               # F0 at the resolution frames are drawn at
        self.refiner = Refiner()
        self.refiner.ready.connect(self._refined)
        self.ahead = Ahead()
        self.settle = QtCore.QTimer(self)            # the slider rests: the exact frame
        self.settle.setSingleShot(True)
        self.settle.setInterval(90)
        self.settle.timeout.connect(self._refine_now)
        self.loaded = False
        self.cur = 0                      # 0-based internally; shown 1-based
        self.N = 0
        self.view = 'original'
        self.rois = []
        self.roi_count = 0
        self.base = []
        self.base_str = '1-10'
        self.range_str = 'auto'
        self.cmap = 'blue-white-red'
        self.clim_dff = (-1.0, 1.0)
        self._raw_base = None                            # display range of the original before brightness / contrast
        self.F0 = None
        self.fps = float('nan')
        self.drawing = None
        self.trace_rows = []
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self._build()
        self._enable(False)
        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ window
    def _build(self):
        c = QtWidgets.QWidget()
        c.setObjectName('central')
        self.setCentralWidget(c)
        v = QtWidgets.QVBoxLayout(c)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(8)
        self._icons = []                                  # (widget, icon name, on-colour?, off name) to recolour
        self._tr_items = []                               # (widget, setter, English text): the language can change
        self._tr_funcs = []

        def tool(name, slot=None, tip=None, text=None, checkable=False, off_name=None):
            b = QtWidgets.QToolButton()
            b.setObjectName('icon' if text is None else 'tool')
            if text:
                self._t(b, 'setText', text)
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setIconSize(QtCore.QSize(18, 18))
            b.setCheckable(checkable)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            if slot is not None:
                b.clicked.connect(slot)
            if tip:
                self._t(b, 'setToolTip', tip)
            self._icons.append((b, name, checkable, off_name))
            return b

        def muted(text, cls=QtWidgets.QLabel):
            l = cls()
            l.setObjectName('muted')
            self._t(l, 'setText', text)
            return l

        # ---- top bar: open, the recording, frame rate, export, look -------------------------
        r1 = QtWidgets.QHBoxLayout()
        r1.setSpacing(8)
        self.logo = QtWidgets.QLabel()
        ic = icon_path(png=True)
        if ic:
            self.logo.setPixmap(QtGui.QIcon(ic).pixmap(26, 26))
        self.b_load = QtWidgets.QPushButton()
        self._tr_funcs.append(lambda: self.b_load.setText('  ' + tr('Open')))
        self.b_load.setObjectName('primary')
        self.b_load.setCursor(Qt.PointingHandCursor)
        self.b_load.setFocusPolicy(Qt.NoFocus)
        self._t(self.b_load, 'setToolTip', 'open a video (any format FFmpeg reads), a multi-page TIFF or a MAT-file with an '
                '[H x W x frames] array (Ctrl+O; or drop a file on the window)')
        self.b_load.clicked.connect(lambda: self.load_file(''))
        self.l_name = QtWidgets.QLabel(APP_NAME)
        self.l_name.setObjectName('name')
        self.info = muted('Open a recording, or drop a file here', ElideLabel)
        self.info.setContentsMargins(0, 0, 16, 0)               # (a gap before what follows)
        self.info.setMinimumWidth(60)
        self.info.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.e_fps = QtWidgets.QLineEdit()
        self.e_fps.setFixedWidth(58)
        self.e_fps.setAlignment(Qt.AlignRight)
        self._t(self.e_fps, 'setToolTip', "the recording's frame rate: sets the time axis and the playback speed (Play runs in real time); "
                "empty = frame numbers, playback at 10 frames/s (the video's own rate is filled in when it has one)")
        self.e_fps.editingFinished.connect(lambda: self.set_fps(self.e_fps.text()))
        self.b_export = tool('export', lambda: self.export_csv(''), 'export all traces as a CSV file', 'Export CSV')
        self.b_save = tool('save', lambda: self.save_view(''), 'save the window as a PNG image', 'Save PNG')
        self.b_theme = tool('moon', self.toggle_theme, 'dark / light')
        self.b_help = tool('help', self._show_help, 'keyboard and mouse')
        self.b_lang = tool('globe', None, 'Language')
        self.b_lang.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.m_lang = QtWidgets.QMenu(self.b_lang)
        self.g_lang = QtGui.QActionGroup(self.m_lang)
        for code, label in i18n.LANGS:
            a = self.m_lang.addAction(label)
            a.setCheckable(True)
            a.setData(code)
            self.g_lang.addAction(a)
        self.g_lang.triggered.connect(lambda a: self.set_language(a.data()))
        self.b_lang.setMenu(self.m_lang)
        self.b_lang.setStyleSheet('QToolButton::menu-indicator { image: none; width: 0px; }')
        r1.addWidget(self.logo)
        r1.addWidget(self.b_load)
        r1.addSpacing(6)
        r1.addWidget(self.l_name)
        r1.addWidget(self.info, 1)
        r1.addWidget(muted('Frame rate'))
        r1.addWidget(self.e_fps)
        r1.addWidget(muted('Hz'))
        r1.addSpacing(10)
        for b in (self.b_export, self.b_save, self.b_lang, self.b_theme, self.b_help):
            r1.addWidget(b)
        v.addLayout(r1)

        # ---- tool bar: view, baseline, ROIs --------------------------------------------------
        r2 = QtWidgets.QHBoxLayout()
        r2.setSpacing(8)
        self.c_view = Segmented(['Original', 'Relative change  dF/F'])
        self._tr_funcs.append(lambda: self.c_view.set_labels([tr('Original'), tr('Relative change  dF/F')]))
        self._t(self.c_view, 'setToolTip', 'Relative change: (frame - F0) / F0 beside the original frame')
        self.c_view.currentIndexChanged.connect(lambda i: self.set_view('relative' if i == 1 else 'original'))
        self.e_base = QtWidgets.QLineEdit('1-10')
        self.e_base.setFixedWidth(110)
        self._t(self.e_base, 'setToolTip', 'frames of the player (1..N) whose mean is F0, e.g. 1-10  or  1-10, 200-210')
        self.e_base.editingFinished.connect(lambda: self.set_baseline(self.e_base.text()))
        self.b_rect = tool('rect', lambda: self.draw_start('rect'),
                           'ROI: press the left button on the frame, drag to the opposite corner, release (Esc: cancel)', 'Rectangle')
        self.b_free = tool('free', lambda: self.draw_start('freehand'),
                           'ROI: press the left button on the frame, trace the outline, release to close it (Esc: cancel)', 'Freehand')
        self.b_del = tool('remove', lambda: self.remove_roi(None), 'remove ROIs', 'Remove')
        r2.addWidget(self.c_view)
        r2.addSpacing(10)
        r2.addWidget(muted('Baseline'))
        r2.addWidget(self.e_base)
        r2.addStretch(1)
        # brightness and contrast of the original frame: how it is drawn only (the display range),
        # never its values, so dF/F, traces and exports stay as they are
        self.s_bright, self.s_contrast = ResetSlider(), ResetSlider()
        self._t(self.s_bright, 'setToolTip', 'brightness of the original frame, for display only: values, dF/F, traces and exports '
                'do not change (double-click: back to 0)')
        self._t(self.s_contrast, 'setToolTip', 'contrast of the original frame, for display only: values, dF/F, traces and exports '
                'do not change (double-click: back to 0)')
        self.l_bright, self.l_contrast = muted('Brightness'), muted('Contrast')
        self.b_look_reset = QtWidgets.QToolButton()
        self.b_look_reset.setObjectName('tool')
        self.b_look_reset.setFocusPolicy(Qt.NoFocus)
        self.b_look_reset.setCursor(Qt.PointingHandCursor)
        self._t(self.b_look_reset, 'setText', 'Reset')
        self._t(self.b_look_reset, 'setToolTip', 'brightness and contrast back to normal')
        self.b_look_reset.clicked.connect(self.reset_look)
        for l, s in ((self.l_bright, self.s_bright), (self.l_contrast, self.s_contrast)):
            s.setFixedWidth(96)
            s.valueChanged.connect(self._look_changed)
            r2.addWidget(l)
            r2.addWidget(s)
        r2.addWidget(self.b_look_reset)
        r2.addSpacing(14)
        r2.addWidget(muted('ROI'))
        for b in (self.b_rect, self.b_free, self.b_del):
            r2.addWidget(b)
        v.addLayout(r2)

        # ---- smooth scrubbing being prepared: the video is open already; this says how long until
        #      dragging is smooth everywhere (hidden when there is nothing to prepare) -----------------
        self.strip = QtWidgets.QFrame()
        self.strip.setObjectName('strip')
        sl = QtWidgets.QHBoxLayout(self.strip)
        sl.setContentsMargins(10, 5, 10, 5)
        sl.setSpacing(10)
        self.l_strip = QtWidgets.QLabel()
        self.l_strip.setObjectName('strip')
        self.p_strip = QtWidgets.QProgressBar()
        self.p_strip.setObjectName('strip')
        self.p_strip.setRange(0, 1000)
        self.p_strip.setTextVisible(False)
        self.p_strip.setFixedHeight(6)
        self.l_eta = QtWidgets.QLabel()
        self.l_eta.setObjectName('muted')
        sl.addWidget(self.l_strip)
        sl.addWidget(self.p_strip, 1)
        sl.addWidget(self.l_eta)
        self.strip.hide()
        self.strip_timer = QtCore.QTimer(self)
        self.strip_timer.setSingleShot(True)
        self.strip_timer.timeout.connect(self.strip.hide)
        v.addWidget(self.strip)

        # ---- the frame (one panel, or original | relative change) ----------------------------------
        self.title = QtWidgets.QLabel(APP_NAME)
        self.title.setObjectName('title')
        self.title.setAlignment(Qt.AlignCenter)
        top = QtWidgets.QWidget()
        tl = QtWidgets.QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(4)
        tl.addWidget(self.title)
        self.gv = GraphView(self)
        self.gv.ci.layout.setContentsMargins(6, 6, 6, 6)
        self.gv.ci.layout.setHorizontalSpacing(14)
        self.vb1 = FrameBox(self, 1)
        self.vb2 = FrameBox(self, 2)
        self.img1 = pg.ImageItem()
        self.img2 = pg.ImageItem()
        self.vb1.addItem(self.img1)
        self.vb2.addItem(self.img2)
        # the dF/F panel shows what the original shows (zoom, position). One way only: two aspect-locked views
        # linked both ways push each other wider while the layout changes
        self.vb1.sigRangeChanged.connect(lambda *a: self.vb2.setRange(self.vb1.viewRect(), padding=0))
        self.redraw = QtCore.QTimer(self)                 # zoomed or resized: drawn again at the new resolution
        self.redraw.setSingleShot(True)
        self.redraw.setInterval(60)
        self.redraw.timeout.connect(self._redraw_if_needed)
        self.vb1.sigRangeChanged.connect(lambda *a: self.redraw.isActive() or self.redraw.start())
        self.vb1.sigResized.connect(lambda *a: self.redraw.isActive() or self.redraw.start())
        self.hint = pg.TextItem('', anchor=(0.5, 0.5))
        self._tr_funcs.append(self._hint_text)
        f = QtGui.QFont()
        f.setPointSize(13)
        self.hint.setFont(f)
        self.vb1.addItem(self.hint)
        self.vb1.setRange(xRange=(0, 1), yRange=(0, 1), padding=0)
        self.hint.setPos(0.5, 0.5)
        self.cbar = pg.ColorBarItem(values=(-1, 1), colorMap=cmap_lut(self.cmap), interactive=False, width=12)
        self.cbar.axis.setLabel('dF/F (%)')
        self.cbar.setImageItem(self.img2)
        self.gv.addItem(self.vb1, row=0, col=0)
        self.gv.setMinimumHeight(120)
        tl.addWidget(self.gv, 1)
        # the frame above, transport + traces below, with a draggable edge between them
        self.split = QtWidgets.QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(10)
        self.split.addWidget(top)
        lower = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(lower)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)

        # ---- transport: step, play, step, slider, frame, loop, sound; dF/F display ----------------
        r3 = QtWidgets.QHBoxLayout()
        r3.setSpacing(6)
        self.b_prev = tool('prev', lambda: self.step(-1), 'previous frame (left arrow; Shift: 10 frames)')
        self.b_next = tool('next', lambda: self.step(1), 'next frame (right arrow; Shift: 10 frames)')
        self.b_play = QtWidgets.QPushButton()
        self.b_play.setObjectName('play')
        self.b_play.setCheckable(True)
        self.b_play.setFocusPolicy(Qt.NoFocus)
        self.b_play.setCursor(Qt.PointingHandCursor)
        self.b_play.setIconSize(QtCore.QSize(20, 20))
        self._t(self.b_play, 'setToolTip', 'play / pause (Space), in real time at the frame rate')
        self.b_play.toggled.connect(self._play_toggled)
        self.slider = QtWidgets.QSlider(Qt.Horizontal)
        self.slider.setMinimum(1)
        self.slider.setMaximum(1)
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.slider.valueChanged.connect(lambda val: self.goto(val - 1, fast=self.slider.isSliderDown()))
        self.slider.sliderReleased.connect(self._slider_released)
        self.e_frame = QtWidgets.QLineEdit()
        self.e_frame.setFixedWidth(64)
        self.e_frame.setAlignment(Qt.AlignRight)
        self._t(self.e_frame, 'setToolTip', 'type a frame number')
        self.e_frame.editingFinished.connect(self._frame_typed)
        self.l_count = QtWidgets.QLabel('/ 0')
        self.l_count.setObjectName('muted')
        self.cb_loop = tool('loop', None, 'loop: start again at the end', checkable=True)
        self.cb_loop.setChecked(True)
        self.cb_sound = tool('sound', None, 'play the sound of the video (at its own frame rate)', checkable=True, off_name='mute')
        self.cb_sound.setChecked(True)
        self.cb_sound.toggled.connect(self._sound_toggled)
        self.l_range = muted('dF/F range %')
        self.e_range = QtWidgets.QLineEdit('auto')
        self.e_range.setFixedWidth(64)
        self._t(self.e_range, 'setToolTip', 'colour range of the relative change: auto, one number (symmetric), or two numbers (low high)')
        self.e_range.editingFinished.connect(lambda: self.set_range(self.e_range.text()))
        self.l_cmap = muted('Colour map')
        self.c_cmap = QtWidgets.QComboBox()
        self.c_cmap.addItems(CMAP_NAMES)
        self._t(self.c_cmap, 'setToolTip', 'colour map of the relative change')
        self.c_cmap.setFocusPolicy(Qt.NoFocus)
        self.c_cmap.currentTextChanged.connect(self.set_cmap)
        r3.addWidget(self.b_prev)
        r3.addWidget(self.b_play)
        r3.addWidget(self.b_next)
        r3.addSpacing(6)
        r3.addWidget(self.slider, 1)
        r3.addSpacing(6)
        r3.addWidget(self.e_frame)
        r3.addWidget(self.l_count)
        r3.addSpacing(4)
        r3.addWidget(self.cb_loop)
        r3.addWidget(self.cb_sound)
        r3.addSpacing(10)
        r3.addWidget(self.l_range)
        r3.addWidget(self.e_range)
        r3.addSpacing(4)
        r3.addWidget(self.l_cmap)
        r3.addWidget(self.c_cmap)
        lv.addLayout(r3)

        # ---- traces -----------------------------------------------------------------------------
        self.tv = GraphView(self)
        self.tv.ci.layout.setContentsMargins(0, 4, 8, 0)
        self.tv.ci.layout.setVerticalSpacing(6)
        self.tv.setMinimumHeight(70)
        lv.addWidget(self.tv, 1)
        self.split.addWidget(lower)
        self.split.setStretchFactor(0, 5)
        self.split.setStretchFactor(1, 2)
        self._t(self.split.handle(1), 'setToolTip', 'drag up or down: frame / traces')
        self.split.handle(1).setCursor(Qt.SplitVCursor)
        self.split.splitterMoved.connect(self._split_moved)
        v.addWidget(self.split, 1)

        # ---- keyboard ----------------------------------------------------------------------------
        def sc(key, slot):
            s = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            s.setContext(Qt.WindowShortcut)
            s.activated.connect(slot)
        sc('Right', lambda: self.step(1))
        sc('Left', lambda: self.step(-1))
        sc('Shift+Right', lambda: self.step(10))
        sc('Shift+Left', lambda: self.step(-10))
        sc('Home', lambda: self.goto(0))
        sc('End', lambda: self.goto(self.N - 1))
        sc('Space', lambda: self.b_play.toggle() if self.loaded else None)
        sc('Esc', self.draw_end)
        sc('Ctrl+O', lambda: self.load_file(''))
        sc('Ctrl+0', self.zoom_fit)
        # after typing in a box (Enter, or clicking elsewhere) the keys go back to the frame:
        # arrows step, Space plays (a text box would keep them for its cursor)
        for e in (self.e_fps, self.e_base, self.e_frame, self.e_range):
            e.returnPressed.connect(self._focus_frame)
        lang = os.environ.get('SCIPLAYER_LANG') or ('en' if os.environ.get('SCIPLAYER_TEST') else
                                                    (self._settings().value('language', '') or i18n.system_language()))
        self.set_language(lang, save=False)
        self.apply_theme(self._settings().value('theme', '') or theme.system_theme(), save=False)

    def _hint_text(self):
        """the start screen: what to do, and in Chinese the name with its nickname above it"""
        if self.hint is None:
            return
        nick = i18n.nickname()
        if not nick:
            self.hint.setText(tr('Open a recording, or drop a file here'))
            return
        self.hint.setHtml('<div style="text-align:center"><span style="font-size:22pt; font-weight:600">%s · %s</span>'
                          '<br><br>%s</div>' % (APP_NAME, nick, tr('Open a recording, or drop a file here')))

    def _show_help(self):
        QtWidgets.QToolTip.showText(self.b_help.mapToGlobal(QtCore.QPoint(0, self.b_help.height())), tr(i18n.HELP_EN), self.b_help)

    # ------------------------------------------------------------------ language
    def _t(self, w, setter, text):
        """a text of the window, in the current language (and again whenever the language changes)"""
        self._tr_items.append((w, setter, text))
        getattr(w, setter)(tr(text))
        return w

    def set_language(self, code, save=True):
        """English, 简体中文 or 繁體中文: every text of the window"""
        code = i18n.set_language(code)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            f = app.font()
            f.setFamilies(i18n.fonts())
            app.setFont(f)
            self.setFont(f)
        for a in self.g_lang.actions():
            a.setChecked(a.data() == code)
        for w, setter, text in self._tr_items:
            getattr(w, setter)(tr(text))
        for fn in self._tr_funcs:
            fn()
        if self.loaded:
            self._info_text()
            self._sound_state()
            if self.strip.isVisible():
                self._strip_update()                             # (its text, in the new language)
            self._traces()
            self.show_frame()
        else:
            self.info.setText(tr('Open a recording, or drop a file here'))
        if save:
            try:
                self._settings().setValue('language', code)
            except Exception:
                pass

    # ------------------------------------------------------------------ look
    def apply_theme(self, name, save=True):
        """flat dark or light look: the style sheet, the icons, and the plots' colours"""
        name = name if name in theme.THEMES else 'dark'
        self.theme_name = name
        t = self.th = theme.THEMES[name]
        self.setStyleSheet(theme.style_sheet(t))
        for b, nm, on, off in self._icons:
            b.setIcon(theme.icon(nm, t['muted'] if on else t['text'], t['accent'] if on else None, off))
        self.b_theme.setIcon(theme.icon('sun' if name == 'dark' else 'moon', t['text']))
        self.b_load.setIcon(theme.icon('open', '#ffffff'))
        self._play_icon()
        self.gv.setBackground(t['canvas'])
        self.tv.setBackground(t['plot'])
        if self.hint is not None:
            self.hint.setColor(t['hint'])
        ax = self.cbar.axis
        ax.setPen(pg.mkPen(t['axis']))
        ax.setTextPen(pg.mkPen(t['muted']))
        ax.setLabel('dF/F (%)', color=t['muted'])
        if self.drawing is not None:
            self.title.setStyleSheet('color: %s' % t['warn'])
        if self.loaded:
            self._traces()
        if save:
            try:
                self._settings().setValue('theme', name)
            except Exception:
                pass

    def toggle_theme(self):
        self.apply_theme('light' if self.theme_name == 'dark' else 'dark')

    def _play_icon(self):
        if hasattr(self, 'th'):
            self.b_play.setIcon(theme.icon('pause' if self.b_play.isChecked() else 'play', '#ffffff'))

    def _split_moved(self, pos=None, index=None):
        """the edge between the frame and the traces: remembered for the next start"""
        try:
            self._settings().setValue('split_sizes', [int(x) for x in self.split.sizes()])
        except Exception:
            pass

    def restore_split(self):
        try:
            v = self._settings().value('split_sizes')
            if v and len(v) == 2 and all(int(x) > 0 for x in v):
                self.split.setSizes([int(x) for x in v])
        except Exception:
            pass

    def _focus_frame(self):
        self.gv.setFocus(Qt.OtherFocusReason)

    def _enable(self, on):
        for w in (self.b_export, self.b_save, self.c_view, self.e_base, self.b_rect, self.b_free, self.b_del,
                  self.b_prev, self.b_next, self.slider, self.e_frame, self.b_play, self.cb_loop, self.e_fps,
                  self.l_range, self.e_range, self.l_cmap, self.c_cmap, self.cb_sound,
                  self.l_bright, self.s_bright, self.l_contrast, self.s_contrast):
            w.setEnabled(on)
        self.b_look_reset.setEnabled(on and self._look_changed_from_normal())
        if on:
            self._sound_state()
            rel = self.view == 'relative'
            for w in (self.l_range, self.e_range, self.l_cmap, self.c_cmap):
                w.setEnabled(rel)

    # ------------------------------------------------------------------ messages
    def msg(self, text, title=APP_NAME):
        if os.environ.get('SCIPLAYER_TEST'):
            print('[sciplayer] ' + text.replace('\n', ' '))
            return
        QtWidgets.QMessageBox.warning(self, title, text)

    # ------------------------------------------------------------------ loading
    def load_file(self, path, var=None, reduction=None, mode='auto'):
        """open PATH ('' = ask). VAR: the MAT-file array. Scripted use: REDUCTION (binning, every n-th
        frame, range, grey: read into memory), MODE 'memory' / 'disk' (default: by size)"""
        self.draw_end()
        if not path:
            exts = ' '.join('*' + e for e in sio.ALL_EXT)
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, tr('SciPlayer: choose a recording'), self._last_dir(),
                                                            tr('Videos, TIFF stacks, MAT-files (%s);;All files (*.*)') % exts)
            if not path:
                return False
        if not os.path.isfile(path):
            self.msg(tr('File not found:\n%s') % path)
            return False
        self.stop()
        if path.lower().endswith('.mat') and var is None:
            try:
                arrs = sio.mat_arrays(path)
            except Exception as e:
                self.msg(tr('Could not open %s:\n%s') % (path, e))
                return False
            if len(arrs) > 1 and os.environ.get('SCIPLAYER_TEST'):
                var = arrs[0][0]                                   # scripted: the largest
            elif len(arrs) > 1:
                items = ['%s   [%s]   %s' % (a[0], ' x '.join(map(str, a[1])), a[2]) for a in arrs]
                it, ok = QtWidgets.QInputDialog.getItem(self, APP_NAME, tr('Which array holds the frames?'), items, 0, False)
                if not ok:
                    return False
                var = arrs[items.index(it)][0]
        # open at once from disk (videos, TIFF stacks, v7.3 MAT-files); the rest is read into memory first,
        # with a progress bar (v5 MAT-files, single-array TIFFs, reductions)
        prog = QtWidgets.QProgressDialog(tr('Reading %s ...') % os.path.basename(path), tr('Cancel'), 0, 1000, self)
        prog.setWindowTitle(APP_NAME)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(400)
        prog.setAutoReset(False)
        self.info.setText(tr('Opening %s ...') % os.path.basename(path))
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)

        def progress(fr):
            prog.setValue(int(fr * 1000))
            QtWidgets.QApplication.processEvents()
            return prog.wasCanceled()
        try:
            src = ss.open_source(path, var, mode=mode, mem_limit=ss.default_memory_limit(self.mem_limit_gb),
                                 reduction=reduction, progress=progress)
        except MemoryError:
            src = MemoryError
        except Exception as e:
            src = e
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            prog.close()
        if src is MemoryError or isinstance(src, Exception) or src is None:
            if src is MemoryError:
                self.msg(tr('Not enough memory to read %s.') % os.path.basename(path))
            elif src is not None:
                self.msg(tr('Could not open %s:\n%s') % (path, src))
            self._info_text()
            return False
        # the new recording replaces the old one
        self.scanner.cancel()
        self._audio_stop()
        self.clear_rois()
        if self.src is not None:
            self.src.close()
        self.src = src
        self.N, self.H, self.W, self.is_rgb = src.N, src.H, src.W, src.is_rgb
        self.kept = src.kept
        self.file, self.finfo = path, src.info
        self.fps = src.fps
        self.reduced = src.reduced
        self.mean_trace = src.mean_trace
        self.samples = None
        self.scan_progress = 0.0
        self.refiner.cancel()
        self.ahead.stop()
        self.proxy = None
        self.store = None
        self.preview = False
        # smooth scrubbing, prepared in the background while the video already plays from disk: the whole
        # recording read into memory when it fits, otherwise the scrubbing copy (videos)
        if getattr(src, 'fits_memory', False):
            try:
                self.store = ss.MemoryStore(src.N, src.H, src.W, src.cs, src.dtype)
            except (MemoryError, ValueError):
                self.store = None
        if self.store is None and isinstance(src, ss.VideoSource) and src.dtype == np.uint8:
            try:
                self.proxy = ss.ProxyStore(src.W, src.H, src.N, src.cs)
            except Exception:
                self.proxy = None
        self.loaded = True
        self.zoomed, self._zoom_rect, self._shown = False, None, None
        self.cur = 0
        self.base_str = '1-%d' % min(10, self.N)
        self.base, self.F0 = [], None
        if src.in_memory:
            self.samples = self._memory_samples()
        self.clim_raw = self._raw_clim()
        self.reset_look()                                       # (each recording starts as it is)
        self.e_base.setText(self.base_str)
        self.e_fps.setText(fmt_g(self.fps) if np.isfinite(self.fps) else '')
        self.slider.blockSignals(True)
        self.slider.setRange(1, max(1, self.N))
        self.slider.setPageStep(max(1, self.N // 20))
        self.slider.setValue(1)
        self.slider.blockSignals(False)
        self.l_count.setText('/ %d' % self.N)
        self._info_text()
        self._enable(True)
        self.slider.setEnabled(self.N > 1)
        if self.hint is not None:
            self.vb1.removeItem(self.hint)
            self.hint = None
        for im in (self.img1, self.img2):                # one unit per pixel, centres at 1..W, 1..H (as in MATLAB)
            im.resetTransform()
            im.setPos(0, 0)                              # (setRect places it: pixel k is centred at k)
        self._update_x()
        self._layout()
        self.set_baseline(self.base_str)
        self._audio_open()
        self._traces()
        self.show_frame()
        self.strip.hide()
        self._start_scan()
        self._remember_dir(path)
        self._focus_frame()
        return True

    def _memory_samples(self):
        """~30 frames (subsampled luminance) for display ranges, from a recording in memory"""
        st = ss.sample_stride(self.H, self.W)
        return dict(stride=st, frames={k: sio.lum(self.src.frame(k)[::st, ::st]).copy() for k in ss.sample_indices(self.N)})

    def _info_text(self):
        if not self.loaded:
            self.l_name.setText(APP_NAME)
            self.info.setText(tr('Open a recording, or drop a file here'))
            return
        parts = [tr('%d x %d px') % (self.W, self.H)]
        if self.is_rgb:
            parts.append(tr('colour'))
        parts.append(tr('%d frames') % self.N)
        if np.isfinite(self.fps):
            parts.append('%s Hz' % fmt_g(self.fps))
        parts.append(str(self.src.dtype))
        if self.src.in_memory:
            parts.append(tr('%s in memory') % sio.size_text(self.src.data.nbytes / 1e6))
        else:
            parts.append(tr('decoded from disk as shown (cache %s)') % sio.size_text(getattr(self.src, 'cache').max_bytes / 1e6))
        if self.reduced and hasattr(self.src, 'info_p'):
            parts.append(tr('reduced: %s') % sio.reduction_text(self.finfo, self.src.info_p))
        if self.proxy is not None and self.proxy.complete:
            parts.append(tr('smooth scrubbing ready'))
        if self.audio is not None and self.audio.has_audio:
            parts.append(tr('sound: %s') % (self.audio.desc if self.audio.ok else self.audio.reason_text()))
        self.l_name.setText(os.path.basename(self.file))
        self.info.setText('    ' + '  \u00b7  '.join(parts))
        self.info.setToolTip(self.file)
        self.l_name.setToolTip(self.file)

    def _settings(self):
        return QtCore.QSettings(APP_NAME, APP_NAME)

    def _last_dir(self):
        return self._settings().value('last_dir', os.path.expanduser('~'))

    def _remember_dir(self, path):
        try:
            self._settings().setValue('last_dir', os.path.dirname(path))
        except Exception:
            pass

    def _raw_clim(self):
        """display range of the original frames: 0.5th - 99.5th percentile of ~30 frames (until a
        recording on disk has been scanned: of the first frame)"""
        if self.samples:
            v = np.concatenate([a.ravel() for a in self.samples['frames'].values()])
        else:
            g = sio.lum(self.frame(0)).ravel()
            v = g[::max(1, g.size // 200000)]
        v = np.sort(v.astype(float))
        v = v[np.isfinite(v)]
        if v.size == 0:
            return (0.0, 1.0)
        cl = (v[max(0, int(round(0.005 * v.size)) - 1)], v[max(0, int(round(0.995 * v.size)) - 1)])
        if not cl[1] > cl[0]:
            cl = (v.min(), v.max() + 1e-6)
        return cl

    def frame(self, k):
        return self.src.frame(k)

    # ------------------------------------------------------------------ background traces
    def _start_scan(self):
        """traces still missing (whole frame, new ROIs) and display samples, in one background pass"""
        if not self.loaded or self.src.in_memory or self.scanner.busy:
            return
        want_mean = self.mean_trace is None
        todo = [r for r in self.rois if r['trace'] is None]
        want_samples = self.samples is None
        want_proxy = self.proxy is not None and not self.proxy.complete
        want_store = self.store is not None and not self.store.complete
        if not (want_mean or todo or want_samples or want_proxy or want_store):
            return
        self._scan_rois = [r['name'] for r in todo]
        self.scan_progress = 0.0
        self.scanner.start(self.src, [r['mask'] for r in todo], want_mean, want_samples,
                           self.proxy if want_proxy else None, self.store if want_store else None)
        self._scan_t0 = time.perf_counter()
        self._scan_for_smooth = want_proxy or want_store
        self._show_scan_state()
        self._strip_update()

    def _scan_progress(self, job, f):
        self._index_check()
        if job == self.scanner.job:
            self.scan_progress = f
            self._show_scan_state()
            self._strip_update()

    def _strip_update(self, done=False):
        """the strip above the frame: how far smooth scrubbing is, and about how long it still takes"""
        if not self.loaded or (self.proxy is None and self.store is None and not done):
            self.strip.hide()
            return
        if done or (self.proxy is not None and self.proxy.complete):
            if self.strip.isVisible():
                self.l_strip.setText(tr('Smooth scrubbing ready'))
                self.p_strip.setValue(1000)
                self.l_eta.setText('')
                self.strip_timer.start(2500)
            return
        if not getattr(self, '_scan_for_smooth', False):
            return
        f = self.scan_progress
        self.strip_timer.stop()
        self.strip.show()
        self.l_strip.setText(tr('Preparing smooth scrubbing') + '   %d %%' % int(100 * f))
        self.p_strip.setValue(int(1000 * f))
        el = time.perf_counter() - getattr(self, '_scan_t0', time.perf_counter())
        if f > 0.02 and el > 1.0:
            left = el * (1 - f) / f
            if left < 10:
                eta = tr('a few seconds left')
            elif left < 90:
                eta = tr('about %d s left') % int(round(left / 5.0) * 5)
            else:
                eta = tr('about %d min left') % int(round(left / 60.0))
        else:
            eta = tr('estimating the time ...')
        self.l_eta.setText(eta + '   \u00b7   ' + tr('the video can be used meanwhile'))

    def _scan_done(self, job, res):
        if job != self.scanner.job or not self.loaded:
            return
        self.scanner.thread = None
        if isinstance(res, Exception):
            self.msg(tr('Computing the traces failed:\n%s') % res)
            return
        if res is None:
            return
        if isinstance(self.src, ss.VideoSource) and res.get('pts') and self.src.adopt_index(res['pts']):
            self._recount()
        if res['mean'] is not None:
            self.mean_trace = res['mean'][:self.N]
        for name, trc in zip(self._scan_rois, res['rois']):
            for r in self.rois:
                if r['name'] == name:
                    r['trace'] = trc[:self.N]
        if res['samples']:
            self.samples = dict(stride=res['stride'], frames=res['samples'])
            self.clim_raw = self._raw_clim()
            if self.range_str == 'auto':
                self.set_range('auto')
        ready = self.proxy is not None and self.proxy.complete
        if self.store is not None:
            ready = self._to_memory(res['n'])
        self._traces()
        if not self.preview:
            self.show_frame()
        self._info_text()
        self._strip_update(done=ready)
        self._start_scan()                                   # ROIs added meanwhile

    def _to_memory(self, n):
        """the background pass has read every frame into memory: the player moves to it (every frame
        exact and instant from now on, as a recording read into memory)"""
        st, self.store = self.store, None
        if st is None or n < 1 or n > st.N or not st.have[:n].all():
            return False
        old = self.src
        info = dict(old.info)
        info['N'] = n
        mean = self.mean_trace if (self.mean_trace is not None and len(self.mean_trace) >= n) else \
            [ss.fast_mean(st.data[k], old.is_rgb) for k in range(n)]
        src = ss.ArraySource(info, st.data if n == st.N else st.data[:n], np.asarray(mean)[:n], np.arange(1, n + 1))
        src.fps = old.fps
        src.times = getattr(old, 'times', None)
        self.settle.stop()
        self.refiner.cancel()
        self.ahead.stop()
        self.src = src
        if n != self.N:
            self._recount()
        self.preview = False
        for r in self.rois:                                  # ROIs drawn during the pass: from memory now
            if r['trace'] is None:
                r['trace'] = sio.roi_trace(src.data, r['mask'], self.is_rgb)
        with old.lock:                                       # (after a decode in progress)
            old.close()
        return True

    def _index_check(self):
        """a long video's real index arrived (it is read in the background): follow it when it differs"""
        if self.loaded and getattr(self.src, 'index_changed', False):
            self.src.index_changed = False
            self._recount()
            self._traces()

    def _recount(self):
        """the decoder found another number of frames than the index: follow it"""
        self.N = self.src.N
        self.kept = self.src.kept
        self.cur = min(self.cur, self.N - 1)
        self.slider.blockSignals(True)
        self.slider.setRange(1, max(1, self.N))
        self.slider.blockSignals(False)
        self.l_count.setText('/ %d' % self.N)
        self.base = [b for b in self.base if b <= self.N] or [1]
        if getattr(self.src, 'times', None) is not None:
            self.media_t = np.asarray(self.src.times, float)
        elif self.media_t is not None and len(self.media_t) != self.N and np.isfinite(self.src.fps) and self.src.fps > 0:
            self.media_t = (np.asarray(self.kept) - 1) / self.src.fps
        if self.mean_trace is not None and len(self.mean_trace) != self.N:
            self.mean_trace = None if len(self.mean_trace) < self.N else self.mean_trace[:self.N]
        for r in self.rois:
            if r['trace'] is not None and len(r['trace']) != self.N:
                r['trace'] = None if len(r['trace']) < self.N else r['trace'][:self.N]
        self._update_x()
        self._info_text()

    def _show_scan_state(self):
        for row in self.trace_rows:
            if row.get('wait') is not None:
                row['wait'].setText(tr('computing the trace (one pass through the recording) ... %d %%') % round(100 * self.scan_progress))

    def wait_traces(self, timeout=600):
        """block (events running) until the background traces are done; False if they did not finish"""
        t0 = time.perf_counter()
        def missing():
            return self.loaded and not self.src.in_memory and (
                self.mean_trace is None or any(r['trace'] is None for r in self.rois) or self.store is not None)
        while self.scanner.busy or missing():
            QtWidgets.QApplication.processEvents()
            time.sleep(0.005)
            if time.perf_counter() - t0 > timeout:
                return False
            if not self.scanner.busy:
                QtWidgets.QApplication.processEvents()
                if missing():
                    self._start_scan()
        QtWidgets.QApplication.processEvents()
        return True

    # ------------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        urls = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if urls:
            QtCore.QTimer.singleShot(0, lambda: self.load_file(urls[0]))

    # ------------------------------------------------------------------ display
    def _layout(self):
        """one panel (original) or two (original | relative change)"""
        rel = self.view == 'relative'
        lay = self.gv.ci
        for it in (self.vb2, self.cbar):
            if it in lay.items:
                lay.removeItem(it)
        if rel:
            lay.addItem(self.vb2, row=0, col=1)
            lay.addItem(self.cbar, row=0, col=2)
        self.vb2.setVisible(rel)
        self.cbar.setVisible(rel)
        for r in self.rois:
            for it in r['items2']:
                it.setVisible(rel)
        if self.loaded:
            if self.zoomed and self._zoom_rect is not None:
                self.vb1.setRange(self._zoom_rect, padding=0)
                self._clamp_view()
            else:
                self.vb1.setRange(xRange=(0.5, self.W + 0.5), yRange=(0.5, self.H + 0.5), padding=0)
            for w in (self.l_range, self.e_range, self.l_cmap, self.c_cmap):
                w.setEnabled(rel)
        for w in (self.l_range, self.e_range, self.l_cmap, self.c_cmap):
            w.setVisible(rel)

    def show_frame(self, f=None):
        """draw frame self.cur everywhere: the frame(s), the title, the slider, the cursors"""
        if not self.loaded:
            return
        k = self.cur
        if f is None:
            try:
                f = self.frame(k)
                self.preview = False
            except Exception as e:
                self.msg(tr('Frame %d cannot be shown:\n%s') % (k + 1, e))
                return
        small = f.shape[0] != self.H or f.shape[1] != self.W    # the scrubbing copy: shown at full size
        # drawn at the resolution it is shown at (S x S pixel blocks averaged: the panel shows no more);
        # zooming in or a larger window draws it again, finer (down to every pixel)
        st = 1 if small else self._display_step()
        if st < 3 and self.view != 'relative':
            st = 1                                           # (the original alone: cheap enough at full size)
        area = (0, 0, self.W, self.H) if small else self._draw_area(st)
        self._shown = None if small else (f, st, area)
        x0, y0, x1, y1 = area
        exact = self.view == 'relative'                         # (dF/F: exact block means)
        pre = self._pre
        self._pre = None
        if pre is not None and pre[1] is f and pre[3] == self._draw_key():
            g, d = pre[2]                                        # made ready ahead, while playing
        elif small:
            g, d = f, None
        else:
            g, d = self._drawable(f, st, area, exact)
        if small:
            rect = QtCore.QRectF(0.5, 0.5, self.W, self.H)
        else:
            rect = QtCore.QRectF(x0 + 0.5, y0 + 0.5, g.shape[1] * st, g.shape[0] * st)
        self._raw_base = (0, 255) if self.is_rgb and g.dtype == np.uint8 else self.clim_raw
        self.img1.setImage(g, autoLevels=False, levels=self.raw_levels())
        self.img1.setRect(rect)
        if self.view == 'relative' and self.F0 is not None:
            if small:                                            # the scrubbing copy: F0 at its size
                d = self._dff(g, self.F0p, self.F0okp)
            if d is not None:
                self.img2.setImage(d, autoLevels=False, levels=self.clim_dff)
                self.img2.setRect(rect)
        x = self.x[k]
        for row in self.trace_rows:
            row['cursor'].setValue(x)
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(k + 1)
            self.slider.blockSignals(False)
        self.e_frame.setText(str(k + 1))
        if self.drawing is None:
            self.title.setText(self._title_text())
        self.setWindowTitle('%s - %s - %s' % (APP_NAME, os.path.basename(self.file), tr('frame %d / %d') % (k + 1, self.N)))

    # ------------------------------------------------------------------ brightness and contrast
    def raw_levels(self, base=None):
        """the display range of the original frame: its normal range (BASE) narrowed by the contrast
        (x 2^(c/50): x0.25 .. x4) and moved by the brightness (b/100 of the normal range: +100 shows
        the normal maximum as black) - only how values map to grey; the values stay as they are"""
        lo, hi = (self._raw_base if base is None else base) or (0.0, 1.0)
        lo, hi = float(lo), float(hi)
        w = (hi - lo) / 2.0 ** (self.s_contrast.value() / 50.0)
        mid = (lo + hi) / 2.0 - self.s_bright.value() / 100.0 * (hi - lo)
        return (mid - w / 2.0, mid + w / 2.0)

    def _look_changed_from_normal(self):
        return self.s_bright.value() != 0 or self.s_contrast.value() != 0

    def _look_changed(self, *_):
        self.b_look_reset.setEnabled(self.loaded and self._look_changed_from_normal())
        if self.loaded and self._raw_base is not None and self.img1.image is not None:
            self.img1.setLevels(self.raw_levels())               # (the same image, other levels: instant)

    def reset_look(self):
        for s in (self.s_bright, self.s_contrast):
            s.blockSignals(True)
            s.setValue(0)
            s.blockSignals(False)
        self._look_changed()

    def _display_step(self):
        """S: frames are drawn as the mean of S x S pixel blocks, about one block per screen pixel of the
        panel (1: every pixel, when zoomed in far enough or the frame is small)"""
        try:
            dpr = float(self.gv.devicePixelRatioF())
        except Exception:
            dpr = 1.0
        pw, ph = self.vb1.width() * dpr, self.vb1.height() * dpr
        if pw < 32 or ph < 32:
            return 1
        (x0, x1), (y0, y1) = self.vb1.viewRange()
        vw, vh = min(self.W, x1 - x0), min(self.H, y1 - y0)
        return max(1, int(min(vw / pw, vh / ph) + 0.25))   # (1.75 image pixels a screen pixel: blocks of 2)

    def _drawable(self, f, st, area, exact):
        """(g, d): the frame as drawn, the part in AREA as S x S block means, and (EXACT: the relative view)
        its relative change in %, from exact block means of the frame and of F0"""
        x0, y0, x1, y1 = area
        g = f if area == (0, 0, self.W, self.H) else f[y0:y1, x0:x1]
        g = sio.shrink(g, st, exact=exact)
        d = None
        if exact and self.F0 is not None:
            F0, ok = self._F0_at(st)
            by, bx = y0 // st, x0 // st
            d = self._dff(g, F0[by:by + g.shape[0], bx:bx + g.shape[1]], ok[by:by + g.shape[0], bx:bx + g.shape[1]])
        if f.dtype == np.uint8 and g.dtype != np.uint8:      # the original panel: 8 bits again (drawn faster)
            g = np.rint(g).astype(np.uint8)
        return g, d

    @staticmethod
    def _dff(g, F0, ok):
        """(G - F0) / F0 in %, NaN where F0 is unusable (one new array, the rest in place)"""
        if F0 is None or F0.shape != g.shape[:2]:
            return None
        d = np.subtract(sio.lum(g), F0, dtype=np.float32)
        d /= F0
        d *= 100
        d[~ok] = np.nan
        return d

    def _draw_key(self):
        """what a frame is made ready for: this recording, step, area, exact (dF/F)"""
        if self._shown is None:
            return None
        return (id(self.src), self._shown[1], self._shown[2], self.view == 'relative', id(self.F0))

    def _ahead_start(self, k_from):
        """(playing) the pipeline reads and prepares the frames from K_FROM on, at the clock's pace"""
        key = self._draw_key()
        if key is None or self.drawing is not None or k_from >= self.N:
            self.ahead.stop()
            return
        src, store = self.src, self.store
        _, st, area, exact, _ = key

        scanner = self.scanner

        def get(k):
            f = store.get(k) if store is not None else None
            if f is None:
                f = src.frame(k)
                scanner.offer(k, f)                      # (prepared for smooth scrubbing too)
            return f
        self.ahead.start(key, get, lambda f: self._drawable(f, st, area, exact), self._due_in, k_from, self.N)

    def view_busy(self):
        return self._shown is None or self.drawing is not None

    def _draw_area(self, st):
        """(x0, y0, x1, y1): the pixels drawn. Zoomed in, the part in view and a sixth of a view around it (moving
        the view a little needs no new drawing); x0, y0 on whole S x S blocks"""
        if not self.zoomed:
            return 0, 0, self.W, self.H
        r = self.vb1.viewRect()
        mx, my = 0.15 * r.width(), 0.15 * r.height()
        x0 = max(0, int(np.floor(r.left() - 0.5 - mx)))
        y0 = max(0, int(np.floor(r.top() - 0.5 - my)))
        x1 = min(self.W, int(np.ceil(r.right() - 0.5 + mx)))
        y1 = min(self.H, int(np.ceil(r.bottom() - 0.5 + my)))
        x0, y0 = x0 - x0 % st, y0 - y0 % st
        if x1 - x0 < st or y1 - y0 < st:
            return 0, 0, self.W, self.H
        return x0, y0, x1, y1

    def _F0_at(self, st):
        """F0 (and where it is usable) at the resolution of frames drawn with step ST"""
        if st <= 1:
            return self.F0, self.F0ok
        c = self._F0s.get(st)
        if c is None:
            g = sio.shrink(np.where(self.F0ok, self.F0, 0).astype(np.float32), st)
            mx = np.abs(g).max() if g.size else 0
            ok = np.abs(g) > max(np.finfo(np.float32).eps, 1e-6 * mx)
            c = self._F0s[st] = (np.where(ok, g, np.nan).astype(np.float32), ok)
        return c

    def _redraw_if_needed(self):
        """after zooming or resizing: the frame again, at the resolution it is now shown at"""
        if not self.loaded or self._shown is None:
            return
        if self.zoomed:
            self._clamp_view()                               # (a resize keeps the centre: back onto the frame)
            self._zoom_rect = self.vb1.viewRect()
        f, st, (x0, y0, x1, y1) = self._shown
        want = self._display_step()
        if want < 3 and self.view != 'relative':
            want = 1
        r = self.vb1.viewRect()
        inside = (x0 <= max(0, r.left() - 0.5) and y0 <= max(0, r.top() - 0.5)
                  and x1 >= min(self.W, r.right() - 0.5) and y1 >= min(self.H, r.bottom() - 0.5))
        if want != st or not inside or (not self.zoomed and (x0, y0, x1, y1) != (0, 0, self.W, self.H)):
            self.show_frame(f)

    # ------------------------------------------------------------------ zoom
    def zoom(self, delta, at):
        """Ctrl + wheel: zoom in (wheel forward) or out around the point AT (x, y) of the frame"""
        if not self.loaded or not delta:
            return
        f = 0.8 ** (delta / 120.0)
        r = self.vb1.viewRect()
        full = r.width() >= self.W and r.height() >= self.H
        if f > 1 and full:
            return
        if f < 1 and min(r.width(), r.height()) * f < 8:          # at most ~8 pixels across
            f = 8.0 / max(1e-6, min(r.width(), r.height()))
            if f >= 1:
                return
        x, y = at
        nr = QtCore.QRectF(x - (x - r.left()) * f, y - (y - r.top()) * f, r.width() * f, r.height() * f)
        if f > 1 and nr.width() >= self.W and nr.height() >= self.H:
            self.zoom_fit()
            return
        self.vb1.setRange(nr, padding=0)
        self.zoomed = True
        self._clamp_view()
        self._zoom_rect = self.vb1.viewRect()

    def zoom_fit(self):
        """the whole frame again (double-click, Ctrl+0)"""
        self.zoomed, self._zoom_rect = False, None
        if self.loaded:
            self.vb1.setRange(xRange=(0.5, self.W + 0.5), yRange=(0.5, self.H + 0.5), padding=0)

    def _clamp_view(self):
        """keep the zoomed view on the frame (centred along a side the frame does not fill)"""
        r = self.vb1.viewRect()
        x, y = r.left(), r.top()
        for lo, size, n, setter in ((x, r.width(), self.W, 'x'), (y, r.height(), self.H, 'y')):
            if size >= n:
                v = 0.5 + (n - size) / 2.0
            else:
                v = min(max(lo, 0.5), n + 0.5 - size)
            if setter == 'x':
                x = v
            else:
                y = v
        if abs(x - r.left()) > 1e-6 or abs(y - r.top()) > 1e-6:
            self.vb1.setRange(QtCore.QRectF(x, y, r.width(), r.height()), padding=0)
        if self.zoomed and r.width() >= self.W and r.height() >= self.H:
            self.zoom_fit()

    def _title_text(self):
        k = self.cur
        t = tr('frame %d / %d') % (k + 1, self.N)
        if self.reduced:
            t += '   ' + tr('(recorded frame %d)') % self.kept[k]
        if np.isfinite(self.fps):
            t += '     t = %.3f s' % self.x[k]
        if self.view == 'relative' and (k + 1) in self.base:
            t += '     ' + tr('[baseline]')
        if self.slider.isSliderDown() and k + 1 != self.slider.value():
            t += '     ' + tr('(key frame while dragging)')
        if self.preview:
            t += '     \u00b7'                                 # (a dot: the scrubbing copy, exact frame coming)
        return t

    # ------------------------------------------------------------------ navigation and playback
    def goto(self, k, fast=False, _tick=False):
        """show frame K (0-based).
        In memory: the frame itself. From disk: the exact frame when it comes at once (cached, or just
        ahead of the decoder: stepping forward, playing); otherwise its scrubbing copy at once and the
        exact frame from a background decoder a moment later (FAST, dragging: when the slider rests).
        Before the scrubbing copy of that part exists, a nearby key frame while dragging."""
        if not self.loaded:
            return
        k = int(max(0, min(self.N - 1, round(k))))
        src = self.src
        have_proxy = self.proxy is not None and k in self.proxy
        try:
            f, exact = None, True
            if _tick and self._pre is not None and self._pre[0] == k:
                f = self._pre[1]                             # read and made ready ahead
            if f is None and self.store is not None:
                f = self.store.get(k)                        # read into memory already
            if f is not None:
                pass
            elif src.in_memory or not isinstance(src, ss.VideoSource):
                f = self.frame(k)
            else:
                f = src.cached(k)                            # (never waits for the background decoder)
            if f is not None:
                pass
            elif _tick or (src.is_cheap(k) and not (self.refiner.busy and have_proxy)):
                f = self.frame(k)                            # stepping forward, playing: decoded at once
            elif have_proxy:
                f, exact = self.proxy.get(k), False
            elif fast:
                f, k = src.frame_fast(k)
                exact = src.is_cheap(k)
            else:
                f = self.frame(k)
        except Exception as e:
            self.msg(tr('Frame %d cannot be shown:\n%s') % (k + 1, e))
            return
        self.cur = k
        self.preview = not exact
        if exact and f is not None and not src.in_memory:
            self.scanner.offer(k, f)                         # decoded anyway: smooth scrubbing gains it
        self.show_frame(f)
        if exact:
            self.settle.stop()
            self.refiner.cancel()
        elif fast:
            self.settle.start()                              # exact once the slider rests
        else:
            self._refine_now()
        if not _tick and self.timer.isActive():
            self._play_anchor()                               # moved while playing: the clock restarts here
            if self.audio is not None and self.audio.playing:
                self._audio_start()                           # and the sound follows
        if self.timer.isActive() and (not _tick or self.ahead.key != self._draw_key()):
            self._ahead_start(k + 1)                          # (jumped, zoomed, other view: from here)

    def _slider_released(self):
        k = self.slider.value() - 1
        if self.preview and k == self.cur:
            self.settle.stop()
            self._refine_now()
        else:
            self.goto(k)

    def _refine_now(self):
        if self.loaded and self.preview:
            self.refiner.request(self.src, self.cur)

    def _refined(self, gen, k, f):
        if gen != self.refiner.gen or not self.loaded or k != self.cur or not self.preview:
            return
        if isinstance(f, Exception):
            self.msg(tr('Frame %d cannot be shown:\n%s') % (k + 1, f))
            return
        self.preview = False
        self.show_frame(f)

    def step(self, n):
        if self.loaded:
            self.goto(self.cur + n)

    def wheel(self, delta):
        if delta:
            self.step(-int(np.sign(delta)))              # wheel down: forward

    def _frame_typed(self):
        try:
            self.goto(int(round(float(self.e_frame.text()))) - 1)
        except ValueError:
            self.e_frame.setText(str(self.cur + 1))

    def play_rate(self):
        """frames shown per second: the recording in real time (every n-th frame kept: rate / n)"""
        if np.isfinite(self.fps) and self.fps > 0:
            step = self.src.info_p['step'] if (self.src is not None and hasattr(self.src, 'info_p')) else 1
            return self.fps / max(1, step)
        return 10.0

    def _play_toggled(self, on):
        if on and self.loaded:
            self._drops.clear()
            self._play_icon()
            self._play_count = 0
            self._play_max = getattr(self, '_play_max_next', None)
            self._play_max_next = None
            self._play_anchor()
            if self._sound_state() and self.cb_sound.isChecked():
                self._audio_start()
            # the timer looks twice per frame; the frame shown follows the sound's clock, or the wall
            # clock: playback keeps the recording's own pace even when a frame comes slowly from disk
            self.timer.start(max(1, int(round(500 / self.play_rate()))))
            self._ahead_start(self.cur + 1)
        else:
            self.timer.stop()
            self._audio_stop()
            self.ahead.stop()
            self._pre = None
            self.scanner.set_paused(False)                   # the background pass goes on
            if self.strip.isVisible():
                self._strip_update()
            self.b_play.blockSignals(True)
            self.b_play.setChecked(False)
            self.b_play.blockSignals(False)
            self._play_icon()

    def _tick(self):
        if self.audio is not None and self.audio.playing:
            t = self.audio.clock()                         # the frame whose time is being heard
            if t is not None:
                k = int(np.searchsorted(self.media_t, t + 1e-6, side='right')) - 1
                k = max(0, k)
                if k >= self.N - 1 and t > self.media_t[-1] + 1.0 / max(1e-6, self.play_rate()):
                    k = self.N                             # past the last frame
                if k <= self.cur:
                    return
                n = k - self.cur
            else:                                           # the sound has ended (or its device does not keep time)
                self._audio_stop()
                self._play_anchor()
                k, n = self.cur + 1, 1
        else:
            k = self._play_k0 + int((time.perf_counter() - self._play_t0) * self.play_rate() + 1e-6)
            if k <= self.cur:
                return
            if k > self.cur + 1 and self._play_max is not None:
                k = min(k, self.cur + (self._play_max - self._play_count))
            n = k - self.cur
        if k < self.N:
            k = self._pace(k)
            if k is None:
                return
            n = k - self.cur
            self._backoff(max(0, n - 1))
        if k >= self.N:
            if self.cb_loop.isChecked():
                self.goto(0, _tick=True)
                self._play_anchor()
                if self.audio is not None and self.audio.playing:
                    self._audio_start()
            else:
                self.goto(self.N - 1, _tick=True)
                self.stop()
                return
        else:
            self.goto(k, _tick=True)
        self._play_count += max(1, n)
        if self._play_max is not None and self._play_count >= self._play_max:
            self.stop()

    def _pace(self, k):
        """the frame to show now, when the clock asks for K: the newest frame the pipeline made ready that is
        due; None: wait a moment, it is on its way (rather than decoding another one here and falling
        behind); K itself when the pipeline has nothing coming (it starts again from there)"""
        if self.ahead.key is None or self.ahead.key != self._draw_key():
            return k
        r = self.ahead.take(k, self.cur)
        if r is not None:
            self._pre = (r[0], r[1], r[2], self.ahead.key)
            return r[0]
        if self.ahead.pending(self.cur) and k - self.cur <= max(3, int(0.5 * self.play_rate())):
            return None
        self.ahead.stop()
        return k

    def _backoff(self, dropped):
        """smooth scrubbing goes on being prepared while the video plays; only while playback drops frames
        (the computer or the disk cannot do both) does the background pass stop reading for a moment"""
        now = time.perf_counter()
        q = self._drops
        q.append((now, dropped))
        while q and q[0][0] < now - 1.0:
            q.popleft()
        if not self.scanner.busy:
            return
        if sum(d for _, d in q) > max(2, 0.1 * self.play_rate()):
            self.scanner.set_paused(True)
            self._backoff_until = now + 1.5
        elif self.scanner.pause_ev.is_set() and now > self._backoff_until:
            self.scanner.set_paused(False)

    def _due_in(self, dt):
        """the frame the playback clock will ask for DT seconds from now"""
        if self.audio is not None and self.audio.playing and self.media_t is not None:
            t = self.audio.clock()
            if t is not None:
                return int(np.searchsorted(self.media_t, t + dt + 1e-6, side='right')) - 1
        return self._play_k0 + int((time.perf_counter() + dt - self._play_t0) * self.play_rate() + 1e-6)

    def _play_anchor(self):
        """the playback clock starts (again) at the frame shown"""
        self._play_t0 = time.perf_counter()
        self._play_k0 = self.cur

    def play(self, n_frames=None):
        """start playing (scripted: N_FRAMES frames, then stop)"""
        self._play_max_next = n_frames
        self.b_play.setChecked(True)

    def stop(self):
        if self.b_play.isChecked() or self.timer.isActive():
            self._play_toggled(False)

    # ------------------------------------------------------------------ sound
    def _audio_open(self):
        self.audio = None
        self.media_t = None
        if not self.loaded or self.finfo.get('type') != 'video':
            self._sound_state()
            return
        v0 = (self.src.pts[0] * self.src.tb) if isinstance(self.src, ss.VideoSource) else self.finfo.get('v0', 0.0)
        self.audio = sa.AudioPlayer(self.file, v0, backend=getattr(self, 'audio_backend', None))
        # the time of every frame (the sound's clock is turned into a frame by it)
        if getattr(self.src, 'times', None) is not None:
            self.media_t = np.asarray(self.src.times, float)
        elif np.isfinite(self.src.fps) and self.src.fps > 0:
            self.media_t = (np.asarray(self.kept) - 1) / self.src.fps
        self._sound_state()
        self._info_text()

    def _sound_state(self):
        """sound can play: the video has it, a device is there, and the picture runs at its own rate"""
        a = self.audio
        if a is None or not a.has_audio:
            self.cb_sound.setEnabled(False)
            self.cb_sound.setToolTip(tr('no sound track in this recording'))
            return False
        if not a.ok:
            self.cb_sound.setEnabled(False)
            self.cb_sound.setToolTip(tr('sound off: %s') % a.reason_text())
            return False
        native = self.src.fps
        same = (np.isfinite(self.fps) and np.isfinite(native) and abs(self.fps - native) < 1e-6 * native
                and not self.reduced and self.media_t is not None)
        self.cb_sound.setEnabled(bool(same))
        self.cb_sound.setToolTip(tr('play the sound of the video (%s)') % a.desc if same else
                                 tr("sound plays only at the video's own frame rate (%s Hz), with every frame") % fmt_g(native))
        return bool(same)

    def _audio_start(self):
        if self.audio is None or self.media_t is None:
            return False
        return self.audio.start(float(self.media_t[self.cur]))

    def _audio_stop(self):
        if self.audio is not None:
            self.audio.stop()

    def _sound_toggled(self, on):
        if not self.b_play.isChecked():
            return
        self._play_anchor()
        if on and self._sound_state():
            self._audio_start()
        else:
            self._audio_stop()

    # ------------------------------------------------------------------ view, baseline, colour, frame rate
    def set_view(self, v):
        self.draw_end()
        self.view = v
        self.c_view.blockSignals(True)
        self.c_view.setCurrentIndex(1 if v == 'relative' else 0)
        self.c_view.blockSignals(False)
        if not self.loaded:
            return
        if v == 'relative' and self.F0 is None:
            self.set_baseline(self.base_str)
        self._layout()
        self._traces()
        self.show_frame()

    def set_baseline(self, s):
        if not self.loaded:
            return
        b = sio.parse_frames(s, self.N)
        if not b:
            self.e_base.setText(self.base_str)
            return
        self.base, self.base_str = b, s.strip()
        self.e_base.setText(self.base_str)
        F0 = np.zeros((self.H, self.W), np.float64)
        prog = None
        if not self.src.in_memory and len(b) > 30:
            prog = QtWidgets.QProgressDialog(tr('Averaging the baseline frames ...'), None, 0, len(b), self)
            prog.setWindowModality(Qt.WindowModal)
            prog.setMinimumDuration(300)
        for i, k in enumerate(b):
            F0 += sio.lum(self.frame(k - 1))
            if prog is not None and i % 10 == 0:
                prog.setValue(i)
                QtWidgets.QApplication.processEvents()
        if prog is not None:
            prog.close()
        F0 = (F0 / len(b)).astype(np.float32)
        mx = np.abs(F0).max() if F0.size else 0
        self.F0ok = np.abs(F0) > max(np.finfo(np.float32).eps, 1e-6 * mx)
        F0[~self.F0ok] = np.nan
        self.F0 = F0
        self._F0s = {}
        self.F0p = self.F0okp = None
        if self.proxy is not None:                          # F0 at the size of the scrubbing copy
            from PIL import Image
            g = np.where(self.F0ok, F0, 0).astype(np.float32)
            F0p = np.asarray(Image.fromarray(g, 'F').resize((self.proxy.pw, self.proxy.ph), Image.BOX))
            self.F0okp = np.abs(F0p) > max(np.finfo(np.float32).eps, 1e-6 * mx)
            self.F0p = np.where(self.F0okp, F0p, np.nan).astype(np.float32)
        self.set_range(self.range_str)
        if self.view == 'relative':
            self._traces()
            self.show_frame()

    def set_range(self, s):
        """colour range of the relative change: auto (symmetric 99th percentile of |dF/F| over up to 30 frames),
        a (symmetric), or 'lo hi'"""
        if not self.loaded or self.F0 is None:
            return
        s = s.strip()
        try:
            v = [float(t) for t in s.replace(',', ' ').split()]
        except ValueError:
            v = []
        if s.lower() == 'auto' or not v:
            # the ~30 sample frames (a recording on disk: the current frame until it has been scanned)
            if self.samples:
                st = self.samples['stride']
                F0s = self.F0[::st, ::st]
                frames = list(self.samples['frames'].values())
            else:
                F0s, frames = self.F0, [sio.lum(self.frame(self.cur))]
            a = []
            for g in frames:
                d = np.abs((g - F0s) / F0s * 100).ravel()
                d = d[np.isfinite(d)]
                a.append(d[::max(1, d.size // 100000)])
            a = np.sort(np.concatenate(a)) if a else np.zeros(0)
            lim = max(a[max(0, int(round(0.99 * a.size)) - 1)], 1e-3) if a.size else 1.0
            cl, s = (-lim, lim), 'auto'
        elif len(v) == 1:
            cl = (-abs(v[0]), abs(v[0]))
        else:
            cl = tuple(sorted(v[:2]))
            if cl[1] == cl[0]:
                cl = (cl[0], cl[0] + 1)
        self.range_str, self.clim_dff = s, (float(cl[0]), float(cl[1]))
        self.e_range.setText(s)
        self.cbar.setLevels(self.clim_dff)
        if self.view == 'relative':
            self.show_frame()

    def set_cmap(self, name):
        self.cmap = name
        self.c_cmap.blockSignals(True)
        self.c_cmap.setCurrentText(name)
        self.c_cmap.blockSignals(False)
        self.cbar.setColorMap(cmap_lut(name))
        self.cbar.setLevels(self.clim_dff)

    def set_fps(self, s):
        if not self.loaded:
            return
        try:
            v = float(s)
        except (TypeError, ValueError):
            v = float('nan')
        if not (np.isfinite(v) and v > 0):
            v = float('nan')
        self.fps = v
        self.e_fps.setText(fmt_g(v) if np.isfinite(v) else '')
        if self.timer.isActive():
            if not self._sound_state():
                self._audio_stop()
            self._play_anchor()
            self.timer.setInterval(max(1, int(round(500 / self.play_rate()))))
        else:
            self._sound_state()
        self._info_text()
        self._traces()
        self.show_frame()

    # ------------------------------------------------------------------ traces
    def _traces(self):
        """one row per signal (whole frame, then every ROI), each with its own y axis"""
        if not self.loaded:
            return
        self.tv.ci.clear()
        self.trace_rows = []
        self.tv.ci.layout.setColumnFixedWidth(0, 100)
        self.tv.ci.layout.setColumnStretchFactor(1, 1)
        xl = self._update_x()
        rel = self.view == 'relative' and len(self.base) > 0
        th = self.th
        rows = [(tr('whole frame'), self.mean_trace, QtGui.QColor(th['trace0']).getRgb()[:3])] + [(r['name'], r['trace'], r['colour']) for r in self.rois]
        xr = (self.x[0], self.x[-1]) if self.x[-1] > self.x[0] else (self.x[0] - 0.5, self.x[0] + 0.5)
        first = None
        for i, (name, y, col) in enumerate(rows):
            waiting = y is None
            y = np.full(self.N, np.nan) if waiting else np.asarray(y, float)
            unit = 'a.u.'
            if rel and not waiting:
                b0 = y[np.array(self.base) - 1].mean()
                y = (y - b0) / max(abs(b0), np.finfo(float).eps) * 100
                unit = 'dF/F, %'
            elif rel:
                unit = 'dF/F, %'
            lo, hi = (np.nanmin(y), np.nanmax(y)) if not waiting else (np.nan, np.nan)
            yl = (lo, hi) if (np.isfinite(lo) and hi > lo) else ((lo - 0.5, lo + 0.5) if np.isfinite(lo) else (0, 1))
            pad = 0.12 * (yl[1] - yl[0])                 # room for the min / max labels
            yl = (yl[0] - pad, yl[1] + pad)
            lab = pg.LabelItem('<span style="color: rgb%s; font-size: 8pt; font-weight: 600">%s</span><br>'
                               '<span style="color: %s; font-size: 7pt">%s</span>' % (str(tuple(col)), name, th['muted'], unit),
                               justify='right')
            lab.setFixedWidth(95)
            self.tv.ci.addItem(lab, row=i, col=0)
            pl = pg.PlotItem(viewBox=TraceBox(self))
            pl.hideButtons()
            pl.setMenuEnabled(False)
            pl.showGrid(x=True, y=True, alpha=th['grid'])
            for ax_ in ('left', 'bottom'):
                a_ = pl.getAxis(ax_)
                a_.setPen(pg.mkPen(th['axis']))
                a_.setTextPen(pg.mkPen(th['muted']))
                a_.setStyle(tickLength=-4)
            la = pl.getAxis('left')
            la.setWidth(54)
            la.setStyle(hideOverlappingLabels=False)
            la.setStyle(tickFont=QtGui.QFont('Segoe UI', 7))
            if hi > lo:
                la.setTicks([[(lo, fmt_tick(lo)), (hi, fmt_tick(hi))], []])
            ba = pl.getAxis('bottom')
            ba.setStyle(tickFont=QtGui.QFont('Segoe UI', 7))
            if i < len(rows) - 1:
                ba.setStyle(showValues=False)
            else:
                pl.setLabel('bottom', xl, **{'font-size': '8pt', 'color': th['muted']})
            if rel:
                for a, b in sio.segments(self.base):
                    reg = pg.LinearRegionItem((self.x[a - 1], self.x[b - 1]), movable=False,
                                              brush=pg.mkBrush(*th['shade']), pen=pg.mkPen(None))
                    reg.setZValue(-10)
                    pl.addItem(reg)
            wait = None
            if waiting:
                wait = pg.TextItem('', color=th['muted'], anchor=(0.5, 0.5))
                wait.setPos(0.5 * (xr[0] + xr[1]), 0.5)
                pl.addItem(wait)
            else:
                pl.plot(self.x, y, pen=pg.mkPen(col, width=1.2))
            cur = pg.InfiniteLine(self.x[self.cur], angle=90, pen=pg.mkPen(th['cursor'], width=1, style=Qt.DashLine))
            pl.addItem(cur)
            pl.setXRange(*xr, padding=0)
            pl.setYRange(*yl, padding=0)
            if first is None:
                first = pl
            else:
                pl.setXLink(first)
            self.tv.ci.addItem(pl, row=i, col=1)
            self.trace_rows.append(dict(plot=pl, cursor=cur, y=y, wait=wait))
        self._show_scan_state()

    def _update_x(self):
        """the time axis: s at the frame rate, or the recorded frame numbers"""
        if np.isfinite(self.fps):
            self.x = (np.asarray(self.kept) - 1) / self.fps
            return tr('time (s)')
        self.x = np.asarray(self.kept).astype(float)
        return tr('recorded frame')

    def trace_click(self, x):
        if self.loaded:
            self.goto(int(np.argmin(np.abs(self.x - x))))

    # ------------------------------------------------------------------ ROI drawing
    def draw_start(self, shape):
        """the user draws the ROI with the mouse on the frame (either panel in the relative view):
        press the left button, drag, release. rect: corner to corner; freehand: trace the outline,
        which closes back to its start. Esc or a right-click cancels."""
        if not self.loaded:
            return
        self.draw_end()
        self.stop()
        self.drawing = dict(shape=shape, state='wait', panel=None, pts=[], lines=[])
        self.title.setText(self._draw_msg(shape, False))
        self.title.setStyleSheet('color: %s' % self.th['warn'])
        self.gv.setCursor(Qt.CrossCursor)

    def _draw_msg(self, shape, again):
        s = ('ROI rectangle: press the left button on the frame, drag to the opposite corner, release   (Esc: cancel)'
             if shape == 'rect' else
             'ROI freehand: press the left button on the frame, trace the outline, release to close it   (Esc: cancel)')
        s = tr(s)
        return (tr('Too small - draw again.   ') + s) if again else s

    def draw_end(self):
        """stop drawing (if drawing)"""
        D = self.drawing
        if D is None:
            return
        for vb, it in D['lines']:
            vb.removeItem(it)
        self.drawing = None
        self.title.setStyleSheet('')
        self.gv.unsetCursor()
        if self.loaded:
            self.title.setText(self._title_text())

    def draw_step(self, ev, pt, panel):
        """one step: 'down' starts, 'move' extends, 'up' finishes and adds the ROI"""
        D = self.drawing
        if D is None or not self.loaded:
            return
        pt = (min(max(pt[0], 0.5), self.W + 0.5), min(max(pt[1], 0.5), self.H + 0.5))
        if ev == 'down':
            if D['state'] != 'wait':
                return
            D.update(state='drag', panel=panel, pts=[pt])
            for vb in ([self.vb1, self.vb2] if self.view == 'relative' else [self.vb1]):
                it = pg.PlotCurveItem(pen=pg.mkPen(DRAW_COLOUR, width=2))
                vb.addItem(it)
                D['lines'].append((vb, it))
        elif ev in ('move', 'up'):
            if D['state'] != 'drag':
                return
            if D['shape'] == 'rect':
                D['pts'] = [D['pts'][0], pt]
            elif np.hypot(pt[0] - D['pts'][-1][0], pt[1] - D['pts'][-1][1]) >= 1:
                D['pts'].append(pt)                    # a vertex at least 1 pixel from the last
        if ev == 'up':
            xy, ok = self._draw_result(D)
            if ok:
                shape = D['shape']
                self.draw_end()
                self.add_roi(shape, xy)
                return
            for vb, it in D['lines']:
                vb.removeItem(it)
            D.update(state='wait', panel=None, pts=[], lines=[])
            self.title.setText(self._draw_msg(D['shape'], True))
            return
        p = np.array(D['pts'])
        if D['shape'] == 'rect':
            xs, ys = p[[0, -1], 0], p[[0, -1], 1]
            xd, yd = xs[[0, 1, 1, 0, 0]], ys[[0, 0, 1, 1, 0]]
        else:
            xd, yd = np.r_[p[:, 0], p[0, 0]], np.r_[p[:, 1], p[0, 1]]
        for _, it in D['lines']:
            it.setData(xd, yd)

    @staticmethod
    def _draw_result(D):
        p = np.array(D['pts'], float)
        if D['shape'] == 'rect':
            if len(p) < 2:
                return None, False
            x, y = np.sort(p[[0, -1], 0]), np.sort(p[[0, -1], 1])
            return (np.c_[x, y], True) if (x[1] - x[0] >= 1 and y[1] - y[0] >= 1) else (None, False)
        if len(p) >= 3:
            area = 0.5 * abs(np.dot(p[:, 0], np.roll(p[:, 1], 1)) - np.dot(p[:, 1], np.roll(p[:, 0], 1)))
            if area >= 2:
                return p, True
        return None, False

    def draw_path(self, shape, path, panel=1):
        """replay a mouse path ([n x 2] frame pixels) as a drag (scripted use and testing)"""
        self.draw_start(shape)
        path = np.asarray(path, float).reshape(-1, 2)
        self.draw_step('down', path[0], panel)
        for q in path[1:]:
            self.draw_step('move', q, panel)
        self.draw_step('up', path[-1], panel)
        self.draw_end()

    # ------------------------------------------------------------------ ROIs
    def add_roi(self, shape, xy):
        """SHAPE 'rect' (XY: two opposite corners, or four) or 'freehand' (any closed outline)"""
        if not self.loaded:
            return
        xy = np.asarray(xy, float)
        if shape == 'rect' and len(xy) == 2:
            x, y = np.sort(xy[:, 0]), np.sort(xy[:, 1])
            xy = np.c_[x[[0, 1, 1, 0]], y[[0, 0, 1, 1]]]
        mask = sio.polygon_mask(xy, self.H, self.W)
        if not mask.any():
            self.msg(tr('The ROI holds no pixel.'))
            return
        col = ROI_COLOURS[len(self.rois) % len(ROI_COLOURS)]
        self.roi_count += 1
        name = 'ROI %d' % self.roi_count
        xc, yc = np.r_[xy[:, 0], xy[0, 0]], np.r_[xy[:, 1], xy[0, 1]]
        items1, items2 = [], []
        for vb, items in ((self.vb1, items1), (self.vb2, items2)):
            ln = pg.PlotCurveItem(xc, yc, pen=pg.mkPen(col, width=2))
            tx = pg.TextItem(' ' + name, color=col, anchor=(0, 1))
            f = QtGui.QFont()
            f.setBold(True)
            tx.setFont(f)
            tx.setPos(xy[0, 0], xy[0, 1])
            vb.addItem(ln)
            vb.addItem(tx)
            items += [ln, tx]
        for it in items2:
            it.setVisible(self.view == 'relative')
        # its trace: at once in memory; from disk, in the background (one pass, with the other new ROIs)
        tr = sio.roi_trace(self.src.data, mask, self.is_rgb) if self.src.in_memory else None
        self.rois.append(dict(name=name, xy=xy, mask=mask, colour=col, items1=items1, items2=items2, trace=tr))
        self._traces()
        self.show_frame()
        self._start_scan()

    def remove_roi(self, which=None):
        """remove ROIs (indices, 0-based); None: ask"""
        if not self.rois:
            self.msg(tr('There is no ROI to remove.'))
            return
        if which is None:
            d = QtWidgets.QDialog(self)
            d.setWindowTitle(tr('Remove ROI'))
            lay = QtWidgets.QVBoxLayout(d)
            lay.addWidget(QtWidgets.QLabel(tr('Remove which ROI(s)?')))
            lw = QtWidgets.QListWidget()
            lw.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            lw.addItems([r['name'] for r in self.rois])
            lay.addWidget(lw)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(d.accept)
            bb.rejected.connect(d.reject)
            lay.addWidget(bb)
            if d.exec() != QtWidgets.QDialog.Accepted:
                return
            which = [lw.row(it) for it in lw.selectedItems()]
        for i in sorted(set(which), reverse=True):
            if 0 <= i < len(self.rois):
                r = self.rois.pop(i)
                for vb, its in ((self.vb1, r['items1']), (self.vb2, r['items2'])):
                    for it in its:
                        vb.removeItem(it)
        self._traces()
        self.show_frame()

    def clear_rois(self):
        for r in self.rois:
            for vb, its in ((self.vb1, r['items1']), (self.vb2, r['items2'])):
                for it in its:
                    vb.removeItem(it)
        self.rois = []
        self.roi_count = 0

    # ------------------------------------------------------------------ export
    def export_csv(self, path):
        if not self.loaded:
            return False
        if not path:
            b = os.path.splitext(self.file)[0]
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, tr('Export the traces'), b + '_sciplayer_traces.csv', 'CSV (*.csv)')
            if not path:
                return False
        if not self.src.in_memory and (self.mean_trace is None or any(r['trace'] is None for r in self.rois)):
            prog = QtWidgets.QProgressDialog(tr('The traces are still being computed ...'), None, 0, 0, self)
            prog.setWindowModality(Qt.WindowModal)
            prog.setMinimumDuration(0)
            prog.show()
            ok = self.wait_traces()
            prog.close()
            if not ok:
                self.msg(tr('The traces are not ready yet; export again in a moment.'))
                return False
        names = ['whole_frame'] + [r['name'].replace(' ', '_') for r in self.rois]
        Y = np.column_stack([self.mean_trace] + [r['trace'] for r in self.rois])
        R = np.full(Y.shape, np.nan)
        if self.base:
            b0 = Y[np.array(self.base) - 1].mean(axis=0)
            R = (Y - b0) / np.maximum(np.abs(b0), np.finfo(float).eps) * 100
        t = (self.kept - 1) / self.fps if np.isfinite(self.fps) else np.full(self.N, np.nan)
        g = lambda v: 'NaN' if not np.isfinite(v) else '%.6g' % v
        try:
            with open(path, 'w', newline='') as fh:
                fh.write('%% SciPlayer traces of %s; mean intensity (a.u., luminance for colour) and relative change (%%) '
                         'against baseline frames %s\n' % (self.file, self.base_str))
                for r in self.rois:
                    fh.write('%% %s outline x: [%s]; y: [%s]\n' % (r['name'], ' '.join(g(round(v * 10) / 10) for v in r['xy'][:, 0]),
                                                                    ' '.join(g(round(v * 10) / 10) for v in r['xy'][:, 1])))
                fh.write(','.join(['frame', 'recorded_frame', 'time_s'] + [n + '_mean' for n in names] +
                                  [n + '_dff_pct' for n in names]) + '\n')
                for k in range(self.N):
                    fh.write('%d,%d,%s,%s,%s\n' % (k + 1, self.kept[k], g(t[k]), ','.join(g(v) for v in Y[k]),
                                                   ','.join(g(v) for v in R[k])))
        except OSError as e:
            self.msg(tr('Cannot write %s:\n%s') % (path, e))
            return False
        self.info.setText(tr('Traces written: %s') % path)
        QtCore.QTimer.singleShot(4000, self._info_text)
        return True

    def save_view(self, path):
        if not path:
            nm = 'sciplayer_view.png'
            if self.loaded:
                nm = '%s_frame%05d.png' % (os.path.splitext(self.file)[0], self.cur + 1)
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, tr('Save the view'), nm, 'PNG (*.png)')
            if not path:
                return False
        QtWidgets.QApplication.processEvents()
        return self.centralWidget().grab().save(path, 'PNG')

    def closeEvent(self, ev):
        self.stop()
        self.scanner.cancel()
        self._audio_stop()
        if self.src is not None:
            self.src.close()
        super().closeEvent(ev)


# =============================================================================
# start
# =============================================================================
def _log_path():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'sciplayer_error.log')


def _excepthook(t, v, tb):
    text = ''.join(traceback.format_exception(t, v, tb))
    try:
        with open(_log_path(), 'a', encoding='utf-8') as fh:
            fh.write('\n==== %s\n%s' % (time.strftime('%Y-%m-%d %H:%M:%S'), text))
    except Exception:
        pass
    if sys.stderr:
        sys.stderr.write(text)
    if os.environ.get('SCIPLAYER_TEST'):
        return
    try:
        QtWidgets.QMessageBox.critical(None, APP_NAME, tr('Something went wrong:\n\n%s\n\n(details in %s)') % (v, _log_path()))
    except Exception:
        pass


def icon_path(png=False):
    names = ('sciplayer_256.png', 'sciplayer.ico') if png else ('sciplayer.ico', 'sciplayer_256.png')
    for nm in names:
        for d in (HERE, os.path.join(HERE, '..'), os.path.join(HERE, '..', 'assets')):
            p = os.path.join(d, nm)
            if os.path.isfile(p):
                return p
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    sys.excepthook = _excepthook
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SciPlayer.SciPlayer')
        except Exception:
            pass
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle('Fusion')
    f = app.font()
    f.setFamilies(['Segoe UI Variable Text', 'Segoe UI', 'Inter', 'Helvetica Neue', 'Arial'])
    f.setPointSizeF(9.5)
    app.setFont(f)
    ic = icon_path()
    if ic:
        app.setWindowIcon(QtGui.QIcon(ic))
    w = Player()
    scr = app.primaryScreen().availableGeometry()
    w.resize(min(1500, int(0.92 * scr.width())), min(960, int(0.88 * scr.height())))
    w.move(scr.center() - w.rect().center())
    w.show()
    w.restore_split()
    w._focus_frame()                                      # arrows and Space work at once
    files = [a for a in argv if not a.startswith('-')]
    if files:
        QtCore.QTimer.singleShot(50, lambda: w.load_file(os.path.abspath(files[0])))
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
