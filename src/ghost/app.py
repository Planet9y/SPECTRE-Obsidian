"""GHOST desktop application."""
from __future__ import annotations
import csv
import os
import sys
from collections import deque
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QRectF
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QLinearGradient, QRadialGradient, QPainterPath
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QStackedWidget, QFileDialog, QTextEdit, QFrame, QSplitter, QMessageBox, QProgressBar, QGridLayout, QScrollArea, QSizePolicy, QGraphicsDropShadowEffect)
import pyqtgraph as pg
from .monitor import Sampler
from .storage import History
from .diagnostics import resolve, ping, port_exposure

STYLE = """
QWidget { background: #070b13; color: #eaf2ff; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow { background: #070b13; }
QLabel { background: transparent; border: none; }
QFrame#side { background: #0b111d; border: 1px solid #202d40; border-radius: 20px; }
QFrame#panel { background: #101927; border: 1px solid #24354a; border-radius: 18px; }
QFrame#card { background: #101b29; border: 1px solid #263a4d; border-radius: 17px; }
QFrame#alert { background: #111e2c; border: 1px solid #293e51; border-radius: 12px; }
QFrame#hero { background: #0d1b27; border: 1px solid #24675f; border-radius: 21px; }
QFrame#row { background: #111e2c; border: none; border-radius: 9px; }
QPushButton { background: #142331; border: 1px solid #2a4051; border-radius: 11px; padding: 12px 15px; text-align: left; color: #d2e2ef; font-size: 12px; font-weight: 600; }
QPushButton:hover { background: #1b3440; border-color: #49ddc3; color: #ffffff; }
QPushButton:checked { background: #143e3c; border: 1px solid #37e5c4; color: #8fffe7; }
QPushButton#action { background: #17695c; border: 1px solid #39e9c5; color: #f4fffc; }
QPushButton#tool { background: #172b3b; padding: 13px 15px; }
QLineEdit, QTextEdit { background: #101e2d; border: 1px solid #2b4054; border-radius: 11px; padding: 12px; selection-background-color: #267d75; }
QLineEdit:focus { border-color: #52e7d0; }
QTableWidget { background: #0e1927; alternate-background-color: #142436; border: 1px solid #27394d; border-radius: 12px; gridline-color: #1c2e3e; selection-background-color: #21675f; }
QTableWidget::item { padding: 8px; }
QHeaderView::section { background: #172a3a; color: #a1c4d4; padding: 12px; border: none; border-right: 1px solid #263b4c; font-weight: 700; }
QStatusBar { background: #0b1420; color: #86a7b7; border-top: 1px solid #24384a; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: #0d1722; width: 9px; }
QScrollBar::handle:vertical { background: #315367; border-radius: 4px; min-height: 28px; }
QProgressBar { background: #243747; border: none; border-radius: 4px; height: 7px; text-align: center; }
QProgressBar::chunk { background: #38e2be; border-radius: 4px; }
"""

class AmbientHero(QFrame):
    """A painted ambient field; no external images, fonts, or network dependencies."""
    def __init__(self):
        super().__init__(); self.setObjectName('hero'); self.setMinimumHeight(160)
    def paintEvent(self, event):
        super().paintEvent(event)
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w,h=self.width(),self.height()
        painter.setClipRect(2,2,w-4,h-4)
        glow=QRadialGradient(w*.86,h*.46,w*.43)
        glow.setColorAt(0,QColor(21,172,151,85)); glow.setColorAt(.42,QColor(20,103,118,33)); glow.setColorAt(1,QColor(12,25,40,0))
        painter.fillRect(self.rect(),glow)
        for i in range(5):
            path=QPainterPath(); x0=w*.65; y0=h*(.62+i*.075)
            path.moveTo(x0,y0)
            path.cubicTo(w*.77,h*(.05+i*.06),w*.88,h*(1.0-i*.12),w*1.04,h*(.20+i*.12))
            painter.setPen(QPen(QColor(40,238,204,max(18,78-i*14)),1.1)); painter.drawPath(path)
        painter.end()

class RingGauge(QWidget):
    def __init__(self, color='#43e7c6', parent=None):
        super().__init__(parent); self.percent=0; self.tint=QColor(color); self.setFixedSize(78,78)
    def setValue(self, value): self.percent=max(0,min(100,float(value))); self.update()
    def paintEvent(self, event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=QRectF(9,9,60,60)
        p.setPen(QPen(QColor('#263a49'),8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); p.drawArc(rect,0,360*16)
        p.setPen(QPen(self.tint,8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); p.drawArc(rect,90*16,-int(360*16*self.percent/100))
        p.setPen(QColor('#e9f9fa')); font=p.font(); font.setPixelSize(16); font.setBold(True); p.setFont(font)
        p.drawText(rect,Qt.AlignmentFlag.AlignCenter,f'{self.percent:.0f}%'); p.end()

class MetricTile(QFrame):
    def __init__(self,title,icon,color,ring=False):
        super().__init__(); self.setObjectName('card'); self.setMinimumHeight(154)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
        layout=QVBoxLayout(self); layout.setContentsMargins(19,16,19,15); layout.setSpacing(10)
        header=QHBoxLayout(); header.addWidget(label(icon,21,color,True)); header.addWidget(label(title.upper(),11,'#9db5c7',True)); header.addStretch()
        self.tag=label('LIVE',9,color,True); header.addWidget(self.tag); layout.addLayout(header)
        middle=QHBoxLayout(); values=QVBoxLayout(); values.setSpacing(5)
        self.value=label('—',26,'#f5fcff',True); values.addWidget(self.value)
        self.detail=label('Collecting telemetry',10,'#7895a7'); values.addWidget(self.detail)
        middle.addLayout(values,1)
        self.gauge=RingGauge(color) if ring else None
        if self.gauge: middle.addWidget(self.gauge)
        layout.addLayout(middle)
        self.bar=None; self.spark=None
        if ring:
            self.bar=QProgressBar(); self.bar.setRange(0,100); self.bar.setTextVisible(False)
            self.bar.setStyleSheet(f'QProgressBar::chunk {{background:{color};border-radius:4px;}}')
            layout.addWidget(self.bar)
        else:
            self.spark=tiny_plot(35); layout.addWidget(self.spark)
            self.curve=self.spark.plot(pen=pg.mkPen(color,width=2.2))



def panel(title, subtitle=None):
    frame=QFrame(); frame.setObjectName('panel')
    outer=QVBoxLayout(frame); outer.setContentsMargins(17,15,17,15); outer.setSpacing(10)
    heading=QHBoxLayout(); heading.addWidget(label(title,14,'#f0fffb',True)); heading.addStretch()
    if subtitle: heading.addWidget(label(subtitle,10,'#75a4a9'))
    outer.addLayout(heading)
    return frame, outer

def tiny_plot(height=62):
    plot=pg.PlotWidget(); plot.setFixedHeight(height); plot.setBackground(None)
    plot.setMouseEnabled(x=False,y=False); plot.hideAxis('left'); plot.hideAxis('bottom')
    plot.getPlotItem().hideButtons(); plot.setMenuEnabled(False)
    plot.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
    return plot

class Worker(QThread):
    ready = Signal(object)
    failed = Signal(str)
    def run(self):
        sampler = Sampler()
        while not self.isInterruptionRequested():
            try: self.ready.emit(sampler.sample())
            except Exception as e: self.failed.emit(str(e))
            self.msleep(2000)

class Diagnostic(QThread):
    ready = Signal(str)
    def __init__(self, operation, host):
        super().__init__(); self.operation, self.host = operation, host
    def run(self):
        try:
            result = '\n'.join(resolve(self.host)) if self.operation == 'DNS' else ping(self.host)
            self.ready.emit(result or 'No result')
        except Exception as exc: self.ready.emit(f'Error: {exc}')

def label(text, size=12, color='#e7edf8', bold=False):
    w = QLabel(text); w.setStyleSheet(f'color:{color}; font-size:{size}px; font-weight:{700 if bold else 400};'); return w

def card(title):
    frame = QFrame(); frame.setObjectName('card'); layout = QVBoxLayout(frame); layout.setContentsMargins(20, 18, 20, 18); layout.setSpacing(9)
    layout.addWidget(label('●  '+title, 11, '#75c8bd', True)); value = label('—', 27, '#f1fffc', True); layout.addWidget(value)
    return frame, value

def table(columns):
    w = QTableWidget(0, len(columns)); w.setHorizontalHeaderLabels(columns); w.setAlternatingRowColors(True); w.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); w.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    w.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); w.verticalHeader().hide(); w.setSortingEnabled(True)
    return w

def fill_table(widget, rows):
    """Refresh a table without losing user filters, sorting or selection."""
    sort_col = widget.horizontalHeader().sortIndicatorSection()
    sort_order = widget.horizontalHeader().sortIndicatorOrder()
    selected = []
    for item in widget.selectedItems():
        if item.column() == 0:
            selected.append(tuple(widget.item(item.row(), c).text() if widget.item(item.row(), c) else '' for c in range(widget.columnCount())))
    scroll = widget.verticalScrollBar().value()
    widget.setUpdatesEnabled(False)
    widget.setSortingEnabled(False)
    widget.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            item = QTableWidgetItem(str(val if val is not None else '—'))
            if isinstance(val, (int, float)): item.setData(Qt.ItemDataRole.EditRole, val)
            widget.setItem(r, c, item)
    widget.setSortingEnabled(True)
    if sort_col >= 0:
        widget.sortItems(sort_col, sort_order)
    query = getattr(widget, '_filter_input', None)
    needle = query.text().casefold().strip() if query else ''
    for r in range(widget.rowCount()):
        cells = tuple(widget.item(r, c).text() if widget.item(r, c) else '' for c in range(widget.columnCount()))
        widget.setRowHidden(r, bool(needle) and not any(needle in value.casefold() for value in cells))
        if cells in selected:
            widget.selectRow(r)
    widget.verticalScrollBar().setValue(scroll)
    widget.setUpdatesEnabled(True)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SPECTRE 5.0 | Nocturne'); self.resize(1580, 960); self.setMinimumSize(1120, 740)
        if sys.platform == 'win32':
            try:
                import ctypes
                hwnd=int(self.winId()); enabled=ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd,20,ctypes.byref(enabled),ctypes.sizeof(enabled))
                caption=ctypes.c_int(0x00130B07)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd,35,ctypes.byref(caption),ctypes.sizeof(caption))
            except (OSError,AttributeError): pass
        icon_path = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2])) / 'assets' / 'spectre.ico'
        if icon_path.exists(): self.setWindowIcon(QIcon(str(icon_path)))
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'GHOST'
        self.history = History(base / 'history.db')
        self.worker = Worker(); self.worker.ready.connect(self.update_snapshot); self.worker.failed.connect(self.show_error)
        self.latest = None; self.diag = None; self.paused = False
        self.uploads, self.downloads, self.cpu_series = deque(maxlen=90), deque(maxlen=90), deque(maxlen=90)
        shell = QWidget(); self.setCentralWidget(shell)
        horizontal = QHBoxLayout(shell); horizontal.setContentsMargins(16,16,16,16); horizontal.setSpacing(20)
        side = QFrame(); side.setObjectName('side'); side.setFixedWidth(244)
        nav = QVBoxLayout(side); nav.setContentsMargins(15,24,15,18); nav.setSpacing(9)
        brandrow=QHBoxLayout(); brandrow.addWidget(label('◈',33,'#36edc1',True)); brand=label('SPECTRE',27,'#f3fffc',True); brand.setObjectName('brand'); brandrow.addWidget(brand); brandrow.addStretch()
        nav.addLayout(brandrow); nav.addWidget(label('N E T W O R K   I N T E L L I G E N C E',8,'#7aabb0'))
        nav.addSpacing(38); nav.addWidget(label('WORKSPACE',10,'#5c9d9b',True)); nav.addSpacing(8)
        self.stack = QStackedWidget(); self.nav_buttons=[]
        pages = [('Overview', self.overview), ('Connections', self.connections_page), ('History', self.history_page), ('Processes', self.processes_page), ('Listening ports', self.ports_page), ('Insights', self.insights_page), ('Diagnostics', self.diagnostics_page)]
        icons=['▦','⇄','◷','▤','◉','⬡','⌁']
        for idx, (name, build) in enumerate(pages):
            b=QPushButton(icons[idx]+'     '+name); b.setMinimumHeight(48); b.setCheckable(True)
            b.clicked.connect(lambda checked, i=idx: self.navigate(i)); nav.addWidget(b); self.nav_buttons.append(b)
            page=QWidget(); self.stack.addWidget(page); build(page)
        nav.addStretch()
        state=QFrame(); state.setObjectName('panel'); st=QVBoxLayout(state); st.setContentsMargins(11,12,11,12)
        st.addWidget(label('●  MONITORING ONLINE',11,'#38e7ae',True)); st.addWidget(label('LOCAL  /  READ-ONLY',10,'#84a8aa'))
        nav.addWidget(state)
        self.pause_button=QPushButton('Ⅱ   Pause monitoring'); self.pause_button.setObjectName('action'); self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self.toggle_pause); nav.addWidget(self.pause_button)
        nav.addWidget(label('SPECTRE 5.0  •  NOCTURNE',10,'#668d92'))
        horizontal.addWidget(side); horizontal.addWidget(self.stack, 1)
        self.statusBar().showMessage('Starting monitor…'); self.navigate(0); self.worker.start()
        self.refresh_history = QTimer(self); self.refresh_history.timeout.connect(self.update_history); self.refresh_history.start(5000)
        self.last_processes = []

    def toggle_pause(self, paused):
        self.paused = paused
        self.pause_button.setText('▶  Resume monitoring' if paused else 'Ⅱ  Pause monitoring')
        self.live_pill.setText('Ⅱ  PAUSED' if paused else '●  LIVE  /  2s')
        self.statusBar().showMessage('Live display paused; monitoring continues' if paused else 'Live display resumed')

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for i,b in enumerate(self.nav_buttons): b.setChecked(i==index)
        if index==2: self.update_history()

    def page_layout(self, page, title, subtitle):
        v=QVBoxLayout(page); v.setContentsMargins(8, 7, 8, 7); v.setSpacing(13)
        v.addWidget(label(title.upper(), 27, '#effffb', True)); v.addWidget(label(subtitle, 12, '#83b2b8')); return v

    def overview(self, page):
        root=QVBoxLayout(page); root.setContentsMargins(0,0,0,0)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content=QWidget(); v=QVBoxLayout(content); v.setContentsMargins(5,6,12,16); v.setSpacing(17)
        header=QHBoxLayout(); heading=QVBoxLayout(); heading.setSpacing(5)
        heading.addWidget(label('OVERVIEW',12,'#49dfc0',True)); heading.addWidget(label('Your entire system. One view.',30,'#f2f8ff',True))
        heading.addWidget(label('Real-time performance, network activity and security signals',12,'#8aa6b9'))
        header.addLayout(heading); header.addStretch()
        self.live_pill=label('●  LIVE  /  2s',12,'#5df2c6',True); header.addWidget(self.live_pill); v.addLayout(header)
        hero=AmbientHero(); hl=QHBoxLayout(hero); hl.setContentsMargins(30,22,30,22)
        left=QVBoxLayout(); left.setSpacing(9)
        left.addWidget(label('S P E C T R E    /    C O M M A N D   D E C K',11,'#6ff2d6',True))
        left.addWidget(label('Visibility is power.',30,'#ffffff',True))
        left.addWidget(label('Local-first monitoring  •  Private by design  •  Read-only intelligence',12,'#acc7d0'))
        hl.addLayout(left,1)
        right=QVBoxLayout(); right.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.hero_connections=label('—',34,'#72ffe0',True); self.hero_connections.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self.hero_connections); sub=label('SOCKETS OBSERVED',10,'#9cc2c6',True); sub.setAlignment(Qt.AlignmentFlag.AlignRight); right.addWidget(sub)
        hl.addLayout(right); v.addWidget(hero)

        self.metrics={}; self.bars={}; self.sparks={}; self.tiles={}
        metrics=QGridLayout(); metrics.setHorizontalSpacing(13); metrics.setVerticalSpacing(13)
        definitions=[('CPU','◈','#48e6c2',True),('RAM','▤','#6b9fff',True),('DISK','▥','#ff728c',True),('GPU','⬡','#b38aff',True),('UPLOAD','↗','#41d9d2',False),('DOWNLOAD','↘','#ffb86c',False)]
        for i,(key,icon,color,ring) in enumerate(definitions):
            tile=MetricTile(key,icon,color,ring); metrics.addWidget(tile,i//3,i%3)
            self.tiles[key]=tile; self.metrics[key]=tile.value
            if tile.bar: self.bars[key]=tile.bar
            if tile.spark: self.sparks[key]=tile.curve
        v.addLayout(metrics)

        middle=QHBoxLayout(); middle.setSpacing(14)
        netframe,netbox=panel('NETWORK THROUGHPUT','LIVE TRAFFIC  /  KiB/s')
        netframe.setMinimumHeight(330)
        self.net_plot=pg.PlotWidget(); self.style_plot(self.net_plot)
        self.net_plot.setMinimumHeight(235); self.net_plot.setLabel('left','KiB/s')
        netbox.addWidget(self.net_plot,1)
        legend=QHBoxLayout(); legend.addWidget(label('●  UPLOAD',11,'#43e5c8',True)); legend.addWidget(label('●  DOWNLOAD',11,'#ffb86c',True)); legend.addStretch()
        netbox.addLayout(legend)
        self.up_line=self.net_plot.plot(pen=pg.mkPen('#43e5c8',width=2.8))
        self.down_line=self.net_plot.plot(pen=pg.mkPen('#ffb86c',width=2.8))
        self.net_plot.setDownsampling(mode='peak'); self.net_plot.setClipToView(True)
        middle.addWidget(netframe,7)
        security,secbox=panel('SECURITY SIGNALS','LIVE ADVISORIES')
        self.security_items=[]
        for _ in range(3):
            row=QFrame(); row.setObjectName('alert'); rr=QHBoxLayout(row); rr.setContentsMargins(15,14,15,14); rr.setSpacing(12)
            icon=label('●',21,'#38e7ae',True); rr.addWidget(icon)
            copy=QVBoxLayout(); copy.setSpacing(5)
            title=label('Waiting for telemetry',13,'#f0fffb',True); detail=label('Connecting to local sensors…',11,'#96b7bb')
            copy.addWidget(title); copy.addWidget(detail); rr.addLayout(copy,1); secbox.addWidget(row)
            self.security_items.append((icon,title,detail))
        secbox.addStretch(1); middle.addWidget(security,4); v.addLayout(middle)

        lower=QHBoxLayout(); lower.setSpacing(14)
        cpu_frame,cpu_box=panel('PROCESSOR ACTIVITY','CPU LOAD  /  %')
        self.cpu_plot=pg.PlotWidget(); self.style_plot(self.cpu_plot)
        self.cpu_plot.setMinimumHeight(190); self.cpu_plot.setYRange(0,100)
        self.cpu_line=self.cpu_plot.plot(pen=pg.mkPen('#72aaff',width=2.7)); cpu_box.addWidget(self.cpu_plot)
        lower.addWidget(cpu_frame,5)
        feed,feedbox=panel('ACTIVE CONNECTIONS','LATEST REMOTE ENDPOINTS')
        self.feed_rows=[]
        for _ in range(4):
            rowframe=QFrame(); rowframe.setObjectName('row'); row=QHBoxLayout(rowframe); row.setContentsMargins(12,10,12,10)
            name=label('Waiting…',12,'#f2fffd',True); endpoint=label('',10,'#86aabb'); endpoint.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(name,2); row.addWidget(endpoint,3); feedbox.addWidget(rowframe); self.feed_rows.append((name,endpoint))
        view=QPushButton('Explore all connections     ↗'); view.clicked.connect(lambda:self.navigate(1)); feedbox.addWidget(view)
        lower.addWidget(feed,5)
        quick,quickbox=panel('QUICK ACTIONS','TOOLS')
        for name,action in [('↗   Run ping test',lambda:self.quick_diagnostic('Ping')),('◎   DNS lookup',lambda:self.quick_diagnostic('DNS')),('⇄   Connection history',lambda:self.navigate(2))]:
            btn=QPushButton(name); btn.setObjectName('tool'); btn.clicked.connect(action); quickbox.addWidget(btn)
        quickbox.addStretch(1); lower.addWidget(quick,3); v.addLayout(lower)
        footer=QHBoxLayout(); self.summary=label('Collecting system telemetry…',11,'#9ac0c1'); footer.addWidget(self.summary,1)
        footer.addWidget(label('●  ON-DEVICE  /  READ ONLY',10,'#48d7ae',True)); v.addLayout(footer)
        scroll.setWidget(content); root.addWidget(scroll)

    @staticmethod
    def style_plot(plot):
        plot.setBackground(None); plot.showGrid(x=True,y=True,alpha=.09)
        plot.setMouseEnabled(x=False,y=False); plot.getPlotItem().hideButtons()
        plot.setMenuEnabled(False)
        for axis in ('left','bottom'):
            plot.getAxis(axis).setTextPen('#819eb0'); plot.getAxis(axis).setPen(pg.mkPen('#30485b'))
        plot.getPlotItem().setContentsMargins(4,5,8,5)

    def quick_diagnostic(self, op):
        self.navigate(6)
        if not self.host.text().strip(): self.host.setText('1.1.1.1' if op=='Ping' else 'example.com')
        self.run_diagnostic(op)

    def refresh_dashboard_details(self, snap):
        public=[c for c in snap.connections if c['scope']=='Public' and c['status']=='ESTABLISHED']
        listeners=[c for c in snap.connections if c['status']=='LISTEN']
        alerts=[]
        if snap.disk>=90: alerts.append(('!','Disk space running low',f'{snap.disk:.0f}% used. Free up storage.','#ff7d78'))
        if snap.memory>=90: alerts.append(('!','High memory utilization',f'{snap.memory:.0f}% RAM in use.','#ffbd62'))
        if snap.error: alerts.append(('!','Limited network visibility','Try administrator permissions.','#ffbd62'))
        alerts.extend([('●','Public connections',f'{len(public)} established public endpoints.','#61b6ff'),('✓','Active listeners',f'{len(listeners)} TCP listening sockets.','#41e4ac'),('✓','Read-only monitoring','No network changes are made.','#41e4ac')])
        for (icon,title,detail),(mark,heading,description,color) in zip(self.security_items,alerts):
            icon.setText(mark); icon.setStyleSheet(f'color:{color}; font-size:19px; font-weight:700; background:transparent;')
            title.setText(heading); detail.setText(description)
        live=[c for c in snap.connections if c['status']=='ESTABLISHED' and c['remote'] not in ('—','-')]
        for i,(name,endpoint) in enumerate(self.feed_rows):
            if i<len(live): name.setText(str(live[i]['name'])[:23]); endpoint.setText(str(live[i]['remote'])[:30])
            else: name.setText('—'); endpoint.setText('')
    def searchable(self, v, columns):
        query=QLineEdit(); query.setPlaceholderText('Filter rows by process, address, port, or status…'); v.addWidget(query)
        widget=table(columns); v.addWidget(widget,1)
        widget._filter_input = query
        query.textChanged.connect(lambda text: self.filter_rows(widget,text)); return widget

    def filter_rows(self, widget, text):
        needle=text.casefold().strip()
        for row in range(widget.rowCount()):
            widget.setRowHidden(row, bool(needle) and not any(needle in (widget.item(row,col).text().casefold() if widget.item(row,col) else '') for col in range(widget.columnCount())))

    def connections_page(self, page):
        v=self.page_layout(page,'Live connections','Inspect socket endpoints and owning processes; double-click a row for details')
        self.conn_table=self.searchable(v,['Process','PID','Protocol','Local endpoint','Remote endpoint','Scope','Status'])
        self.conn_table.cellDoubleClicked.connect(self.inspect_connection)
        self.inspector=QTextEdit(); self.inspector.setReadOnly(True); self.inspector.setFixedHeight(105); self.inspector.setPlaceholderText('Double-click a connection to inspect it'); v.addWidget(self.inspector)
        b=QPushButton('Export current connections to CSV'); b.clicked.connect(self.export_connections); v.addWidget(b)

    def history_page(self, page):
        v=self.page_layout(page,'Connection history','Recorded locally in SQLite • up to 25,000 recent events')
        self.hist_table=self.searchable(v,['Time','Event','Process','PID','Protocol','Local endpoint','Remote endpoint','Status'])
        b=QPushButton('Export history to CSV'); b.clicked.connect(self.export_history); v.addWidget(b)

    def processes_page(self, page):
        v=self.page_layout(page,'Processes','Running processes sorted by memory use')
        self.proc_table=self.searchable(v,['Process','PID','RAM (MiB)','Status'])
        self.proc_table.cellDoubleClicked.connect(self.inspect_process)
        self.proc_details=QTextEdit(); self.proc_details.setReadOnly(True); self.proc_details.setFixedHeight(115); self.proc_details.setPlaceholderText('Double-click a process for executable path and details'); v.addWidget(self.proc_details)

    def ports_page(self, page):
        v=self.page_layout(page,'Listening ports','A listener on all interfaces is worth reviewing, not automatically malicious')
        self.port_table=self.searchable(v,['Process','PID','Protocol','Local endpoint','Observation'])

    def diagnostics_page(self, page):
        v=self.page_layout(page,'Diagnostics','Basic DNS and ping tests. No scanning of external hosts.')
        row=QHBoxLayout(); self.host=QLineEdit(); self.host.setPlaceholderText('example.com or 1.1.1.1'); row.addWidget(self.host)
        for op in ('DNS','Ping'):
            b=QPushButton(op); b.clicked.connect(lambda checked, name=op: self.run_diagnostic(name)); row.addWidget(b)
        v.addLayout(row); v.addWidget(label('RESULTS  /  NETWORK TOOL OUTPUT', 13, '#67ddc8', True)); self.diag_output=QTextEdit(); self.diag_output.setReadOnly(True); v.addWidget(self.diag_output)


    def insights_page(self, page):
        v=self.page_layout(page,'Security & system insights','Read-only checks with context. Warnings are not malware verdicts.')
        v.addWidget(label('●  LIVE ASSESSMENT  •  UPDATES AUTOMATICALLY', 13, '#62e8cd', True)); self.insights_text=QTextEdit(); self.insights_text.setReadOnly(True); v.addWidget(self.insights_text,1)
        b=QPushButton('Refresh insights'); b.clicked.connect(self.refresh_insights); v.addWidget(b)

    def refresh_insights(self):
        snap=self.latest
        if not snap: return
        import psutil
        lines=['SPECTRE SYSTEM INSIGHTS', '='*55, '']
        disk=psutil.disk_usage('C:\\' if os.name=='nt' else '/')
        lines += [f'DISK  |  {disk.percent:.0f}% used, {disk.free/1073741824:.1f} GiB free',
                  'Review disk usage soon.' if disk.percent>=90 else 'Disk utilization is below the 90% advisory threshold.', '']
        public=[c for c in snap.connections if c['scope']=='Public' and c['status']=='ESTABLISHED']
        listeners=[c for c in snap.connections if c['status']=='LISTEN']
        wildcard=[c for c in listeners if c['local'].startswith(('0.0.0.0:', '[::]:', ':::'))]
        lines += [f'NETWORK  |  {len(public)} established public endpoints',
                  f'LISTENERS  |  {len(listeners)} TCP listeners, {len(wildcard)} bound to all interfaces',
                  'A wildcard bind does NOT prove internet exposure; firewall and router rules matter.', '']
        from collections import Counter
        counts=Counter(c['name'] for c in snap.connections if c['remote'] not in ('—','-'))
        lines += ['TOP PROCESSES BY REMOTE SOCKET COUNT']
        lines += [f'  {name}: {n} sockets' for name,n in counts.most_common(8)] or ['  None currently observed']
        lines += ['', 'TOP PROCESSES BY RAM']
        lines += [f"  {p['name']} (PID {p['pid']}): {p['ram']:.1f} MiB" for p in sorted(snap.processes,key=lambda x:x['ram'],reverse=True)[:8]]
        lines += ['', 'INTERPRETATION', 'This is an inventory and advisory tool, not antivirus software.',
                  'A public IP or unfamiliar process name alone does not establish malicious activity.']
        self.insights_text.setPlainText('\n'.join(lines))

    def inspect_process(self, row, col):
        import psutil
        try:
            pid=int(self.proc_table.item(row,1).text())
            p=psutil.Process(pid)
            with p.oneshot():
                details=[f'Name: {p.name()}', f'PID: {pid}', f'Executable: {p.exe()}',
                         f'Started: {__import__("datetime").datetime.fromtimestamp(p.create_time())}',
                         f'Memory: {p.memory_info().rss/1048576:.1f} MiB', f'Status: {p.status()}']
            self.proc_details.setPlainText('\n'.join(details))
        except (psutil.NoSuchProcess,psutil.AccessDenied,ValueError) as exc:
            self.proc_details.setPlainText(f'Process details unavailable: {exc}')

    def run_diagnostic(self, op):
        if self.diag and self.diag.isRunning(): return
        host=self.host.text().strip()
        if not host: self.diag_output.setPlainText('Enter a hostname or IP address.'); return
        self.diag_output.setPlainText(f'Running {op} for {host}…')
        self.diag=Diagnostic(op,host); self.diag.ready.connect(self.diag_output.setPlainText); self.diag.start()

    def update_snapshot(self, snap):
        self.latest=snap
        self.history.record(snap.timestamp,snap.connections)
        if self.paused: return
        self.metrics['CPU'].setText(f'{snap.cpu:.0f}%'); self.metrics['RAM'].setText(f'{snap.memory:.0f}%'); self.metrics['DISK'].setText(f'{snap.disk:.0f}%')
        self.metrics['UPLOAD'].setText(f'{snap.upload/1024:.1f} KiB/s'); self.metrics['DOWNLOAD'].setText(f'{snap.download/1024:.1f} KiB/s')
        self.metrics['GPU'].setText(f"{snap.gpu['load']:.0f}%  ·  {snap.gpu['temp']}°C" if snap.gpu else 'N/A')
        for key,value in [('CPU',snap.cpu),('RAM',snap.memory),('DISK',snap.disk),('GPU',snap.gpu['load'] if snap.gpu else 0)]:
            self.bars[key].setValue(int(value)); self.tiles[key].gauge.setValue(value)
        self.tiles['CPU'].detail.setText('Processor utilization')
        self.tiles['RAM'].detail.setText('Physical memory in use')
        self.tiles['DISK'].detail.setText('Primary disk capacity')
        self.tiles['GPU'].detail.setText(f"{snap.gpu['used']:,} / {snap.gpu['total']:,} MiB VRAM" if snap.gpu else 'GPU telemetry unavailable')
        self.tiles['UPLOAD'].detail.setText('Outgoing traffic')
        self.tiles['DOWNLOAD'].detail.setText('Incoming traffic')
        self.hero_connections.setText(f'{len(snap.connections):,}')
        self.summary.setText(f"GPU  {snap.gpu['used']} / {snap.gpu['total']} MiB VRAM  •  {snap.gpu['temp']}°C" if snap.gpu else 'GPU telemetry unavailable  •  NVIDIA nvidia-smi required')
        self.uploads.append(snap.upload/1024); self.downloads.append(snap.download/1024); self.cpu_series.append(snap.cpu)
        self.up_line.setData(list(self.uploads)); self.down_line.setData(list(self.downloads)); self.cpu_line.setData(list(self.cpu_series))
        self.sparks['UPLOAD'].setData(list(self.uploads)); self.sparks['DOWNLOAD'].setData(list(self.downloads))
        self.refresh_dashboard_details(snap)
        fill_table(self.conn_table, [[c[k] for k in ('name','pid','protocol','local','remote','scope','status')] for c in snap.connections])
        fill_table(self.proc_table, [[p[k] for k in ('name','pid','ram','status')] for p in sorted(snap.processes, key=lambda x:x['ram'], reverse=True)[:500]])
        # Respect the user's current sort choice on every refresh.
        fill_table(self.port_table, [[c['name'],c['pid'],c['protocol'],c['local'],port_exposure(c) or 'Bound to specific interface'] for c in snap.connections if c['status']=='LISTEN'])
        if self.stack.currentIndex()==5: self.refresh_insights()
        self.statusBar().showMessage(f"Updated {snap.timestamp}  •  {len(snap.connections)} sockets  •  {snap.error or 'Local read-only monitoring'}")

    def inspect_connection(self, row, col):
        values=[self.conn_table.item(row,i).text() for i in range(self.conn_table.columnCount())]
        self.inspector.setPlainText('\n'.join(f'{k}: {v}' for k,v in zip(['Process','PID','Protocol','Local','Remote','Scope','Status'],values))+'\n\nNote: IP address alone cannot establish whether a connection is malicious.')

    def update_history(self):
        if not self.paused and self.stack.currentIndex()==2: fill_table(self.hist_table,self.history.recent())

    def export_rows(self, columns, rows, default):
        path,_=QFileDialog.getSaveFileName(self,'Export CSV',default,'CSV files (*.csv)')
        if not path: return
        try:
            with open(path,'w',newline='',encoding='utf-8-sig') as f:
                writer=csv.writer(f); writer.writerow(columns); writer.writerows(rows)
            self.statusBar().showMessage(f'Exported {len(rows)} rows to {path}')
        except OSError as exc: QMessageBox.warning(self,'Export failed',str(exc))

    def export_connections(self):
        if self.latest:
            keys=['name','pid','protocol','local','remote','scope','status']
            self.export_rows(keys,[[c[k] for k in keys] for c in self.latest.connections],'spectre_connections.csv')

    def export_history(self): self.export_rows(['Time','Event','Process','PID','Protocol','Local','Remote','Status'],self.history.recent(25000),'spectre_history.csv')
    def show_error(self, error): self.statusBar().showMessage('Monitor error: '+error)
    def closeEvent(self, event):
        self.worker.requestInterruption(); self.worker.wait(6000)
        if self.diag and self.diag.isRunning(): self.diag.wait(13000)
        self.history.close(); super().closeEvent(event)

def main():
    app=QApplication(sys.argv); app.setStyleSheet(STYLE)
    icon_path=Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2])) / 'assets' / 'spectre.ico'
    if icon_path.exists(): app.setWindowIcon(QIcon(str(icon_path)))
    window=MainWindow(); window.show(); sys.exit(app.exec())
