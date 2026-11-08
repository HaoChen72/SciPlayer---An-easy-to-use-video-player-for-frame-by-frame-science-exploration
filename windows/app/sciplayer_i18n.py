# -*- coding: utf-8 -*-
"""SciPlayer - languages of the window: English, 简体中文, 繁體中文.

tr(text) returns TEXT in the current language (the English text is the key; format fields such
as %s and %d stay where they are). The language is chosen in the window (the globe button),
remembered, and on first start taken from the installer's choice or from Windows' language.
"""
LANGS = [('en', 'English'), ('zh_CN', '简体中文'), ('zh_TW', '繁體中文')]
_lang = 'en'


def set_language(code):
    global _lang
    _lang = code if code in dict(LANGS) else 'en'
    return _lang


def language():
    return _lang


def system_language():
    """zh_CN / zh_TW from Windows' language (Hong Kong, Macau, Taiwan: traditional), else English"""
    try:
        from PySide6.QtCore import QLocale
        loc = QLocale.system()
        name = loc.name()                                  # e.g. zh_CN, zh_TW, en_US
        if name.startswith('zh'):
            if loc.script() == QLocale.TraditionalChineseScript or name[3:5] in ('TW', 'HK', 'MO'):
                return 'zh_TW'
            return 'zh_CN'
    except Exception:
        pass
    return 'en'


def fonts():
    """font families for the language: the Latin face first, the right Chinese face next"""
    latin = ['Segoe UI Variable Text', 'Segoe UI']
    if _lang == 'zh_CN':
        return latin + ['Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans CJK SC', 'PingFang SC']
    if _lang == 'zh_TW':
        return latin + ['Microsoft JhengHei UI', 'Microsoft JhengHei', 'Noto Sans CJK TC', 'PingFang TC']
    return latin + ['Inter', 'Helvetica Neue', 'Arial']


def tr(text):
    if _lang == 'en':
        return text
    t = T.get(text)
    if t is None:
        return text
    return t[0] if _lang == 'zh_CN' else t[1]


HELP_EN = ('<b>Keyboard and mouse</b><br>'
           'Left / Right: one frame (Shift: 10)<br>Mouse wheel: scroll through frames<br>'
           'Space: play / pause<br>Home / End: first / last frame<br>'
           'Drag the slider: every frame, smoothly<br>Click a trace: jump there<br>'
           'Drag the edge above the slider: frame / traces<br>Drop a file on the window: open it<br>'
           'Esc or right-click: cancel drawing an ROI<br>'
           'Ctrl + mouse wheel: zoom in / out where the mouse points<br>'
           'Zoomed in: drag to move; double-click or Ctrl+0: the whole frame')

# English: (简体中文, 繁體中文)
T = {
    # top bar
    'Open': ('打开', '開啟'),
    'open a video (any format FFmpeg reads), a multi-page TIFF or a MAT-file with an [H x W x frames] array '
    '(Ctrl+O; or drop a file on the window)':
        ('打开视频（FFmpeg 支持的任何格式）、多页 TIFF，或含 [H x W x 帧] 数组的 MAT 文件（Ctrl+O；也可把文件拖入窗口）',
         '開啟影片（FFmpeg 支援的任何格式）、多頁 TIFF，或含 [H x W x 影格] 陣列的 MAT 檔（Ctrl+O；也可把檔案拖入視窗）'),
    'Open a recording, or drop a file here': ('打开一个记录，或把文件拖到这里', '開啟一個記錄，或把檔案拖曳到這裡'),
    "the recording's frame rate: sets the time axis and the playback speed (Play runs in real time); "
    "empty = frame numbers, playback at 10 frames/s (the video's own rate is filled in when it has one)":
        ('记录的帧率：决定时间轴和播放速度（按实际时间播放）；留空 = 使用帧序号，以每秒 10 帧播放（视频自带的帧率会自动填入）',
         '記錄的影格率：決定時間軸與播放速度（依實際時間播放）；留空 = 使用影格編號，以每秒 10 格播放（影片本身的影格率會自動填入）'),
    'Frame rate': ('帧率', '影格率'),
    'Export CSV': ('导出 CSV', '匯出 CSV'),
    'export all traces as a CSV file': ('把所有曲线导出为 CSV 文件', '把所有曲線匯出為 CSV 檔'),
    'Save PNG': ('保存 PNG', '儲存 PNG'),
    'save the window as a PNG image': ('把窗口保存为 PNG 图片', '把視窗儲存為 PNG 圖片'),
    'dark / light': ('深色 / 浅色', '深色 / 淺色'),
    'keyboard and mouse': ('键盘与鼠标', '鍵盤與滑鼠'),
    'Language': ('语言', '語言'),
    # tool bar
    'Original': ('原始', '原始'),
    'Relative change  dF/F': ('相对变化  dF/F', '相對變化  dF/F'),
    'Relative change: (frame - F0) / F0 beside the original frame':
        ('相对变化：(帧 - F0) / F0，显示在原始帧旁边', '相對變化：(影格 - F0) / F0，顯示在原始影格旁邊'),
    'Baseline': ('基线', '基線'),
    'frames of the player (1..N) whose mean is F0, e.g. 1-10  or  1-10, 200-210':
        ('取平均作为 F0 的帧（1..N），例如 1-10 或 1-10, 200-210', '取平均作為 F0 的影格（1..N），例如 1-10 或 1-10, 200-210'),
    'Rectangle': ('矩形', '矩形'),
    'Freehand': ('手绘', '手繪'),
    'Remove': ('删除', '刪除'),
    'remove ROIs': ('删除 ROI', '刪除 ROI'),
    'ROI: press the left button on the frame, drag to the opposite corner, release (Esc: cancel)':
        ('ROI：在画面上按住左键，拖到对角，松开（Esc：取消）', 'ROI：在畫面上按住左鍵，拖曳到對角，放開（Esc：取消）'),
    'ROI: press the left button on the frame, trace the outline, release to close it (Esc: cancel)':
        ('ROI：在画面上按住左键，描出轮廓，松开即闭合（Esc：取消）', 'ROI：在畫面上按住左鍵，描繪輪廓，放開即封閉（Esc：取消）'),
    # transport
    'previous frame (left arrow; Shift: 10 frames)': ('上一帧（左方向键；Shift：10 帧）', '上一格（左方向鍵；Shift：10 格）'),
    'next frame (right arrow; Shift: 10 frames)': ('下一帧（右方向键；Shift：10 帧）', '下一格（右方向鍵；Shift：10 格）'),
    'play / pause (Space), in real time at the frame rate': ('播放 / 暂停（空格键），按帧率实时播放', '播放 / 暫停（空白鍵），依影格率即時播放'),
    'type a frame number': ('输入帧序号', '輸入影格編號'),
    'loop: start again at the end': ('循环：播完后从头开始', '循環：播完後從頭開始'),
    'play the sound of the video (at its own frame rate)': ('播放视频的声音（按视频自身的帧率）', '播放影片的聲音（依影片本身的影格率）'),
    'dF/F range %': ('dF/F 范围 %', 'dF/F 範圍 %'),
    'colour range of the relative change: auto, one number (symmetric), or two numbers (low high)':
        ('相对变化的颜色范围：auto、一个数（对称）或两个数（下限 上限）', '相對變化的色彩範圍：auto、一個數（對稱）或兩個數（下限 上限）'),
    'Colour map': ('颜色映射', '色彩對應'),
    'colour map of the relative change': ('相对变化的颜色映射', '相對變化的色彩對應'),
    'drag up or down: frame / traces': ('上下拖动：调整画面与曲线的大小', '上下拖曳：調整畫面與曲線的大小'),
    # help
    HELP_EN: ('<b>键盘与鼠标</b><br>左 / 右方向键：一帧（Shift：10 帧）<br>鼠标滚轮：逐帧滚动<br>空格键：播放 / 暂停<br>'
              'Home / End：第一帧 / 最后一帧<br>拖动滑块：每一帧都流畅显示<br>点击曲线：跳到该时刻<br>'
              '拖动滑块上方的边界：调整画面与曲线的大小<br>把文件拖入窗口：打开它<br>Esc 或右键：取消绘制 ROI<br>'
              'Ctrl + 鼠标滚轮：以鼠标所指处为中心放大 / 缩小<br>放大后：拖动可移动画面；双击或 Ctrl+0：显示整帧',
              '<b>鍵盤與滑鼠</b><br>左 / 右方向鍵：一格（Shift：10 格）<br>滑鼠滾輪：逐格捲動<br>空白鍵：播放 / 暫停<br>'
              'Home / End：第一格 / 最後一格<br>拖曳滑桿：每一格都流暢顯示<br>點擊曲線：跳到該時刻<br>'
              '拖曳滑桿上方的邊界：調整畫面與曲線的大小<br>把檔案拖入視窗：開啟它<br>Esc 或右鍵：取消繪製 ROI<br>'
              'Ctrl + 滑鼠滾輪：以滑鼠所指處為中心放大 / 縮小<br>放大後：拖曳可移動畫面；按兩下或 Ctrl+0：顯示整格'),
    # opening
    'SciPlayer: choose a recording': ('SciPlayer：选择记录文件', 'SciPlayer：選擇記錄檔'),
    'Videos, TIFF stacks, MAT-files (%s);;All files (*.*)': ('视频、TIFF 序列、MAT 文件 (%s);;所有文件 (*.*)', '影片、TIFF 序列、MAT 檔 (%s);;所有檔案 (*.*)'),
    'File not found:\n%s': ('找不到文件：\n%s', '找不到檔案：\n%s'),
    'Could not open %s:\n%s': ('无法打开 %s：\n%s', '無法開啟 %s：\n%s'),
    'Which array holds the frames?': ('哪个数组包含这些帧？', '哪個陣列包含這些影格？'),
    'Reading %s ...': ('正在读取 %s …', '正在讀取 %s …'),
    'Opening %s ...': ('正在打开 %s …', '正在開啟 %s …'),
    'Cancel': ('取消', '取消'),
    'Not enough memory to read %s.': ('内存不足，无法读取 %s。', '記憶體不足，無法讀取 %s。'),
    # the info line
    '%d x %d px': ('%d × %d 像素', '%d × %d 像素'),
    'colour': ('彩色', '彩色'),
    '%d frames': ('%d 帧', '%d 格'),
    '%s in memory': ('%s，在内存中', '%s，在記憶體中'),
    'decoded from disk as shown (cache %s)': ('显示时从磁盘解码（缓存 %s）', '顯示時從磁碟解碼（快取 %s）'),
    'reduced: %s': ('已缩减：%s', '已縮減：%s'),
    'smooth scrubbing ready': ('流畅拖动已就绪', '流暢拖曳已就緒'),
    'Preparing smooth scrubbing': ('正在准备流畅拖动', '正在準備流暢拖曳'),
    'Smooth scrubbing ready': ('流畅拖动已就绪', '流暢拖曳已就緒'),
    'a few seconds left': ('还需几秒', '還需幾秒'),
    'about %d s left': ('约还需 %d 秒', '約還需 %d 秒'),
    'about %d min left': ('约还需 %d 分钟', '約還需 %d 分鐘'),
    'estimating the time ...': ('正在估算时间 …', '正在估算時間 …'),
    'the video can be used meanwhile': ('期间可正常使用视频', '期間可正常使用影片'),
    'sound: %s': ('声音：%s', '聲音：%s'),
    'Traces written: %s': ('曲线已保存：%s', '曲線已儲存：%s'),
    # the title
    'frame %d / %d': ('第 %d / %d 帧', '第 %d / %d 格'),
    '(recorded frame %d)': ('（原始第 %d 帧）', '（原始第 %d 格）'),
    '[baseline]': ('[基线]', '[基線]'),
    '(key frame while dragging)': ('（拖动中：关键帧）', '（拖曳中：關鍵格）'),
    # sound
    'no sound track in this recording': ('此记录没有声音轨', '此記錄沒有聲音軌'),
    'sound off: %s': ('无声音：%s', '無聲音：%s'),
    'play the sound of the video (%s)': ('播放视频的声音（%s）', '播放影片的聲音（%s）'),
    "sound plays only at the video's own frame rate (%s Hz), with every frame":
        ('只有按视频自身的帧率（%s Hz）逐帧播放时才有声音', '只有依影片本身的影格率（%s Hz）逐格播放時才有聲音'),
    'no sound track': ('没有声音轨', '沒有聲音軌'),
    'no sound device (%s)': ('没有声音设备（%s）', '沒有聲音裝置（%s）'),
    'the sound device does not open (%s)': ('声音设备无法打开（%s）', '聲音裝置無法開啟（%s）'),
    # traces
    'whole frame': ('全帧', '全畫面'),
    'time (s)': ('时间 (s)', '時間 (s)'),
    'recorded frame': ('原始帧序号', '原始影格編號'),
    'computing the trace (one pass through the recording) ... %d %%': ('正在计算曲线（把记录完整读一遍）… %d %%', '正在計算曲線（把記錄完整讀一遍）… %d %%'),
    'Computing the traces failed:\n%s': ('计算曲线失败：\n%s', '計算曲線失敗：\n%s'),
    'Averaging the baseline frames ...': ('正在平均基线帧 …', '正在平均基線影格 …'),
    'Frame %d cannot be shown:\n%s': ('无法显示第 %d 帧：\n%s', '無法顯示第 %d 格：\n%s'),
    # ROIs
    'ROI rectangle: press the left button on the frame, drag to the opposite corner, release   (Esc: cancel)':
        ('ROI 矩形：在画面上按住左键，拖到对角，松开   （Esc：取消）', 'ROI 矩形：在畫面上按住左鍵，拖曳到對角，放開   （Esc：取消）'),
    'ROI freehand: press the left button on the frame, trace the outline, release to close it   (Esc: cancel)':
        ('ROI 手绘：在画面上按住左键，描出轮廓，松开即闭合   （Esc：取消）', 'ROI 手繪：在畫面上按住左鍵，描繪輪廓，放開即封閉   （Esc：取消）'),
    'Too small - draw again.   ': ('太小了，请重新画。   ', '太小了，請重新畫。   '),
    'The ROI holds no pixel.': ('这个 ROI 不含任何像素。', '這個 ROI 不含任何像素。'),
    'There is no ROI to remove.': ('没有可删除的 ROI。', '沒有可刪除的 ROI。'),
    'Remove ROI': ('删除 ROI', '刪除 ROI'),
    'Remove which ROI(s)?': ('删除哪些 ROI？', '刪除哪些 ROI？'),
    # export, save
    'Export the traces': ('导出曲线', '匯出曲線'),
    'The traces are still being computed ...': ('曲线仍在计算中 …', '曲線仍在計算中 …'),
    'The traces are not ready yet; export again in a moment.': ('曲线尚未就绪，请稍后再导出。', '曲線尚未就緒，請稍後再匯出。'),
    'Cannot write %s:\n%s': ('无法写入 %s：\n%s', '無法寫入 %s：\n%s'),
    'Save the view': ('保存画面', '儲存畫面'),
    'Something went wrong:\n\n%s\n\n(details in %s)': ('出现错误：\n\n%s\n\n（详情见 %s）', '發生錯誤：\n\n%s\n\n（詳情見 %s）'),
}
