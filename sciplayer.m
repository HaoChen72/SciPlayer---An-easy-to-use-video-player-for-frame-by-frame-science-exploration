function varargout = sciplayer(varargin)
%SCIPLAYER  A video player for scientific recordings: scrub, play, relative change and ROI traces.
%
%   SCIPLAYER opens the player; "Load video..." at the top reads a video
%   (any format VideoReader can open: AVI, MP4, MOV, MJ2, ...), a multi-page
%   TIFF stack, or a MAT-file holding an [H x W x frames] (or [H x W x 3 x
%   frames]) array. The whole recording is read into memory first, so that
%   every frame can be shown at once while scrubbing. Its size is estimated
%   beforehand: above OPTS.limit_gb (4 GB) the player asks for a reduction
%   (spatial binning, every n-th frame, a frame range, colour to grey)
%   before anything is read; below it nothing is asked.
%
%   The window works like a video player: the frame fills most of it, the
%   slider scrubs (live while dragging), the arrow buttons and the keyboard
%   step one frame (Shift: ten), the mouse wheel scrolls through frames,
%   Space plays and pauses, and the title reads "frame i / N".
%
%   View "Original frames" shows the frames as recorded, nothing else - any
%   video can be played. View "Relative change" shows, beside the original,
%   (frame - F0) / F0 in %, with F0 the mean of the BASELINE frames you type
%   (e.g. 1-10, or 1-10, 200-210). Its colour range and colour map are set
%   beside the transport controls, under the frame.
%
%   The frame rate (Hz) is typed in one place, at the top: it sets the time
%   axis, and Play runs the recording in real time at that rate (10 frames/s
%   while no rate is known).
%
%   Below the frame, the mean intensity of the whole frame over time - how
%   the experiment went - one row per signal, each with its own vertical
%   axis. "ROI: rectangle" (press on the frame and drag to the opposite
%   corner) or "ROI: freehand" (press, trace the outline, release to close)
%   adds a row with that region's mean. In the relative view every row is the relative
%   change of its mean against the same baseline, with the baseline shaded.
%   Click a row to jump to that time. "Export traces" writes all rows as a
%   CSV; "Save view" writes the window as a PNG.
%
%   SCIPLAYER(FILE) opens FILE at once. SCIPLAYER(FILE, OPTS) sets options:
%     .limit_gb      above this estimated size, ask for a reduction (4)
%     .visible       'on' / 'off' (for scripted use)
%   FIG = SCIPLAYER(...) returns the window.
%
%   Scripting (and testing): SCIPLAYER(FIG, COMMAND, ...) with COMMAND
%     'load', file            'goto', k              'step', n
%     'view', 'original' | 'relative'                'baseline', '1-10'
%     'range', 'auto' | '10' | '-5 20'               'colormap', name
%     'fps', hz               'add_roi', 'rect' | 'freehand', XY ([n x 2])
%     'draw', 'rect' | 'freehand', PATH  (the mouse path, [n x 2] frame pixels:
%                             press at the first point, release at the last)
%     'remove_roi', k         'export', csv_file     'save_view', png_file
%     'play', n_frames        'state' (returns the state, without the data)
%     'answers', {a1, a2, ...} (answers for the next dialogs, in order)
%
%   Base MATLAB only (no toolbox). Runs under Octave as well (video files
%   need Octave's video package there).
%
%   SciPlayer 0.2.0

if nargin >= 2 && local_is_fig(varargin{1}) && ischar(varargin{2})
    out = local_command(varargin{1}, lower(varargin{2}), varargin(3:end));
    if nargout, varargout{1} = out; end
    return;
end
file = ''; opts = struct();
if nargin >= 1 && ischar(varargin{1}), file = varargin{1}; end
if nargin >= 2 && isstruct(varargin{2}), opts = varargin{2}; end
d = struct('limit_gb', 4, 'visible', 'on');
f = fieldnames(d);
for i = 1:numel(f), if ~isfield(opts, f{i}) || isempty(opts.(f{i})), opts.(f{i}) = d.(f{i}); end, end
fig = local_build(opts);
if ~isempty(file), local_load(fig, file); end
if nargout, varargout{1} = fig; end
end

% =========================================================================
% the window
% =========================================================================
function fig = local_build(opts)
ss = get(0, 'ScreenSize');
try, mp = get(0, 'MonitorPositions'); if ~isempty(mp), ss = mp(1, :); end, catch, end
if numel(ss) < 4 || ss(3) < 400, ss = [1 1 1600 1000]; end
w = min(1500, round(0.92 * ss(3))); hgt = min(960, round(0.86 * ss(4)));
pos = [ss(1) + round((ss(3) - w) / 2), ss(2) + round((ss(4) - hgt) / 2), w, hgt];
fig = figure('Name', 'SciPlayer', 'NumberTitle', 'off', 'Color', 'w', 'Position', pos, 'MenuBar', 'none', ...
    'ToolBar', 'figure', 'Visible', opts.visible, 'Tag', 'sciplayer');
set(fig, 'WindowKeyPressFcn', @(f_, e_) local_key(fig, e_), 'CloseRequestFcn', @(f_, e_) local_close(fig));
try, set(fig, 'WindowScrollWheelFcn', @(f_, e_) local_wheel(fig, e_)); catch, end
bg = 'w';
txt = @(p, s, varargin) uicontrol(fig, 'Style', 'text', 'Units', 'normalized', 'Position', p, 'String', s, ...
    'BackgroundColor', bg, 'HorizontalAlignment', 'left', varargin{:});
btn = @(p, s, cb, varargin) uicontrol(fig, 'Style', 'pushbutton', 'Units', 'normalized', 'Position', p, 'String', s, ...
    'Callback', cb, varargin{:});
h = struct();
% ---- row 1: file -------------------------------------------------------------
h.load = btn([0.008 0.955 0.085 0.036], 'Load video...', @(s_, e_) local_load(fig, ''), 'FontWeight', 'bold', ...
    'BackgroundColor', [0.80 0.90 1.00], 'TooltipString', 'a video file, a multi-page TIFF or a MAT-file with an [H x W x frames] array');
h.info = txt([0.100 0.951 0.460 0.034], 'No video loaded - press "Load video..."', 'FontSize', 9);
txt([0.562 0.951 0.103 0.034], 'Frame rate (Hz):', 'HorizontalAlignment', 'right');
h.fps = uicontrol(fig, 'Style', 'edit', 'Units', 'normalized', 'Position', [0.667 0.955 0.053 0.036], 'String', '', ...
    'Callback', @(s_, e_) local_set_fps(fig, str2double(get(s_, 'String'))), ...
    'TooltipString', ['the recording''s frame rate: sets the time axis and the playback speed (Play runs in real time); ' ...
    'empty = frame numbers, playback at 10 frames/s (the video''s own rate is filled in when it has one)']);
h.export = btn([0.735 0.955 0.125 0.036], 'Export traces (CSV)', @(s_, e_) local_export(fig, ''));
h.save = btn([0.866 0.955 0.126 0.036], 'Save view (PNG)', @(s_, e_) local_save_view(fig, ''));
% ---- row 2: view, baseline, ROIs ---------------------------------------------
txt([0.008 0.909 0.034 0.034], 'View:');
h.view = uicontrol(fig, 'Style', 'popupmenu', 'Units', 'normalized', 'Position', [0.042 0.913 0.160 0.036], ...
    'String', {'Original frames', 'Relative change (dF/F)'}, 'Value', 1, 'TooltipString', 'Relative change: (frame - F0) / F0 beside the original frame', ...
    'Callback', @(s_, e_) local_set_view(fig, local_iff(get(s_, 'Value') == 2, 'relative', 'original')));
txt([0.204 0.909 0.096 0.034], 'Baseline frames:', 'HorizontalAlignment', 'right');
h.base = uicontrol(fig, 'Style', 'edit', 'Units', 'normalized', 'Position', [0.302 0.913 0.068 0.036], 'String', '1-10', ...
    'Callback', @(s_, e_) local_set_baseline(fig, get(s_, 'String')), ...
    'TooltipString', 'frames of the player (1..N) whose mean is F0, e.g. 1-10  or  1-10, 200-210');
h.roi_rect = btn([0.696 0.913 0.098 0.036], 'ROI: rectangle', @(s_, e_) local_add_roi(fig, 'rect', []), ...
    'TooltipString', 'press the left button on the frame, drag to the opposite corner, release (Esc: cancel)');
h.roi_free = btn([0.797 0.913 0.098 0.036], 'ROI: freehand', @(s_, e_) local_add_roi(fig, 'freehand', []), ...
    'TooltipString', 'press the left button on the frame, trace the outline, release to close it (Esc: cancel)');
h.roi_del = btn([0.898 0.913 0.094 0.036], 'Remove ROI...', @(s_, e_) local_remove_roi(fig, []));
% ---- title -------------------------------------------------------------------------
h.title = uicontrol(fig, 'Style', 'text', 'Units', 'normalized', 'Position', [0.05 0.868 0.90 0.036], 'String', 'SciPlayer', ...
    'BackgroundColor', bg, 'FontSize', 14, 'FontWeight', 'bold', 'HorizontalAlignment', 'center');
% ---- the frame (one panel, or original | relative change) ---------------------------
h.ax1 = axes('Parent', fig, 'Position', [0.010 0.365 0.980 0.495]);
h.img1 = image(h.ax1, zeros(2, 2), 'CDataMapping', 'scaled', 'Visible', 'off'); axis(h.ax1, 'image'); axis(h.ax1, 'off'); colormap(h.ax1, gray(256)); hold(h.ax1, 'on');
h.hint = text(h.ax1, 1.5, 1.5, 'Load a video to start', 'HorizontalAlignment', 'center', 'FontSize', 14, 'Color', [0.55 0.55 0.55]);
h.ax2 = axes('Parent', fig, 'Position', [0.505 0.365 0.440 0.495], 'Visible', 'off');
h.img2 = image(h.ax2, nan(2, 2), 'CDataMapping', 'scaled', 'Visible', 'off'); axis(h.ax2, 'image'); axis(h.ax2, 'off'); hold(h.ax2, 'on');
h.cb2 = [];
% ---- transport ---------------------------------------------------------------------
h.prev = btn([0.010 0.315 0.030 0.038], local_arrow(-1), @(s_, e_) local_step(fig, -1), 'TooltipString', 'previous frame (left arrow; Shift: 10 frames)');
h.slider = uicontrol(fig, 'Style', 'slider', 'Units', 'normalized', 'Position', [0.044 0.318 0.395 0.032], 'Min', 1, 'Max', 2, 'Value', 1, ...
    'SliderStep', [0.5 0.5], 'Callback', @(s_, e_) local_goto(fig, round(get(s_, 'Value'))), 'Enable', 'off');
try, h.listener = addlistener(h.slider, 'ContinuousValueChange', @(s_, e_) local_goto(fig, round(get(s_, 'Value')))); catch, h.listener = []; end
h.next = btn([0.443 0.315 0.030 0.038], local_arrow(1), @(s_, e_) local_step(fig, 1), 'TooltipString', 'next frame (right arrow; Shift: 10 frames)');
txt([0.476 0.312 0.038 0.034], 'Frame:', 'HorizontalAlignment', 'right');
h.frame = uicontrol(fig, 'Style', 'edit', 'Units', 'normalized', 'Position', [0.516 0.315 0.052 0.038], 'String', '', ...
    'Callback', @(s_, e_) local_goto(fig, round(str2double(get(s_, 'String')))), 'TooltipString', 'type a frame number');
h.play = uicontrol(fig, 'Style', 'togglebutton', 'Units', 'normalized', 'Position', [0.574 0.315 0.058 0.038], 'String', 'Play', ...
    'FontWeight', 'bold', 'Callback', @(s_, e_) local_play(fig, Inf), 'TooltipString', 'play / pause (Space), in real time at the frame rate set at the top');
h.loop = uicontrol(fig, 'Style', 'checkbox', 'Units', 'normalized', 'Position', [0.637 0.318 0.042 0.032], 'String', 'loop', ...
    'BackgroundColor', bg, 'Value', 1);
% the relative-change display (active in the relative view)
h.range_lbl = txt([0.682 0.312 0.088 0.034], 'dF/F range (%):', 'HorizontalAlignment', 'right');
h.range = uicontrol(fig, 'Style', 'edit', 'Units', 'normalized', 'Position', [0.772 0.315 0.045 0.038], 'String', 'auto', ...
    'Callback', @(s_, e_) local_set_range(fig, get(s_, 'String')), 'TooltipString', 'colour range of the relative change: auto, one number (symmetric), or two numbers (low high)');
h.cmap_lbl = txt([0.820 0.312 0.068 0.034], 'Colour map:', 'HorizontalAlignment', 'right');
h.cmap = uicontrol(fig, 'Style', 'popupmenu', 'Units', 'normalized', 'Position', [0.890 0.317 0.101 0.036], ...
    'String', local_cmap_names(), 'Value', 1, 'TooltipString', 'colour map of the relative change', ...
    'Callback', @(s_, e_) local_set_cmap(fig, local_pick(get(s_, 'String'), get(s_, 'Value'))));
% ---- traces ------------------------------------------------------------------------
h.trace_note = txt([0.010 0.004 0.98 0.030], ['Arrows: one frame (Shift: 10);   mouse wheel: scroll;   Space: play / pause;   ' ...
    'Home / End: first / last frame;   click a trace to jump there'], 'FontSize', 8, ...
    'ForegroundColor', [0.35 0.35 0.35]);
h.trace_ax = []; h.cursor = []; h.roi_lines = {};
S = struct('h', h, 'opts', opts, 'loaded', false, 'cur', 1, 'N', 0, 'view', 'original', 'rois', struct('name', {}, 'xy', {}, 'mask', {}, ...
    'color', {}, 'trace', {}), 'roi_count', 0, 'answers', {{}}, 'cmap', 'blue-white-red', 'range_str', 'auto', 'base_str', '1-10');
setappdata(fig, 'S', S);
local_enable(fig, 'off');
end

% =========================================================================
% loading
% =========================================================================
function local_load(fig, file)
S = getappdata(fig, 'S');
if isempty(file)
    [fn, pth] = uigetfile({'*.avi;*.mp4;*.mov;*.mj2;*.m4v;*.mpg;*.wmv;*.tif;*.tiff;*.mat', 'Videos, TIFF stacks, MAT-files'; ...
        '*.*', 'All files'}, 'SciPlayer: choose a recording');
    if isequal(fn, 0), return; end
    file = fullfile(pth, fn);
end
if ~exist(file, 'file'), local_msg(fig, sprintf('File not found:\n%s', file)); return; end
local_stop(fig);
try
    info = local_probe(fig, file);
catch e
    local_msg(fig, sprintf('Could not open %s:\n%s', file, e.message)); return;
end
if isempty(info), return; end
p = struct('bin', 1, 'step', 1, 'first', 1, 'last', info.N, 'gray', info.Cs == 1);
lim = S.opts.limit_gb * 1e9;
if local_bytes(info, p) > lim
    p = local_reduce_dialog(fig, info, p, lim);
    if isempty(p), return; end
end
S = getappdata(fig, 'S');
set(S.h.info, 'String', sprintf('Reading %s ...', local_short(file))); drawnow;
[data, mtr, kept] = local_read(info, p);
if isempty(kept), local_msg(fig, 'No frame could be read.'); return; end
S = getappdata(fig, 'S');
local_clear_rois(fig); S = getappdata(fig, 'S');
S.data = data; S.mean_trace = mtr(:).'; S.kept = kept(:).'; S.N = numel(kept);
S.is_rgb = ndims(data) == 4; S.H = size(data, 1); S.W = size(data, 2);
S.file = file; S.info = info; S.p = p; S.loaded = true; S.cur = 1; S.fps = info.fps;
S.reduced = p.bin > 1 || p.step > 1 || p.first > 1 || p.last < info.N || (info.Cs == 3 && p.gray);
S.base_str = sprintf('1-%d', min(10, S.N)); S.base = []; S.F0 = [];
S.clim_raw = local_raw_clim(S);
setappdata(fig, 'S', S);
set(S.h.base, 'String', S.base_str); set(S.h.fps, 'String', local_iff(isfinite(S.fps), sprintf('%.4g', S.fps), ''));
set(S.h.slider, 'Min', 1, 'Max', max(2, S.N), 'Value', 1, 'SliderStep', [1, 10] / max(1, S.N - 1));
cls = class(data); mb = numel(data) * local_bytes_per(cls) / 1e6;
red = ''; if S.reduced, red = sprintf(';   reduced: %s', local_reduction_text(info, p)); end
set(S.h.info, 'String', sprintf('%s:   %d x %d px%s, %d frames%s, %s;   %s in memory%s', local_short(file), S.W, S.H, ...
    local_iff(S.is_rgb, ' colour', ''), S.N, local_iff(isfinite(S.fps), sprintf(' at %.4g Hz', S.fps), ''), cls, local_size_text(mb), red));
local_enable(fig, 'on');
set(S.h.slider, 'Enable', local_iff(S.N > 1, 'on', 'off')); set(S.h.img1, 'Visible', 'on'); if ishghandle(S.h.hint), delete(S.h.hint); end
local_layout(fig); local_set_baseline(fig, S.base_str);
local_traces(fig); local_show(fig);
end

function info = local_probe(fig, file)
% what the file holds, without reading it all
[~, ~, ext] = fileparts(file); ext = lower(ext);
info = struct('file', file, 'type', '', 'H', 0, 'W', 0, 'C', 1, 'Cs', 1, 'N', 0, 'cls', 'uint8', 'fps', NaN, 'var', '', 'rgb_is_gray', false);
switch ext
    case {'.tif', '.tiff'}
        fi = imfinfo(file); f1 = imread(file, 1);
        info.type = 'tiff'; info.N = numel(fi);
    case '.mat'
        w = whos('-file', file);
        num = arrayfun(@(x) any(strcmp(x.class, {'uint8', 'uint16', 'uint32', 'int8', 'int16', 'int32', 'single', 'double', 'logical'})) && ...
            numel(x.size) >= 3, w);
        w3 = w(num);
        if isempty(w3), error('sciplayer:noStack', 'The MAT-file holds no array with 3 or more dimensions.'); end
        [~, o] = sort(arrayfun(@(x) prod(x.size), w3), 'descend'); w3 = w3(o);
        k = 1;
        if numel(w3) > 1
            items = arrayfun(@(x) sprintf('%s   [%s]   %s', x.name, strjoin(arrayfun(@num2str, x.size, 'UniformOutput', false), ' x '), x.class), w3, 'UniformOutput', false);
            k = local_ask(fig, 'list', 'Which array holds the frames?', items);
            if isempty(k), info = []; return; end
        end
        info.type = 'mat'; info.var = w3(k).name; sz = w3(k).size; info.cls = w3(k).class;
        if numel(sz) == 4 && sz(3) == 3, info.N = sz(4); info.C = 3; else, info.N = prod(sz(3:end)); info.C = 1; end
        info.H = sz(1); info.W = sz(2); info.Cs = info.C;
        % a frame rate stored beside the frames
        for nm = {'fps', 'frame_rate', 'FrameRate', 'framerate', 'fs'}
            if any(strcmp({w.name}, nm{1}))
                v = load(file, nm{1}); v = v.(nm{1}); if isnumeric(v) && isscalar(v) && v > 0, info.fps = double(v); break; end
            end
        end
        if info.C == 3
            f1 = local_mat_frame(info, 1);
            info.rgb_is_gray = local_is_grey(f1);
            if info.rgb_is_gray, info.Cs = 1; end
        end
        return;
    otherwise
        v = VideoReader(file);
        info.type = 'video'; info.fps = double(v.FrameRate);
        n = NaN;
        try, n = v.NumFrames; catch, end
        if ~(isfinite(n) && n > 0), try, n = v.NumberOfFrames; catch, end, end %#ok<VIDREAD>
        if ~(isfinite(n) && n > 0), n = floor(v.Duration * v.FrameRate); end
        info.N = n;
        f1 = readFrame(v);
end
info.H = size(f1, 1); info.W = size(f1, 2); info.C = size(f1, 3); info.cls = class(f1);
info.rgb_is_gray = info.C == 3 && local_is_grey(f1);
info.Cs = local_iff(info.C == 3 && ~info.rgb_is_gray, 3, 1);
end

function f = local_mat_frame(info, k)
% one frame of a MAT-file array (matfile reads only that frame from a v7.3 file)
try
    if ~local_is_v73(info.file), error('sciplayer:v7', 'not v7.3'); end
    m = matfile(info.file);
    if info.C == 3, f = m.(info.var)(:, :, :, k); else, f = m.(info.var)(:, :, k); end
catch
    s = load(info.file, info.var); a = s.(info.var);
    if info.C == 3, f = a(:, :, :, k); else, f = a(:, :, k); end
end
end

function b = local_bytes(info, p)
n = numel(p.first:p.step:p.last);
cs = local_iff(p.gray, 1, info.Cs);
b = floor(info.H / p.bin) * floor(info.W / p.bin) * cs * n * local_bytes_per(info.cls);
end

function n = local_bytes_per(cls)
switch cls
    case {'uint8', 'int8', 'logical'}, n = 1;
    case {'uint16', 'int16'}, n = 2;
    case {'uint32', 'int32', 'single'}, n = 4;
    otherwise, n = 8;
end
end

function p = local_reduce_dialog(fig, info, p, lim)
% the recording is larger than the limit: ask how to reduce it before reading
avail = NaN;
try, [~, sv] = memory; avail = sv.PhysMem.Available; catch, end %#ok<NASGU>
% suggested reduction: 2 x 2 binning first, then every n-th frame
b0 = 1; s0 = 1; p0 = p;
for b = [1 2 4]
    p0.bin = b; if local_bytes(info, p0) <= lim, b0 = b; break; end, b0 = b;
end
p0.bin = b0; s0 = max(1, ceil(local_bytes(info, p0) / lim));
p.bin = b0; p.step = s0;
while true
    q = p; q.bin = 1; q.step = 1; q.first = 1; q.last = info.N; q.gray = info.Cs == 1;
    msg = sprintf(['%s: %d x %d px%s, %d frames, %s  ->  %s in memory, above the %.3g GB limit.%s\n\n' ...
        'Reduce it before reading (the suggestion below fits the limit):'], local_short(info.file), info.W, info.H, ...
        local_iff(info.Cs == 3, ' colour', ''), info.N, info.cls, local_size_text(local_bytes(info, q) / 1e6), lim / 1e9, ...
        local_iff(isfinite(avail), sprintf(' (%.1f GB of memory free)', avail / 1e9), ''));
    prompts = {[msg sprintf('\n\nSpatial binning (1 = none, 2 = 2 x 2 average, ...):')], 'Keep every n-th frame:', ...
        sprintf('First frame (1 - %d):', info.N), sprintf('Last frame (1 - %d):', info.N)};
    defs = {num2str(p.bin), num2str(p.step), num2str(p.first), num2str(p.last)};
    if info.Cs == 3, prompts{end+1} = 'Colour to grey (y / n):'; defs{end+1} = local_iff(p.gray, 'y', 'n'); end
    a = local_ask(fig, 'inputs', 'SciPlayer: the recording is large', prompts, defs);
    if isempty(a), p = []; return; end
    v = str2double(a(1:4));
    if any(~isfinite(v)) || v(1) < 1 || v(2) < 1, continue; end
    p.bin = round(v(1)); p.step = round(v(2)); p.first = max(1, min(info.N, round(v(3)))); p.last = max(p.first, min(info.N, round(v(4))));
    if info.Cs == 3, p.gray = strncmpi(strtrim(a{5}), 'y', 1); end
    b = local_bytes(info, p);
    if b <= lim, return; end
    c = local_ask(fig, 'question', sprintf('With these settings: %s in memory, still above the %.3g GB limit.', local_size_text(b / 1e6), lim / 1e9), ...
        'SciPlayer', 'Load anyway', 'Change', 'Cancel', 'Change');
    if strcmp(c, 'Load anyway'), return; end
    if ~strcmp(c, 'Change'), p = []; return; end
end
end

function [data, mtr, kept] = local_read(info, p)
% read the frames kept by P into memory; MTR = mean intensity of every frame
idx = p.first:p.step:p.last; n = numel(idx);
Hb = floor(info.H / p.bin); Wb = floor(info.W / p.bin); cs = local_iff(p.gray, 1, info.Cs);
if cs == 3, data = zeros(Hb, Wb, 3, n, info.cls); else, data = zeros(Hb, Wb, n, info.cls); end
mtr = nan(1, n); kept = zeros(1, n); i = 0;
wb = []; try, wb = waitbar(0, sprintf('Reading %s ...', local_short(info.file)), 'Name', 'SciPlayer'); catch, end
cleaner = onCleanup(@() local_close_wb(wb));
switch info.type
    case 'video'
        v = VideoReader(info.file); k = 0;
        while k < p.last
            if ~local_has_frame(v), break; end
            try, f = readFrame(v); catch, break; end
            k = k + 1;
            if k < p.first || mod(k - p.first, p.step) ~= 0, continue; end
            i = i + 1; [data, mtr(i)] = local_put(data, i, f, p, info, cs); kept(i) = k;
            if mod(i, 50) == 0, local_wb(wb, i / n); end
        end
    case 'tiff'
        for j = 1:n
            f = imread(info.file, idx(j)); i = i + 1; [data, mtr(i)] = local_put(data, i, f, p, info, cs); kept(i) = idx(j);
            if mod(i, 50) == 0, local_wb(wb, i / n); end
        end
    case 'mat'
        % a v7.3 file is read frame by frame (only the kept frames); any
        % other MAT-file cannot be read in parts, so the array is loaded once
        a = []; m = [];
        if local_is_v73(info.file), try, m = matfile(info.file); catch, m = []; end, end
        if isempty(m), s = load(info.file, info.var); a = s.(info.var); clear s; end
        for j = 1:n
            if ~isempty(a)
                if info.C == 3, f = a(:, :, :, idx(j)); else, f = a(:, :, idx(j)); end
            else
                if info.C == 3, f = m.(info.var)(:, :, :, idx(j)); else, f = m.(info.var)(:, :, idx(j)); end
            end
            i = i + 1; [data, mtr(i)] = local_put(data, i, f, p, info, cs); kept(i) = idx(j);
            if mod(i, 50) == 0, local_wb(wb, i / n); end
        end
end
if i < n
    if cs == 3, data = data(:, :, :, 1:i); else, data = data(:, :, 1:i); end
    mtr = mtr(1:i); kept = kept(1:i);
end
end

function [data, m] = local_put(data, i, f, p, info, cs)
% one frame: colour handling, binning, store; M = its mean intensity
if size(f, 3) == 3 && cs == 1
    f = cast(local_lum(f), class(f));
end
if p.bin > 1, f = local_bin(f, p.bin); end
if cs == 3, data(:, :, :, i) = f; m = mean(reshape(local_lum(f), [], 1));
else, data(:, :, i) = f; m = mean(double(f(:))); end
end

function tf = local_is_grey(f)
% a colour frame whose channels agree (grey video stored as RGB; lossy codecs
% leave a few levels of difference): mean |R-G| + |R-B| within 2 % of the range,
% its maximum within 5 %
if size(f, 3) ~= 3, tf = true; return; end
if isinteger(f), r = double(intmax(class(f))); else, r = max(1e-12, double(max(abs(f(:))))); end
d = abs(double(f(:, :, 1)) - double(f(:, :, 2))) + abs(double(f(:, :, 1)) - double(f(:, :, 3)));
tf = mean(d(:)) <= 0.02 * r && max(d(:)) <= 0.05 * r;
end

function g = local_lum(f)
% luminance of a colour frame (single); a grey frame as single
if size(f, 3) == 3, g = 0.299 * single(f(:, :, 1)) + 0.587 * single(f(:, :, 2)) + 0.114 * single(f(:, :, 3));
else, g = single(f); end
end

function f = local_bin(f, b)
% b x b block average, in the frame's own class
cls = class(f); H = floor(size(f, 1) / b) * b; W = floor(size(f, 2) / b) * b; C = size(f, 3);
x = single(f(1:H, 1:W, :));
x = reshape(x, b, H / b, b, W / b, C); x = mean(mean(x, 1), 3);
f = cast(reshape(x, H / b, W / b, C), cls);
end

function tf = local_is_v73(file)
% MAT-file version 7.3 (HDF5), whose arrays can be read in parts
tf = false; fid = fopen(file, 'r'); if fid < 0, return; end
hdr = fread(fid, 116, '*char').'; fclose(fid);
tf = ~isempty(strfind(hdr, 'MATLAB 7.3'));
end

function tf = local_has_frame(v)
tf = true; try, tf = hasFrame(v); catch, end
end

% =========================================================================
% display
% =========================================================================
function local_layout(fig)
% one panel (original) or two (original | relative change)
S = getappdata(fig, 'S'); h = S.h;
rel = strcmp(S.view, 'relative');
if ~isempty(h.cb2) && ishghandle(h.cb2), delete(h.cb2); end
h.cb2 = [];
if rel
    set(h.ax1, 'Position', [0.010 0.365 0.460 0.495]);
    set(h.ax2, 'Position', [0.478 0.365 0.460 0.495], 'Visible', 'off'); set(h.img2, 'Visible', 'on');
    h.cb2 = colorbar(h.ax2, 'eastoutside'); try, ylabel(h.cb2, 'dF/F (%)'); catch, end
    set(h.ax2, 'Position', [0.478 0.365 0.460 0.495]);           % (the colour bar must not shrink the frame)
    set(h.cb2, 'Position', [0.944 0.40 0.011 0.42]);
else
    set(h.ax1, 'Position', [0.010 0.365 0.980 0.495]);
    set(h.img2, 'Visible', 'off');
end
for r = 1:numel(h.roi_lines), set(h.roi_lines{r}(3:4), 'Visible', local_iff(rel, 'on', 'off')); end
if S.loaded, set([h.range_lbl h.range h.cmap_lbl h.cmap], 'Enable', local_iff(rel, 'on', 'off')); end
if S.loaded
    set(h.img1, 'CData', local_frame_display(S, S.cur));
    set(h.ax1, 'XLim', [0.5 S.W + 0.5], 'YLim', [0.5 S.H + 0.5]); set(h.ax2, 'XLim', [0.5 S.W + 0.5], 'YLim', [0.5 S.H + 0.5]);
    if ~S.is_rgb, set(h.ax1, 'CLim', S.clim_raw); end
end
S.h = h; setappdata(fig, 'S', S);
end

function local_show(fig)
% draw frame S.cur everywhere: the frame(s), the title, the slider, the cursor
S = getappdata(fig, 'S'); if ~S.loaded, return; end
h = S.h; k = S.cur;
set(h.img1, 'CData', local_frame_display(S, k));
if strcmp(S.view, 'relative') && ~isempty(S.F0)
    d = (local_lum(local_frame(S, k)) - S.F0) ./ S.F0 * 100; d(~S.F0ok) = NaN;
    set(h.img2, 'CData', d, 'AlphaData', double(isfinite(d)));
end
x = S.x(k);
for r = 1:numel(h.cursor), if ishghandle(h.cursor(r)), set(h.cursor(r), 'XData', [x x]); end, end
set(h.slider, 'Value', min(max(k, get(h.slider, 'Min')), get(h.slider, 'Max'))); set(h.frame, 'String', num2str(k));
ttl = sprintf('frame %d / %d', k, S.N);
if S.reduced, ttl = sprintf('%s   (recorded frame %d)', ttl, S.kept(k)); end
if isfinite(S.fps), ttl = sprintf('%s     t = %.3f s', ttl, S.x(k)); end
if strcmp(S.view, 'relative') && any(S.base == k), ttl = [ttl '     [baseline]']; end
set(h.title, 'String', ttl);
set(fig, 'Name', sprintf('SciPlayer - %s - frame %d / %d', local_short(S.file), k, S.N));
try, drawnow('limitrate'); catch, drawnow; end
end

function f = local_frame(S, k)
if S.is_rgb, f = S.data(:, :, :, k); else, f = S.data(:, :, k); end
end

function c = local_frame_display(S, k)
% what the image shows: grey frames as they are (scaled by CLim), colour frames as RGB
f = local_frame(S, k);
if S.is_rgb
    if isa(f, 'uint8'), c = f; else, c = single(f); c = (c - S.clim_raw(1)) / max(eps, diff(S.clim_raw)); c = min(1, max(0, c)); end
else
    c = f;
end
end

function cl = local_raw_clim(S)
% display range of the original frames: 0.5th - 99.5th percentile of up to 20 frames
ks = unique(round(linspace(1, S.N, min(20, S.N))));
v = [];
for k = ks, g = local_lum(local_frame(S, k)); g = g(1:max(1, floor(numel(g) / 2e5)):end); v = [v; g(:)]; end %#ok<AGROW>
v = sort(double(v(isfinite(v))));
if isempty(v), cl = [0 1]; return; end
cl = [v(max(1, round(0.005 * numel(v)))), v(max(1, round(0.995 * numel(v))))];
if ~(cl(2) > cl(1)), cl = [min(v), max(v) + eps]; end
end

% =========================================================================
% navigation and playback
% =========================================================================
function local_goto(fig, k)
S = getappdata(fig, 'S'); if ~S.loaded || ~isfinite(k), return; end
S.cur = max(1, min(S.N, round(k))); setappdata(fig, 'S', S); local_show(fig);
end

function local_step(fig, n)
S = getappdata(fig, 'S'); if ~S.loaded, return; end
local_goto(fig, S.cur + n);
end

function local_key(fig, e)
S = getappdata(fig, 'S'); if ~S.loaded, return; end
% a control with the keyboard focus handles its own keys (a focused slider
% moves on the arrows, a focused button presses on Space): acting here too
% would step twice
co = []; try, co = get(fig, 'CurrentObject'); catch, end
if ~isempty(co) && ishghandle(co) && strcmp(get(co, 'Type'), 'uicontrol')
    st = get(co, 'Style'); k_ = lower(e.Key);
    if strcmp(st, 'slider') && any(strcmp(k_, {'rightarrow', 'right', 'leftarrow', 'left'})), return; end
    if any(strcmp(st, {'pushbutton', 'togglebutton', 'checkbox'})) && strcmp(k_, 'space'), return; end
end
mods = {}; try, mods = e.Modifier; catch, end
n = local_iff(any(strcmpi(mods, 'shift')), 10, 1);
switch lower(e.Key)
    case {'rightarrow', 'right'}, local_step(fig, n);
    case {'leftarrow', 'left'}, local_step(fig, -n);
    case {'home'}, local_goto(fig, 1);
    case {'end'}, local_goto(fig, S.N);
    case {'space'}, set(S.h.play, 'Value', 1 - get(S.h.play, 'Value')); if get(S.h.play, 'Value') == 1, local_play(fig, Inf); end
end
end

function local_wheel(fig, e)
n = 1; try, n = e.VerticalScrollCount; catch, end
local_step(fig, sign(n) * max(1, abs(round(n))));
end

function local_play(fig, n_max)
% play from the current frame in real time at the frame rate (every n-th
% frame kept: rate / n frames shown per second; 10 frames/s while no rate is
% known), until Pause, the end (or around again with "loop"), or N_MAX frames
% (scripted use)
S = getappdata(fig, 'S'); h = S.h;
if ~S.loaded, set(h.play, 'Value', 0); return; end
if isfinite(n_max), set(h.play, 'Value', 1); end
if get(h.play, 'Value') == 0, set(h.play, 'String', 'Play'); return; end
if isappdata(fig, 'playing') && getappdata(fig, 'playing'), return; end      % already running
setappdata(fig, 'playing', true); set(h.play, 'String', 'Pause');
shown = 0;
while ishghandle(fig) && get(h.play, 'Value') == 1 && shown < n_max
    t0 = tic;
    S = getappdata(fig, 'S'); r = local_play_rate(S);
    k = S.cur + 1;
    if k > S.N
        if get(h.loop, 'Value') == 1, k = 1; else, break; end
    end
    local_goto(fig, k); shown = shown + 1;
    pause(max(0.001, 1 / r - toc(t0)));
end
if ishghandle(fig), set(h.play, 'Value', 0, 'String', 'Play'); setappdata(fig, 'playing', false); end
end

function r = local_play_rate(S)
% frames shown per second: the recording in real time
r = 10;
if isfinite(S.fps) && S.fps > 0, r = S.fps; if isfield(S, 'p') && S.p.step > 1, r = r / S.p.step; end, end
end

function local_stop(fig)
S = getappdata(fig, 'S'); set(S.h.play, 'Value', 0); setappdata(fig, 'playing', false);
end

function local_close(fig)
try, local_stop(fig); catch, end
delete(fig);
end

% =========================================================================
% view, baseline, colour
% =========================================================================
function local_set_view(fig, v)
S = getappdata(fig, 'S'); S.view = v; setappdata(fig, 'S', S);
set(S.h.view, 'Value', local_iff(strcmp(v, 'relative'), 2, 1));
if ~S.loaded, return; end
if strcmp(v, 'relative') && isempty(S.F0), local_set_baseline(fig, S.base_str); end
local_layout(fig); local_apply_cmap(fig); local_traces(fig); local_show(fig);
end

function local_set_baseline(fig, str)
S = getappdata(fig, 'S'); if ~S.loaded, return; end
b = local_parse_frames(str, S.N);
if isempty(b), set(S.h.base, 'String', S.base_str); return; end
S.base = b; S.base_str = strtrim(str); set(S.h.base, 'String', S.base_str);
F0 = zeros(S.H, S.W, 'single');
for k = b, F0 = F0 + local_lum(local_frame(S, k)); end
F0 = F0 / numel(b);
S.F0ok = abs(F0) > max(eps('single'), 1e-6 * max(abs(F0(:)))); S.F0 = F0; S.F0(~S.F0ok) = NaN;
setappdata(fig, 'S', S);
local_set_range(fig, S.range_str);
if strcmp(S.view, 'relative'), local_traces(fig); local_show(fig); end
end

function local_set_range(fig, str)
% dF/F colour range: auto (symmetric 99th percentile of |dF/F| over up to 30 frames), a, or [lo hi]
S = getappdata(fig, 'S'); if ~S.loaded || isempty(S.F0), return; end
v = sscanf(strrep(strtrim(str), ',', ' '), '%f').';
if strcmpi(strtrim(str), 'auto') || isempty(v)
    ks = unique(round(linspace(1, S.N, min(30, S.N)))); a = [];
    for k = ks, d = (local_lum(local_frame(S, k)) - S.F0) ./ S.F0 * 100; d = abs(d(isfinite(d))); a = [a; d(1:max(1, floor(numel(d) / 1e5)):end)]; end %#ok<AGROW>
    a = sort(double(a)); lim = 1; if ~isempty(a), lim = max(a(max(1, round(0.99 * numel(a)))), 1e-3); end
    cl = [-lim lim]; str = 'auto';
elseif numel(v) == 1, cl = [-abs(v) abs(v)];
else, cl = sort(v(1:2)); if cl(2) == cl(1), cl(2) = cl(1) + 1; end
end
S.range_str = str; S.clim_dff = cl; set(S.h.range, 'String', str); setappdata(fig, 'S', S);
set(S.h.ax2, 'CLim', cl);
end

function local_set_cmap(fig, name)
S = getappdata(fig, 'S'); S.cmap = name; setappdata(fig, 'S', S);
names = local_cmap_names(); set(S.h.cmap, 'Value', max(1, find(strcmp(names, name), 1)));
local_apply_cmap(fig);
end

function local_apply_cmap(fig)
S = getappdata(fig, 'S'); colormap(S.h.ax2, local_cmap(S.cmap, 256));
if isfield(S, 'clim_dff'), set(S.h.ax2, 'CLim', S.clim_dff); end
end

function local_set_fps(fig, v)
S = getappdata(fig, 'S'); if ~S.loaded, return; end
if ~(isfinite(v) && v > 0), v = NaN; end
S.fps = v; setappdata(fig, 'S', S);
set(S.h.fps, 'String', local_iff(isfinite(v), sprintf('%.4g', v), ''));
local_traces(fig); local_show(fig);
end

% =========================================================================
% traces
% =========================================================================
function local_traces(fig)
% one row per signal (whole frame, then every ROI), each with its own y axis
S = getappdata(fig, 'S'); h = S.h; if ~S.loaded, return; end
delete(h.trace_ax(ishghandle(h.trace_ax))); h.trace_ax = []; h.cursor = [];
if isfinite(S.fps), S.x = (S.kept - 1) / S.fps; xl = 'time (s)'; else, S.x = S.kept; xl = 'recorded frame'; end
rel = strcmp(S.view, 'relative');
names = [{'whole frame'}, {S.rois.name}]; ys = [{S.mean_trace}, {S.rois.trace}]; cols = [{[0.25 0.25 0.25]}, {S.rois.color}];
nr = numel(names); y0 = 0.085; y1 = 0.285; gap = 0.006; hh = (y1 - y0 - gap * (nr - 1)) / nr;
xr = [S.x(1), S.x(end)]; if ~(xr(2) > xr(1)), xr = xr(1) + [-0.5 0.5]; end
for r = 1:nr
    ax = axes('Parent', fig, 'Position', [0.085 y1 - r * hh - (r - 1) * gap, 0.895, hh], 'FontSize', 8, 'Box', 'on', 'Tag', 'trace_ax');
    hold(ax, 'on');
    y = double(ys{r}); unit = 'a.u.';
    if rel && ~isempty(S.base)
        b0 = mean(y(S.base)); y = (y - b0) / max(abs(b0), eps) * 100; unit = '%';
    end
    yl = [min(y), max(y)]; if ~all(isfinite(yl)), yl = [0 1]; end; if ~(yl(2) > yl(1)), yl = yl(1) + [-0.5 0.5]; end
    yl = yl + [-0.06 0.06] * diff(yl);
    if rel && ~isempty(S.base)
        for seg = local_segments(S.base)
            xs = S.x(seg); patch(ax, [xs(1) xs(2) xs(2) xs(1)], yl([1 1 2 2]), [0.85 0.85 0.85], 'EdgeColor', 'none', 'HitTest', 'off');
        end
    end
    plot(ax, S.x, y, '-', 'Color', cols{r}, 'LineWidth', 1, 'HitTest', 'off');
    h.cursor(r) = plot(ax, S.x(S.cur) * [1 1], yl, 'k--', 'LineWidth', 1, 'HitTest', 'off');
    set(ax, 'XLim', xr, 'YLim', yl, 'ButtonDownFcn', @(a_, e_) local_trace_click(fig, a_));
    grid(ax, 'on');
    % ticks at the row's own lowest and highest value (each row has its own scale)
    yv = [min(y), max(y)]; if yv(2) > yv(1), set(ax, 'YTick', yv, 'YTickLabel', {sprintf('%.4g', yv(1)), sprintf('%.4g', yv(2))}); end
    ylabel(ax, sprintf('%s\n(%s)', names{r}, local_iff(rel, ['dF/F, ' unit], unit)), 'Color', cols{r}, 'FontSize', 8, 'Rotation', 0, ...
        'HorizontalAlignment', 'right', 'VerticalAlignment', 'middle');
    if r < nr, set(ax, 'XTickLabel', {}); else, xlabel(ax, xl); end
    h.trace_ax(r) = ax;
end
S.h = h; setappdata(fig, 'S', S);
end

function local_trace_click(fig, ax)
S = getappdata(fig, 'S'); cp = get(ax, 'CurrentPoint');
[~, k] = min(abs(S.x - cp(1, 1))); local_goto(fig, k);
end

function segs = local_segments(b)
% contiguous runs of frame numbers, as columns [first; last]
b = sort(b(:).'); br = [0, find(diff(b) > 1), numel(b)];
segs = zeros(2, numel(br) - 1);
for i = 1:numel(br) - 1, segs(:, i) = [b(br(i) + 1); b(br(i + 1))]; end
end

% =========================================================================
% ROIs
% =========================================================================
function local_add_roi(fig, shape, xy, path)
% SHAPE 'rect' (XY: two opposite corners, or the four) or 'freehand' ('poly':
% the same, any closed outline); XY empty: the user draws it (PATH: a scripted
% mouse path instead of the mouse)
S = getappdata(fig, 'S'); if ~S.loaded, return; end
if strcmpi(shape, 'poly') || strcmpi(shape, 'polygon'), shape = 'freehand'; end
if ~any(strcmp(shape, {'rect', 'freehand'})), error('sciplayer:shape', 'ROI shape "%s": use rect or freehand.', shape); end
local_stop(fig);
if isempty(xy)
    if nargin < 4, path = []; end
    xy = local_draw(fig, shape, path);
    if isempty(xy), return; end
end
S = getappdata(fig, 'S');
if strcmp(shape, 'rect') && size(xy, 1) == 2
    x = sort(xy(:, 1)); y = sort(xy(:, 2)); xy = [x([1 2 2 1]), y([1 1 2 2])];
end
% the mask, tested only inside the ROI's bounding box (a freehand outline has many vertices)
mask = false(S.H, S.W);
c0 = max(1, floor(min(xy(:, 1)))); c1 = min(S.W, ceil(max(xy(:, 1))));
r0 = max(1, floor(min(xy(:, 2)))); r1 = min(S.H, ceil(max(xy(:, 2))));
if c1 >= c0 && r1 >= r0
    [X, Y] = meshgrid(c0:c1, r0:r1);
    mask(r0:r1, c0:c1) = inpolygon(X, Y, xy(:, 1), xy(:, 2));
end
if ~any(mask(:)), local_msg(fig, 'The ROI holds no pixel.'); return; end
cols = local_roi_colours(); c = cols(1 + mod(numel(S.rois), size(cols, 1)), :);
S.roi_count = S.roi_count + 1; nm = sprintf('ROI %d', S.roi_count);
S.rois(end+1) = struct('name', nm, 'xy', xy, 'mask', mask, 'color', c, 'trace', local_roi_trace(S, mask));
h = S.h; xc = [xy(:, 1); xy(1, 1)]; yc = [xy(:, 2); xy(1, 2)];
l1 = plot(h.ax1, xc, yc, '-', 'Color', c, 'LineWidth', 1.5); t1 = text(h.ax1, xy(1, 1), xy(1, 2), [' ' nm], 'Color', c, 'FontWeight', 'bold', 'VerticalAlignment', 'bottom');
l2 = plot(h.ax2, xc, yc, '-', 'Color', c, 'LineWidth', 1.5); t2 = text(h.ax2, xy(1, 1), xy(1, 2), [' ' nm], 'Color', c, 'FontWeight', 'bold', 'VerticalAlignment', 'bottom');
vis = local_iff(strcmp(S.view, 'relative'), 'on', 'off'); set([l2 t2], 'Visible', vis);
h.roi_lines{end+1} = [l1 t1 l2 t2]; S.h = h; setappdata(fig, 'S', S);
local_traces(fig); local_show(fig);
end

function xy = local_draw(fig, shape, path)
% the user draws the ROI with the mouse, on the frame (on either panel in the
% relative view): press the left button, drag, release.
%   rect      the drag spans two opposite corners (the box follows the mouse)
%   freehand  the drag traces the outline; the line back to the start shows
%             how it will close, and it closes on release
% Esc or a right-click cancels; a drag too small to hold a pixel is ignored
% (draw again). PATH ([n x 2], frame pixels) replays a mouse path instead of
% waiting for the mouse (scripted use and testing).
S = getappdata(fig, 'S'); h = S.h; xy = [];
if nargin < 3, path = []; end
if isappdata(fig, 'roi_draw'), return; end                 % already drawing
axs = h.ax1; if strcmp(S.view, 'relative'), axs = [h.ax1 h.ax2]; end
D = struct('shape', shape, 'axs', axs, 'ax', [], 'pts', zeros(0, 2), 'lines', [], 'state', 'wait', 'xy', []);
setappdata(fig, 'roi_draw', D);
old = struct('title', get(h.title, 'String'), 'tcol', get(h.title, 'ForegroundColor'), 'pointer', get(fig, 'Pointer'), ...
    'down', {get(fig, 'WindowButtonDownFcn')}, 'move', {get(fig, 'WindowButtonMotionFcn')}, ...
    'up', {get(fig, 'WindowButtonUpFcn')}, 'key', {get(fig, 'WindowKeyPressFcn')});
set(h.title, 'String', local_draw_msg(shape, false), 'ForegroundColor', [0.85 0.33 0.10]);
set([h.roi_rect h.roi_free], 'Enable', 'off');
try
    if isempty(path)
        % figure modes (zoom, pan, data cursor) own the mouse: switch them off
        try, zoom(fig, 'off'); catch, end
        try, pan(fig, 'off'); catch, end
        try, datacursormode(fig, 'off'); catch, end
        set(fig, 'Pointer', 'crosshair', 'WindowButtonDownFcn', @(f_, e_) local_draw_event(fig, 'down'), ...
            'WindowButtonMotionFcn', @(f_, e_) local_draw_event(fig, 'move'), ...
            'WindowButtonUpFcn', @(f_, e_) local_draw_event(fig, 'up'), 'WindowKeyPressFcn', @(f_, e_) local_draw_key(fig, e_));
        figure(fig);
        while ishghandle(fig)
            D = getappdata(fig, 'roi_draw');
            if any(strcmp(D.state, {'done', 'cancel'})), break; end
            uiwait(fig);
        end
    else
        ax = h.ax1; if size(path, 2) >= 3 && path(1, 3) == 2, ax = h.ax2; end
        local_draw_step(fig, 'down', path(1, 1:2), ax);
        for i = 2:size(path, 1), local_draw_step(fig, 'move', path(i, 1:2), ax); end
        local_draw_step(fig, 'up', path(end, 1:2), ax);
        D = getappdata(fig, 'roi_draw');
        if ~strcmp(D.state, 'done'), local_draw_step(fig, 'cancel', [], []); end
    end
catch e
    if ishghandle(fig), fprintf('[sciplayer] drawing the ROI failed: %s\n', e.message); end
end
if ~ishghandle(fig), return; end
D = getappdata(fig, 'roi_draw'); rmappdata(fig, 'roi_draw');
if strcmp(D.state, 'done'), xy = D.xy; end
delete(D.lines(ishghandle(D.lines)));
set(fig, 'Pointer', old.pointer, 'WindowButtonDownFcn', old.down, 'WindowButtonMotionFcn', old.move, ...
    'WindowButtonUpFcn', old.up, 'WindowKeyPressFcn', old.key);
set(h.title, 'String', old.title, 'ForegroundColor', old.tcol);
set([h.roi_rect h.roi_free], 'Enable', 'on');
end

function s = local_draw_msg(shape, again)
if strcmp(shape, 'rect')
    s = 'ROI rectangle: press the left button on the frame, drag to the opposite corner, release   (Esc: cancel)';
else
    s = 'ROI freehand: press the left button on the frame, trace the outline, release to close it   (Esc: cancel)';
end
if again, s = ['Too small - draw again.   ' s]; end
end

function local_draw_event(fig, ev)
% mouse events while drawing: where the press landed decides the panel
D = getappdata(fig, 'roi_draw'); if isempty(D), return; end
if strcmp(ev, 'down')
    st = get(fig, 'SelectionType');
    if strcmp(st, 'alt'), local_draw_step(fig, 'cancel', [], []); return; end   % right-click
    if ~strcmp(st, 'normal'), return; end
    ax = []; pt = [];
    for a = D.axs(:).'
        cp = get(a, 'CurrentPoint'); p = cp(1, 1:2); xl = get(a, 'XLim'); yl = get(a, 'YLim');
        if p(1) >= xl(1) && p(1) <= xl(2) && p(2) >= yl(1) && p(2) <= yl(2), ax = a; pt = p; break; end
    end
    if isempty(ax), return; end                               % pressed beside the frame
    local_draw_step(fig, 'down', pt, ax);
else
    if isempty(D.ax) || ~ishghandle(D.ax), return; end
    cp = get(D.ax, 'CurrentPoint'); local_draw_step(fig, ev, cp(1, 1:2), D.ax);
end
end

function local_draw_key(fig, e)
if strcmpi(e.Key, 'escape'), local_draw_step(fig, 'cancel', [], []); else, local_key(fig, e); end
end

function local_draw_step(fig, ev, pt, ax)
% one step of drawing: 'down' starts, 'move' extends, 'up' finishes, 'cancel'
D = getappdata(fig, 'roi_draw'); if isempty(D), return; end
S = getappdata(fig, 'S');
if ~isempty(pt), pt = [min(max(pt(1), 0.5), S.W + 0.5), min(max(pt(2), 0.5), S.H + 0.5)]; end
switch ev
    case 'down'
        if ~strcmp(D.state, 'wait'), return; end
        D.state = 'drag'; D.ax = ax; D.pts = pt;
        delete(D.lines(ishghandle(D.lines))); D.lines = [];
        for a = D.axs(:).'
            D.lines(end+1) = plot(a, pt(1), pt(2), '-', 'Color', [1.00 0.85 0.00], 'LineWidth', 1.5, 'HitTest', 'off');
        end
    case {'move', 'up'}
        if ~strcmp(D.state, 'drag'), return; end
        if strcmp(D.shape, 'rect'), D.pts = [D.pts(1, :); pt];
        elseif norm(pt - D.pts(end, :)) >= 1, D.pts(end+1, :) = pt;  % a vertex at least 1 pixel from the last
        end
        if strcmp(ev, 'up')
            [xy, ok] = local_draw_result(D);
            if ok
                D.state = 'done'; D.xy = xy;
            else                                              % too small: draw again
                D.state = 'wait'; D.ax = []; D.pts = zeros(0, 2);
                delete(D.lines(ishghandle(D.lines))); D.lines = [];
                set(S.h.title, 'String', local_draw_msg(D.shape, true));
            end
        end
    case 'cancel'
        D.state = 'cancel';
end
if strcmp(D.state, 'drag') && ~isempty(D.lines)
    if strcmp(D.shape, 'rect')
        x = D.pts([1 end], 1); y = D.pts([1 end], 2); xd = x([1 2 2 1 1]); yd = y([1 1 2 2 1]);
    else
        xd = [D.pts(:, 1); D.pts(1, 1)]; yd = [D.pts(:, 2); D.pts(1, 2)];
    end
    set(D.lines(ishghandle(D.lines)), 'XData', xd, 'YData', yd);
end
setappdata(fig, 'roi_draw', D);
try, drawnow('limitrate'); catch, drawnow; end
if any(strcmp(D.state, {'done', 'cancel'})), uiresume(fig); end
end

function [xy, ok] = local_draw_result(D)
% the drawn ROI, if it is big enough to hold a pixel
xy = []; ok = false;
if strcmp(D.shape, 'rect')
    if size(D.pts, 1) < 2, return; end
    x = sort(D.pts([1 end], 1)); y = sort(D.pts([1 end], 2));
    if diff(x) >= 1 && diff(y) >= 1, xy = [x, y]; ok = true; end
else
    p = D.pts;
    if size(p, 1) >= 3 && abs(polyarea(p(:, 1), p(:, 2))) >= 2, xy = p; ok = true; end
end
end

function tr = local_roi_trace(S, mask)
% mean intensity inside MASK in every frame (luminance for colour), in blocks of frames
idx = find(mask(:)); tr = zeros(1, S.N); bs = max(1, floor(2e7 / max(1, numel(idx))));
for k0 = 1:bs:S.N
    ks = k0:min(S.N, k0 + bs - 1);
    if S.is_rgb
        X = reshape(S.data(:, :, :, ks), S.H * S.W, 3, numel(ks));
        tr(ks) = 0.299 * mean(single(X(idx, 1, :)), 1) + 0.587 * mean(single(X(idx, 2, :)), 1) + 0.114 * mean(single(X(idx, 3, :)), 1);
    else
        X = reshape(S.data(:, :, ks), S.H * S.W, numel(ks));
        tr(ks) = mean(single(X(idx, :)), 1);
    end
end
end

function local_remove_roi(fig, k)
S = getappdata(fig, 'S'); if isempty(S.rois), local_msg(fig, 'There is no ROI to remove.'); return; end
if isempty(k)
    k = local_ask(fig, 'list', 'Remove which ROI(s)?', {S.rois.name}, 'multiple');
    if isempty(k), return; end
end
k = k(k >= 1 & k <= numel(S.rois));
for i = k, delete(S.h.roi_lines{i}(ishghandle(S.h.roi_lines{i}))); end
S.rois(k) = []; S.h.roi_lines(k) = []; setappdata(fig, 'S', S);
local_traces(fig); local_show(fig);
end

function local_clear_rois(fig)
S = getappdata(fig, 'S');
for i = 1:numel(S.h.roi_lines), delete(S.h.roi_lines{i}(ishghandle(S.h.roi_lines{i}))); end
S.rois = S.rois([]); S.h.roi_lines = {}; S.roi_count = 0; setappdata(fig, 'S', S);
end

% =========================================================================
% export
% =========================================================================
function local_export(fig, file)
S = getappdata(fig, 'S'); if ~S.loaded, return; end
if isempty(file)
    [p, b] = fileparts(S.file);
    [fn, pth] = uiputfile('*.csv', 'Export the traces', fullfile(p, [b '_sciplayer_traces.csv']));
    if isequal(fn, 0), return; end
    file = fullfile(pth, fn);
end
names = [{'whole_frame'}, cellfun(@(s) strrep(s, ' ', '_'), {S.rois.name}, 'UniformOutput', false)];
Y = [S.mean_trace(:), reshape([S.rois.trace], S.N, [])];
R = nan(size(Y));
if ~isempty(S.base), b0 = mean(Y(S.base, :), 1); R = (Y - b0) ./ max(abs(b0), eps) * 100; end
fid = fopen(file, 'w'); if fid < 0, local_msg(fig, sprintf('Cannot write %s', file)); return; end
fprintf(fid, '%% SciPlayer traces of %s; mean intensity (a.u., luminance for colour) and relative change (%%) against baseline frames %s\n', S.file, S.base_str);
for i = 1:numel(S.rois), fprintf(fid, '%% %s outline x: %s; y: %s\n', S.rois(i).name, mat2str(round(S.rois(i).xy(:, 1).' * 10) / 10), mat2str(round(S.rois(i).xy(:, 2).' * 10) / 10)); end
hdr = [{'frame', 'recorded_frame', 'time_s'}, strcat(names, '_mean'), strcat(names, '_dff_pct')];
fprintf(fid, '%s\n', strjoin(hdr, ','));
t = nan(1, S.N); if isfinite(S.fps), t = (S.kept - 1) / S.fps; end
for k = 1:S.N
    fprintf(fid, '%d,%d,%.6g%s%s\n', k, S.kept(k), t(k), sprintf(',%.6g', Y(k, :)), sprintf(',%.6g', R(k, :)));
end
fclose(fid);
set(S.h.info, 'String', sprintf('Traces written: %s', file));
end

function local_save_view(fig, file)
S = getappdata(fig, 'S');
if isempty(file)
    nm = 'sciplayer_view.png'; if S.loaded, [~, b] = fileparts(S.file); nm = sprintf('%s_frame%05d.png', b, S.cur); end
    [fn, pth] = uiputfile('*.png', 'Save the view', nm);
    if isequal(fn, 0), return; end
    file = fullfile(pth, fn);
end
drawnow; fr = getframe(fig); imwrite(fr.cdata, file);
end

% =========================================================================
% scripting interface
% =========================================================================
function out = local_command(fig, cmd, a)
out = [];
switch cmd
    case 'load', local_load(fig, a{1});
    case 'goto', local_goto(fig, a{1});
    case 'step', local_step(fig, a{1});
    case 'view', local_set_view(fig, a{1});
    case 'baseline', local_set_baseline(fig, a{1});
    case 'range', local_set_range(fig, a{1});
    case 'colormap', local_set_cmap(fig, a{1});
    case 'fps', local_set_fps(fig, a{1});
    case 'add_roi', local_add_roi(fig, a{1}, a{2});
    case 'draw', local_add_roi(fig, a{1}, [], a{2});
    case 'remove_roi', local_remove_roi(fig, a{1});
    case 'export', local_export(fig, a{1});
    case 'save_view', local_save_view(fig, a{1});
    case 'play', local_play(fig, a{1});
    case 'answers', S = getappdata(fig, 'S'); S.answers = a{1}; setappdata(fig, 'S', S);
    case 'state', S = getappdata(fig, 'S'); if isfield(S, 'data'), S = rmfield(S, 'data'); end; out = S;
    otherwise, error('sciplayer:command', 'Unknown command "%s".', cmd);
end
end

% =========================================================================
% dialogs (answers can be queued for scripted use)
% =========================================================================
function a = local_ask(fig, kind, varargin)
S = getappdata(fig, 'S');
if ~isempty(S.answers)
    a = S.answers{1}; S.answers(1) = []; setappdata(fig, 'S', S); return;
end
switch kind
    case 'list'
        mode = 'single'; if numel(varargin) > 2, mode = varargin{3}; end
        [a, ok] = listdlg('PromptString', varargin{1}, 'ListString', varargin{2}, 'SelectionMode', mode, 'ListSize', [420 160]);
        if ~ok, a = []; end
    case 'inputs'
        a = inputdlg(varargin{2}, varargin{1}, 1, varargin{3});
    case 'question'
        a = questdlg(varargin{:});
end
end

function local_msg(fig, s)
S = getappdata(fig, 'S');
if strcmp(S.opts.visible, 'off') || ~isempty(S.answers), fprintf('[sciplayer] %s\n', s); return; end
try, uiwait(msgbox(s, 'SciPlayer', 'modal')); catch, fprintf('[sciplayer] %s\n', s); end
end

% =========================================================================
% small helpers
% =========================================================================
function local_enable(fig, st)
S = getappdata(fig, 'S'); h = S.h;
for c = {'export', 'save', 'view', 'base', 'range', 'cmap', 'roi_rect', 'roi_free', 'roi_del', 'prev', 'next', 'frame', 'play', 'loop', 'fps', 'slider', 'range_lbl', 'cmap_lbl'}
    set(h.(c{1}), 'Enable', st);
end
end

function b = local_parse_frames(str, N)
% '1-10', '1:10', '1-10, 200-210', '5 7 9' -> frame numbers within 1..N
b = [];
tok = regexp(strrep(strtrim(str), ';', ','), '[,\s]+', 'split');
for i = 1:numel(tok)
    t = tok{i}; if isempty(t), continue; end
    v = sscanf(strrep(strrep(t, ':', ' '), '-', ' '), '%f').';
    if numel(v) == 1, b = [b, round(v)]; elseif numel(v) >= 2, b = [b, round(v(1)):round(v(end))]; end %#ok<AGROW>
end
b = unique(b(b >= 1 & b <= N));
end

function names = local_cmap_names(), names = {'blue-white-red', 'jet', 'hot', 'gray', 'parula / viridis'}; end

function cm = local_cmap(name, n)
switch name
    case 'jet', cm = jet(n);
    case 'hot', cm = hot(n);
    case 'gray', cm = gray(n);
    case 'parula / viridis'
        try, cm = parula(n); catch, try, cm = viridis(n); catch, cm = jet(n); end, end
    otherwise   % blue - white - red
        h = floor(n / 2); a = linspace(0, 1, h).';
        cm = [[a a ones(h, 1)]; [ones(n - h, 1) flipud(linspace(0, 1, n - h).') flipud(linspace(0, 1, n - h).')]];
end
end

function c = local_roi_colours()
c = [0.00 0.45 0.74; 0.85 0.33 0.10; 0.47 0.67 0.19; 0.49 0.18 0.56; 0.93 0.69 0.13; 0.30 0.75 0.93; 0.64 0.08 0.18];
end

function s = local_pick(c, i), s = c{i}; end

function s = local_arrow(d)
% triangle arrows where the platform's characters allow (MATLAB), plain ones otherwise (Octave)
if exist('OCTAVE_VERSION', 'builtin'), s = local_iff(d < 0, '<', '>'); else, s = char(local_iff(d < 0, 9664, 9654)); end
end
function y = local_iff(c, a, b), if c, y = a; else, y = b; end, end
function s = local_short(f), [~, b, e] = fileparts(f); s = [b e]; end
function s = local_size_text(mb), if mb >= 1000, s = sprintf('%.2f GB', mb / 1000); else, s = sprintf('%.0f MB', mb); end, end
function tf = local_is_fig(h), tf = ~ischar(h) && isscalar(h) && ishghandle(h) && strcmp(get(h, 'Type'), 'figure'); end
function local_wb(wb, v), if ~isempty(wb) && ishghandle(wb), try, waitbar(v, wb); catch, end, end, end
function local_close_wb(wb), if ~isempty(wb) && ishghandle(wb), delete(wb); end, end

function s = local_reduction_text(info, p)
c = {};
if p.bin > 1, c{end+1} = sprintf('%d x %d binning', p.bin, p.bin); end
if p.step > 1, c{end+1} = sprintf('every %d-th frame', p.step); end
if p.first > 1 || p.last < info.N, c{end+1} = sprintf('frames %d-%d', p.first, p.last); end
if info.Cs == 3 && p.gray, c{end+1} = 'grey'; end
s = strjoin(c, ', ');
end
