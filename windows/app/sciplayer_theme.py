"""SciPlayer - look: flat, minimal, in a dark and a light theme (colours of the logo: deep navy,
cyan to blue). Icons are drawn here as vector shapes, so they stay sharp at any screen scaling and
need no image files; the style sheet styles every Qt widget of the window and its dialogs."""
import os
import tempfile

from PySide6 import QtCore, QtGui
from PySide6.QtCore import Qt, QPointF, QRectF

THEMES = {
    'dark': dict(
        bg='#0d1322', surface='#141c2e', field='#1a2438', hover='#212c44', pressed='#2a3752',
        border='#28344d', text='#e6ecf5', muted='#8c99b0', disabled='#4c5871',
        accent='#1e9bff', accent_hover='#45adff', accent_soft='#16304f', accent2='#16d0ff',
        track='#2a3650', handle='#0d1322', canvas='#080c16', plot='#0f1626',
        axis='#3a4762', grid=0.10, trace0='#d6deea', shade=(40, 54, 82, 255), cursor='#e6ecf5',
        warn='#ff9a4d', hint=(120, 132, 152)),
    'light': dict(
        bg='#f6f8fb', surface='#ffffff', field='#ffffff', hover='#e9eef6', pressed='#dce4f0',
        border='#d5dce7', text='#18202e', muted='#677389', disabled='#b3bccb',
        accent='#0a7cff', accent_hover='#3394ff', accent_soft='#dcebff', accent2='#00b4e6',
        track='#d7deea', handle='#ffffff', canvas='#eef1f6', plot='#ffffff',
        axis='#c4ccd9', grid=0.12, trace0='#2b3445', shade=(226, 232, 242, 255), cursor='#18202e',
        warn='#e8590c', hint=(140, 150, 166)),
}

# ROI colours that read well on both themes
ROI_COLOURS = [(47, 155, 255), (255, 122, 69), (54, 196, 143), (180, 124, 255), (255, 197, 61), (34, 211, 238), (245, 72, 127)]


def system_theme():
    try:
        from PySide6.QtGui import QGuiApplication
        return 'dark' if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else 'light'
    except Exception:
        return 'dark'


# ---------------------------------------------------------------------------
# icons
# ---------------------------------------------------------------------------
def _path(name):
    """the icon NAME as (path, filled) in a 24 x 24 box"""
    p = QtGui.QPainterPath()
    fill = False
    if name == 'play':
        p.moveTo(8.5, 5.5); p.lineTo(19, 12); p.lineTo(8.5, 18.5); p.closeSubpath(); fill = True
    elif name == 'pause':
        p.addRoundedRect(QRectF(7, 5.5, 3.6, 13), 1.2, 1.2); p.addRoundedRect(QRectF(13.4, 5.5, 3.6, 13), 1.2, 1.2); fill = True
    elif name == 'prev':
        p.addRoundedRect(QRectF(5.5, 6, 2.4, 12), 1, 1); p.moveTo(18.5, 6.5); p.lineTo(9.5, 12); p.lineTo(18.5, 17.5); p.closeSubpath(); fill = True
    elif name == 'next':
        p.addRoundedRect(QRectF(16.1, 6, 2.4, 12), 1, 1); p.moveTo(5.5, 6.5); p.lineTo(14.5, 12); p.lineTo(5.5, 17.5); p.closeSubpath(); fill = True
    elif name == 'loop':
        p.moveTo(4.5, 11); p.arcTo(QRectF(4.5, 6.5, 15, 11), 180, -180)
        p.moveTo(19.5, 13); p.arcTo(QRectF(4.5, 6.5, 15, 11), 0, -180)
        p.moveTo(16.8, 9.2); p.lineTo(19.5, 12.2); p.lineTo(21.8, 9)
        p.moveTo(7.2, 14.8); p.lineTo(4.5, 11.8); p.lineTo(2.2, 15)
    elif name in ('sound', 'mute'):
        p.moveTo(4, 9.5); p.lineTo(7.5, 9.5); p.lineTo(12, 5.5); p.lineTo(12, 18.5); p.lineTo(7.5, 14.5); p.lineTo(4, 14.5); p.closeSubpath()
        if name == 'sound':
            p.moveTo(15, 9); p.quadTo(17, 12, 15, 15); p.moveTo(17.5, 6.5); p.quadTo(21.5, 12, 17.5, 17.5)
        else:
            p.moveTo(15.5, 9.5); p.lineTo(20.5, 14.5); p.moveTo(20.5, 9.5); p.lineTo(15.5, 14.5)
    elif name == 'rect':
        p.addRoundedRect(QRectF(4.5, 6, 15, 12), 2, 2)
    elif name == 'free':
        p.moveTo(6, 15); p.cubicTo(2, 9, 9, 3.5, 14, 6); p.cubicTo(20, 9, 22, 15, 16, 17.5)
        p.cubicTo(12, 19.5, 9, 18.5, 6, 15)
    elif name == 'remove':
        p.moveTo(5, 7.5); p.lineTo(19, 7.5); p.moveTo(9.5, 7.5); p.lineTo(10, 5); p.lineTo(14, 5); p.lineTo(14.5, 7.5)
        p.moveTo(6.8, 7.5); p.lineTo(7.8, 19); p.lineTo(16.2, 19); p.lineTo(17.2, 7.5)
        p.moveTo(10.5, 10.5); p.lineTo(10.7, 16); p.moveTo(13.5, 10.5); p.lineTo(13.3, 16)
    elif name == 'open':
        p.moveTo(3.5, 7); p.lineTo(3.5, 18); p.lineTo(20.5, 18); p.lineTo(20.5, 9); p.lineTo(11.5, 9)
        p.lineTo(9.5, 6.5); p.lineTo(4.5, 6.5); p.closeSubpath()
    elif name == 'export':
        p.moveTo(12, 4.5); p.lineTo(12, 14.5); p.moveTo(8, 10.5); p.lineTo(12, 14.5); p.lineTo(16, 10.5)
        p.moveTo(4.5, 15); p.lineTo(4.5, 19.5); p.lineTo(19.5, 19.5); p.lineTo(19.5, 15)
    elif name == 'save':
        p.addRoundedRect(QRectF(3.5, 7, 17, 12), 2.5, 2.5); p.moveTo(9, 7); p.lineTo(10.2, 4.8); p.lineTo(13.8, 4.8); p.lineTo(15, 7)
        p.addEllipse(QPointF(12, 13), 3.2, 3.2)
    elif name == 'moon':
        a = QtGui.QPainterPath(); a.addEllipse(QPointF(12, 12), 7.5, 7.5)
        b = QtGui.QPainterPath(); b.addEllipse(QPointF(15.5, 8.5), 6.5, 6.5)
        p = a.subtracted(b); fill = True
    elif name == 'sun':
        p.addEllipse(QPointF(12, 12), 3.8, 3.8)
        import math
        for i in range(8):
            t = i * math.pi / 4
            p.moveTo(12 + 6.2 * math.cos(t), 12 + 6.2 * math.sin(t)); p.lineTo(12 + 8.6 * math.cos(t), 12 + 8.6 * math.sin(t))
    elif name == 'help':
        p.addEllipse(QPointF(12, 12), 8.5, 8.5)
        p.moveTo(9.6, 9.8); p.cubicTo(9.6, 6.6, 14.6, 6.6, 14.6, 9.6); p.cubicTo(14.6, 11.6, 12, 11.8, 12, 13.8)
        p.moveTo(12, 16.4); p.lineTo(12, 16.6)
    elif name == 'globe':
        p.addEllipse(QPointF(12, 12), 8.5, 8.5); p.addEllipse(QPointF(12, 12), 3.8, 8.5)
        p.moveTo(3.5, 12); p.lineTo(20.5, 12); p.moveTo(5, 7.5); p.lineTo(19, 7.5); p.moveTo(5, 16.5); p.lineTo(19, 16.5)
    elif name == 'arrow':
        p.moveTo(6, 9.5); p.lineTo(12, 15); p.lineTo(18, 9.5)
    elif name == 'grip':
        p.moveTo(2, 12); p.lineTo(22, 12)
    return p, fill


def pixmap(name, color, size=20, stroke=1.7):
    dpr = 2.0
    pm = QtGui.QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    qp = QtGui.QPainter(pm)
    qp.setRenderHint(QtGui.QPainter.Antialiasing)
    qp.scale(size / 24.0, size / 24.0)
    path, fill = _path(name)
    col = QtGui.QColor(color)
    if fill:
        qp.setPen(Qt.NoPen)
        qp.setBrush(col)
    else:
        pen = QtGui.QPen(col, stroke * 24.0 / size * (size / 20.0))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        qp.setPen(pen)
        qp.setBrush(Qt.NoBrush)
    qp.drawPath(path)
    qp.end()
    return pm


def icon(name, color, on_color=None, off_name=None, size=20):
    """an icon; ON_COLOR: its checked state in that colour (OFF_NAME: another shape when unchecked)"""
    ic = QtGui.QIcon()
    ic.addPixmap(pixmap(off_name or name, color, size), QtGui.QIcon.Normal, QtGui.QIcon.Off)
    ic.addPixmap(pixmap(name, on_color or color, size), QtGui.QIcon.Normal, QtGui.QIcon.On)
    return ic


# ---------------------------------------------------------------------------
# the style sheet
# ---------------------------------------------------------------------------
_TMP = None


def _asset(name, color, size=12):
    """a small icon written as a PNG (style sheets take images only from files)"""
    global _TMP
    if _TMP is None:
        _TMP = tempfile.mkdtemp(prefix='sciplayer_')
    path = os.path.join(_TMP, '%s_%s.png' % (name, color.strip('#')))
    if not os.path.exists(path):
        pixmap(name, color, size, stroke=2.0).save(path)
    return path.replace('\\', '/')


def style_sheet(t):
    arrow = _asset('arrow', t['muted'])
    grip = _asset('grip', t['muted'], 24)
    return '''
* {{ font-size: 10pt; }}
QMainWindow, QDialog, QWidget#central {{ background: {bg}; }}
QWidget {{ color: {text}; }}
QLabel {{ background: transparent; }}
QLabel#muted {{ color: {muted}; }}
QLabel#name {{ font-weight: 600; font-size: 11pt; }}
QLabel#title {{ font-size: 11pt; font-weight: 600; color: {text}; padding: 2px 0px; }}
QLabel:disabled {{ color: {disabled}; }}

QPushButton, QToolButton {{ background: transparent; border: none; border-radius: 7px; padding: 5px 10px; color: {text}; }}
QPushButton:hover, QToolButton:hover {{ background: {hover}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {pressed}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {disabled}; }}
QToolButton:checked {{ color: {accent}; }}
QToolButton#icon {{ padding: 5px; }}
QPushButton#primary {{ background: {accent}; color: #ffffff; font-weight: 600; padding: 6px 14px; }}
QPushButton#primary:hover {{ background: {accent_hover}; }}
QPushButton#play {{ background: {accent}; border-radius: 18px; padding: 0px;
    min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; }}
QPushButton#play:hover {{ background: {accent_hover}; }}
QPushButton#play:disabled {{ background: {field}; }}

QLineEdit {{ background: {field}; border: 1px solid {border}; border-radius: 7px; padding: 4px 8px;
    selection-background-color: {accent}; selection-color: #ffffff; }}
QLineEdit:hover {{ border-color: {muted}; }}
QLineEdit:focus {{ border: 1px solid {accent}; }}
QLineEdit:disabled {{ color: {disabled}; border-color: {field}; }}

QComboBox {{ background: {field}; border: 1px solid {border}; border-radius: 7px; padding: 4px 26px 4px 9px; }}
QComboBox:hover {{ border-color: {muted}; }}
QComboBox:disabled {{ color: {disabled}; border-color: {field}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({arrow}); width: 11px; height: 11px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 4px;
    selection-background-color: {accent_soft}; selection-color: {text}; outline: 0; }}

QFrame#strip {{ background: {accent_soft}; border-radius: 8px; }}
QLabel#strip {{ color: {text}; font-weight: 600; }}
QProgressBar#strip {{ background: {track}; border-radius: 3px; min-height: 6px; max-height: 6px; }}
QProgressBar#strip::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent2}, stop:1 {accent}); border-radius: 3px; }}
QFrame#segment {{ background: {field}; border: 1px solid {border}; border-radius: 9px; }}
QFrame#segment QToolButton {{ border-radius: 6px; padding: 4px 14px; color: {muted}; margin: 2px; }}
QFrame#segment QToolButton:hover {{ color: {text}; background: {hover}; }}
QFrame#segment QToolButton:checked {{ background: {accent}; color: #ffffff; }}
QFrame#segment QToolButton:disabled {{ color: {disabled}; }}

QSlider {{ min-height: 22px; }}
QSlider::groove:horizontal {{ height: 4px; background: {track}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent2}, stop:1 {accent});
    border-radius: 2px; }}
QSlider::sub-page:horizontal:disabled {{ background: {track}; }}
QSlider::handle:horizontal {{ background: {handle}; border: 2px solid {accent}; width: 12px; height: 12px;
    margin: -6px 0px; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: {accent}; }}
QSlider::handle:horizontal:disabled {{ border-color: {track}; }}

QSplitter::handle:vertical {{ background: transparent; image: url({grip}); }}
QSplitter::handle:vertical:hover {{ background: {accent_soft}; }}

QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 5px 7px; }}
QProgressBar {{ background: {field}; border: none; border-radius: 4px; text-align: center; color: {text}; min-height: 8px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
QListWidget {{ background: {field}; border: 1px solid {border}; border-radius: 7px; padding: 4px; outline: 0; }}
QListWidget::item {{ padding: 4px 6px; border-radius: 5px; }}
QListWidget::item:selected {{ background: {accent_soft}; color: {text}; }}
QMessageBox, QInputDialog, QProgressDialog {{ background: {bg}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 5px 16px; border-radius: 5px; }}
QMenu::item:selected {{ background: {accent_soft}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; }}
'''.format(arrow=arrow, grip=grip, **t)
