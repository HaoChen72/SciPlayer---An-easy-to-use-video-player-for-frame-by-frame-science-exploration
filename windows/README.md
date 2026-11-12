# SciPlayer for Windows 1.4.1

The Windows 11 (64-bit) edition of SciPlayer: the same window and behaviour as
`sciplayer.m` 0.2.0, as an installable program that needs nothing else on the
computer (no MATLAB, no Python). It ships its own Python 3.12, Qt 6 and FFmpeg.

## Look and languages

* **Flat, minimal design** in the colours of the logo. Dark and light themes:
  the first start follows Windows' own setting, and the sun / moon button
  switches between them. The choice is remembered.
* **English, 简体中文, 繁體中文**: the globe button switches the whole window at
  once, including labels, buttons, tooltips, messages, dialogs and the trace
  axes. The installer asks for the language first, and SciPlayer then starts
  in that language. With no choice made, it follows Windows' language (Hong
  Kong, Macau and Taiwan get traditional characters). Chinese text uses
  Microsoft YaHei (简体) or Microsoft JhengHei (繁體).
* **Colour or grey.** Grey recordings stored in a colour format (R = G = B, as
  many cameras and conversions write them) are kept as one grey channel, which
  takes a third of the memory. Whether a recording is grey is decided from
  frames spread over the whole recording (6 for videos, 9 for TIFF stacks and
  MAT-files), not from the first one alone. A colour video that starts black or
  grey (a fade-in, a dark first frame, a title) stays in colour. The check adds
  at most about 0.35 s to opening. MJPEG frames are looked at in 1/8 size, which
  costs almost nothing.
* CSV exports keep English column names, so scripts that read them do not
  depend on the language.

## Install

Run `dist\SciPlayer-1.4.1-Setup-x64.exe`. It installs over an earlier version; there is no need to
uninstall that first.

* The installer first asks for its language, every time it runs, with the
  last choice preselected.
* **Install for anyone using this computer** (asks for administrator rights) installs to
  `C:\Program Files\SciPlayer`. **Install just for me** needs no administrator rights
  and installs to `%LOCALAPPDATA%\Programs\SciPlayer`.
* It adds SciPlayer to the Start menu (and optionally the desktop), and to
  *Apps > Installed apps* for uninstalling.
* SciPlayer is registered for video files (.avi .mp4 .m4v .mov .mkv .wmv .mpg
  .mpeg .mj2 .mjpg .mjpeg .webm .flv .ogv .3gp .mts .m2ts .vob), TIFF stacks
  (.tif .tiff) and MAT-files (.mat). It appears under *Open with* for all of
  them. Extensions that no program opens yet open with SciPlayer on a
  double-click (except .mat, which stays MATLAB's).
* Windows 11 does not let an installer take over the default app for a
  format that already has one. To make SciPlayer the default, tick the last box
  on the installer's final page. It opens *Settings > Default apps >
  SciPlayer*, where one click per format does it. Alternatively, right-click a
  video, choose *Open with > Choose another app*, pick SciPlayer and select
  *Always*.
* The installer is not code-signed, so Windows SmartScreen may show "Windows
  protected your PC" on first run. Click *More info* and then *Run anyway*.
  Signing it with a code-signing certificate (for example your institute's)
  removes this warning.
* Silent installs: `/S /AllUsers` or `/S /CurrentUser`. Silent uninstall:
  `"Uninstall SciPlayer.exe" /S`.

## Use

As in MATLAB:

* Open a recording with *Load video...*, by dropping a file on the window, by
  double-clicking it in Explorer, or with `SciPlayer.exe <file>`.
* Scrub with the slider. Arrow keys step one frame (Shift: 10). The mouse wheel
  scrolls through frames. Space plays and pauses. Home and End jump to the first
  and last frame.
* There is one frame rate, at the top. It sets the time axis, and Play runs in
  real time at that rate.
* The relative change (dF/F) uses the baseline frames you type. Its colour
  range and colour map are next to the transport controls.
* ROIs: for a rectangle, drag from corner to corner. For a freehand ROI, trace
  the outline and release to close it. Esc or a right-click cancels.
* Export traces (CSV) and Save view (PNG) work as in MATLAB.
* The edge between the frame and the transport row / traces can be dragged up
  or down. Its position is remembered for the next start.
* **Zoom**: Ctrl + mouse wheel zooms in and out at the point under the mouse,
  in both panels of the relative view together. When zoomed in, drag the frame
  to move around. Double-click or Ctrl+0 shows the whole frame again. The
  wheel alone still scrolls through frames, and ROIs are drawn as usual.
* **Brightness and contrast** of the original frame: two sliders in the
  toolbar. They change only how the original is drawn, that is its display
  range: contrast narrows or widens the range (up to 4 × either way) and
  brightness moves it. The values themselves, the relative change (dF/F),
  traces, ROI means and exports stay exactly as they are. Double-click a slider,
  or click Reset, to go back to 0. Each recording opens at 0.
* Frames are drawn at the resolution they are shown at. A 4000 × 3000 frame
  in a 700-pixel panel is drawn as the mean of 5 × 5 pixel blocks, because the
  screen cannot show more. Zooming in, or a larger window, draws it finer, down
  to every pixel, and then only the part in view is drawn. For the relative
  change, the blocks are exact means (no rounding), so each block shows the
  dF/F of its mean. Traces, ROI means and exports always use every pixel. This
  keeps the dF/F view as smooth as the original: for a 4000 × 3000 recording,
  about 20 ms per frame instead of 60.
* While a video plays, two threads work a few frames ahead of the playback
  clock: one reads (decodes) the coming frames, the other prepares them for
  drawing (block means, dF/F). The window only draws the frame that is due, so
  reading, preparing and drawing overlap, as in a video player. When a computer
  cannot keep the pace, frames are skipped and the video keeps its time. A
  frame shown is always the exact one for its time.

### Large recordings, and smooth dragging

SciPlayer's core function is smooth slider dragging, where every frame updates
fluidly, together with fast frame-by-frame stepping at full resolution. It
must hold for recordings of any size, and no build may trade it away.

**Every video opens at once.** Its first frame shows, its frame rate is filled
in, and Play, stepping, dragging and ROIs work straight away, as in an ordinary
player. Smooth scrubbing is prepared in the background meanwhile. A strip under
the toolbar shows how far that is and about how long it still takes.
Preparing goes on while the video plays, and playing helps it. Every frame that
playback (or stepping) decodes is handed to the background pass, which prepares
it at once (traces, scrubbing copy, memory) and does not read it again. The
pass reads on from where it is meanwhile. Only while playback is dropping
frames, because the computer or the disk cannot do both at full speed, does the
pass stop its own reading for a moment, and it still prepares the played
frames. Playback follows the clock: if a frame comes too slowly from disk, it
is skipped instead of slowing the video down. This applies to videos, TIFF
stacks and v7.3 MAT-files. v5 MAT-files and single-array TIFFs can only be read
whole, so they are read first, with a progress bar.

* **Up to 2 GB decoded** (or 30 % of the free memory, if that is less): the
  background pass reads the whole recording into memory, at full resolution.
  When it is done, SciPlayer moves to it, as in 1.0.0: every frame is exact
  and instant, while dragging too. Frames already read come from memory
  before that.
* **Larger** (for example a 78 MB MP4 that decodes to 35 GB): it stays on
  disk and is handled the way video editors handle long-GOP footage, with a
  proxy.
  * In the background, one pass decodes every frame once. It computes the
    traces and builds the *scrubbing copy*: every frame scaled to about the
    size it is shown at (1280 px wide at most), JPEG quality 90, in memory.
    For a 4-minute 1080p video that is about 0.9 GB.
  * The video opens and can be used at once. A strip under the toolbar shows
    "Preparing smooth scrubbing NN %", a progress bar and the time left
    ("about 40 s left"). When the pass is done it says "Smooth scrubbing
    ready" and disappears.
  * While you drag, the slider shows the scrubbing copy of every frame it
    passes, in about 10 ms per frame. That is as smooth as a recording in
    memory, and it is never limited to key frames.
  * As soon as the slider rests (90 ms), and on release, the exact
    full-resolution frame is decoded in the background and replaces the copy.
    The title shows a small dot "·" until it arrives. Clicking a trace or
    stepping back with the arrows works the same way: that frame appears at
    once, then the exact one.
  * Stepping forward, scrolling forward and Play decode the next exact frame
    directly, in a few ms.
  * Traces, dF/F values, ROI means and exports always come from the exact
    frames. The scrubbing copy is only for the picture while you move, and it
    differs from the exact frame by about 2 grey levels on average.
  * Until the background pass reaches a part of the video, dragging there
    shows the nearest key frame.
* **Long-GOP videos larger than 150 MB** (H.264, HEVC, … at a constant frame
  rate): their frames are found by time at once, the way ordinary players find
  them. Finding the key frames means reading the whole file, so that runs in
  the background for a few seconds.
* **Uncompressed and intra-only files** (raw AVI, MJPEG, ProRes, DNxHD, HuffYUV,
  UT Video and other intra-only codecs) open at once, whatever their size: every frame is
  its own key frame, so SciPlayer computes where each frame is instead of
  reading the whole file first, and checks it on the first and last frames.
  An 18.6 GB raw AVI (2479 × 1096, 2277 frames) opens in about 0.1 s, any
  frame shows at full resolution in about 20 ms, and its scrubbing copy is
  ready after about a minute.
* Memory for testvid.mp4 (1080p, 5765 frames): about 2.3 GB in all, instead
  of 35 GB.

### Sound

The sound of a video plays with it whenever the video runs at its own frame
rate. The picture follows the sound's clock, so the two stay in step. Untick
*sound* to play the video without it. With another frame rate typed in, there
is no sound, because it would not match the picture.

Errors are logged in `%LOCALAPPDATA%\SciPlayer\sciplayer_error.log`.

## Files

| | |
|---|---|
| `app\sciplayer.py` | the window (PySide6 + pyqtgraph) |
| `app\sciplayer_io.py` | reading (FFmpeg via PyAV, tifffile, scipy / h5py for MAT-files), ROI masks, traces |
| `app\sciplayer_source.py` | frames in memory or decoded from disk on demand (index, key frames, cache), background trace pass |
| `app\sciplayer_audio.py` | the sound track, decoded while it plays, through PortAudio (sounddevice) |
| `app\sciplayer_theme.py` | the dark and light themes: colours, style sheet, vector icons |
| `app\sciplayer_i18n.py` | the languages: English, 简体中文, 繁體中文 |
| `launcher\` | `SciPlayer.exe`: starts the private Python with the program (C, with icon, version and manifest) |
| `installer\sciplayer.nsi` | the installer (NSIS) |
| `assets\` | the logo (`logo_src.png`) as `.ico` (16 to 256 px), PNG and the installer images |
| `build_windows.sh` | builds everything on Linux (no Windows needed) |
| `test\` | `make_test_data.py`, `make_stream_data.py`, `make_raw.py`, `make_big_mjpeg.py` and `make_colour_late.py` write synthetic recordings with a known truth (the frame number is written into every frame); `selftest.py` checks 106 things |
| `LICENSES.txt` | the licences of SciPlayer and of the components the installer contains |

## Build

On Linux, with MinGW-w64 and NSIS installed, and a Python virtual environment
with `py-rattler` and `pefile` (by default `windows/.venv`, or set `VENV`):

```
python3 -m venv .venv && .venv/bin/pip install py-rattler pefile
./build_windows.sh            # -> dist/SciPlayer-<version>-Setup-x64.exe
```

The version comes from `APP_VERSION` in `app/sciplayer.py`. With Wine
installed, the build also byte-compiles the program with the Windows Python.

The private Python comes from conda-forge, with PyAV on conda-forge's LGPL build
of FFmpeg. The PyPI wheel of PyAV is not used: it includes x264 and x265, which
are GPL, and a GPL part would oblige the whole program to be GPL. The build
lists the licence of every conda package in `LICENSES.txt` and stops if any of
them is GPL only.

It also checks every DLL and Python module of the installation against the DLL
Windows would give it, and stops if any function it imports is missing there.
Tests under Wine cannot show such a mismatch, because Wine supplies its own C++
runtime and ICU. Version 1.4.0 did not start on Windows for exactly this reason:
it shipped conda-forge's ICU as `icuuc.dll`, the name of Windows' own ICU, which
Qt imports from System32. `Library\bin` is searched first, so Qt got the wrong
`icuuc.dll` and did not load.

This build was tested under Wine 9 (Windows 11 mode). The tests covered the
install for all users and for the current user, the registry entries,
double-click opening, a real mouse drag for both ROI shapes, all 117
self-tests and a clean uninstall. The sound was checked with a stand-in
device, because the test machine has no sound card. Wine 9 cannot run some newer libraries, so the
versions are pinned to ones that run there: numpy 1.26, Qt 6.10 and h5py 3.12.

## Licence

SciPlayer is free for non-commercial use under the PolyForm Noncommercial
License 1.0.0 (`LICENSE.md` in the repository, shown by the installer and
installed as `LICENSE.txt`). The components the installer contains keep their
own licences, listed in `LICENSES.txt`.
