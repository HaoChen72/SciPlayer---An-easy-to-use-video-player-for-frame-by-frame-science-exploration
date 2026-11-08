# SciPlayer 0.2.0

A video player for scientific recordings, in MATLAB. Open a recording, scrub
and play it like any video, and, when you want, see the relative change of
every pixel against a baseline you choose and follow the mean intensity of the
whole frame and of your own regions over time.

```matlab
sciplayer                     % opens the player; "Load video..." at the top
sciplayer('D:\data\run1.avi') % opens a file at once
```

Base MATLAB only, no toolbox. Also runs under Octave (video files need its
`video` package there).

## Files it opens

* **Videos** – anything `VideoReader` reads (AVI, MP4, MOV, MJ2, …). The
  video's own frame rate sets the time axis. A grey video saved as RGB
  (channels equal, within what a lossy codec leaves) is stored as grey.
* **Multi-page TIFF stacks** – no frame rate is assumed; type it in
  *Frame rate (Hz)* to get a time axis in seconds, or leave it empty to work
  in frame numbers.

The frame rate is typed in one place, *Frame rate (Hz)* at the top. It sets
the time axis and the playback speed: *Play* runs the recording in real time
(with every n-th frame kept, rate / n frames per second; 10 frames per second
while no rate is known).
* **MAT-files** – an `[H x W x frames]` or `[H x W x 3 x frames]` array (the
  player asks which one if there are several). A scalar `fps`, `frame_rate`,
  `FrameRate` or `fs` saved beside it is used as the frame rate. Version 7.3
  files are read frame by frame, so only the frames kept are read.

## Size check

The whole recording is held in memory, so that any frame shows at once while
scrubbing. Before reading, its size is estimated (height × width × colour
channels × frames × bytes per value). Up to **4 GB** nothing is asked. Above
it, the player asks how to reduce it, with a suggestion that fits: spatial
binning (2 × 2, 4 × 4 … average), every n-th frame, a frame range, and colour
to grey. If the result is still above the limit you can load it anyway, change
the settings or cancel (the recording already open stays). The limit is an
option: `sciplayer(file, struct('limit_gb', 8))`.

## The window

* **Title** – `frame i / N`, the time in s when the frame rate is known, and
  the recorded frame number when the recording was reduced.
* **Frame** – most of the window. *View: Original frames* shows only the
  recording as it is, so any video can be played. *View: Relative change*
  shows, beside it, `(frame − F0) / F0` in %, with F0 the mean of the
  **baseline frames** you type (`1-10`, or several ranges: `1-10, 200-210`).
* **Transport** – the slider scrubs (live while dragging), ◀ / ▶ step one
  frame, the frame box jumps, *Play* / *Pause* in real time at the frame
  rate, *loop*. On the same row, active in the relative view: *dF/F range*
  (`auto`, one number for a symmetric range, or two: low high) and the
  *Colour map* (five).
* **Keyboard and mouse** – left / right arrow: one frame (Shift: ten);
  mouse wheel: scroll through frames; Space: play / pause; Home / End.
* **Traces** – one row per signal, each with its own vertical axis, the
  current frame marked: the **whole frame's mean intensity** (how the
  experiment went), then one row per **ROI**, drawn with the mouse on the
  frame (either panel in the relative view). *ROI: rectangle*: press the left
  button, drag to the opposite corner, release. *ROI: freehand*: press, trace
  the outline (a line back to the start shows how it will close), release to
  close it. The title says what to do while drawing; Esc or a right-click
  cancels, and a drag too small to hold a pixel asks to draw again.
  *Remove ROI…* removes any. In the relative view every row is the
  relative change of its mean against the same baseline, which is shaded.
  Click any row to jump to that time. Colour frames are measured as luminance
  (0.299 R + 0.587 G + 0.114 B).
* **Export traces (CSV)** – frame, recorded frame, time, every row's mean and
  its relative change; the ROI outlines in the header.
* **Save view (PNG)** – the window as it is.

## Scripting

Every control has a command form, useful in scripts and for testing:

```matlab
fig = sciplayer('run1.tif');
sciplayer(fig, 'fps', 20);
sciplayer(fig, 'view', 'relative');  sciplayer(fig, 'baseline', '1-50');
sciplayer(fig, 'add_roi', 'rect', [20 20; 50 50]);
sciplayer(fig, 'draw', 'freehand', path);   % replays a mouse path ([n x 2] px)
sciplayer(fig, 'goto', 130);  sciplayer(fig, 'save_view', 'frame130.png');
sciplayer(fig, 'export', 'run1_traces.csv');
S = sciplayer(fig, 'state');          % everything but the frames
```

Commands: `load`, `goto`, `step`, `view`, `baseline`, `range`, `colormap`,
`fps`, `add_roi` (`rect` or `freehand`; `poly` is accepted too), `draw`,
`remove_roi`, `export`, `save_view`, `play`, `state`,
`answers` (answers for the next dialogs, in order).

## Test

`sciplayer_selftest` writes small synthetic recordings (TIFF, MAT, grey and
colour AVI) to a temporary folder, with a planted 10 % global rise, a local
response and a moving blob, and checks 16 things: what is read, the traces
against the truth, the relative-change image, ROIs, the export, playback,
grey-as-RGB video, colour video and the size check. (`sciplayer_selftest.m` is
not part of this repository yet.)

## Version 0.2.0 (2026-10-30)

ROIs are drawn by dragging: rectangle (press, drag to the opposite corner,
release) and freehand (press, trace, release to close), on either panel, with
the instructions in the title, Esc / right-click to cancel; the polygon by
clicked vertices is gone. One frame rate, at the top, for the time axis and
the playback speed (the separate playback *fps* box is gone); *dF/F range* and
*Colour map* moved to the transport row, active in the relative view. ROI
masks are computed within the ROI's bounding box (fast for long outlines).

## Version 0.1.0 (2026-10-30)

First version: load (video, TIFF, MAT) with the size check and reduction,
original and relative-change views, scrubbing, stepping, playback, keyboard
and wheel, whole-frame and ROI traces with their own axes, CSV and PNG export.
