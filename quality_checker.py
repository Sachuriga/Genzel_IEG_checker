import os
import glob
import re
from collections import Counter
import numpy as np
import pandas as pd
from PIL import Image
import sys
import random

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QComboBox, QFileDialog,
    QInputDialog, QSlider, QGroupBox, QSizePolicy, QAbstractItemView,
    QDialog, QLineEdit, QSpinBox, QDialogButtonBox, QMessageBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QBrush


SCORE_MAP = {'1': -2, '2': -1, '3': 0, '4': 1, '5': 2, '6': 'DISCARD'}

MASK_COLORS = {
    'Green':  (0, 255, 0),
    'Blue':   (0, 0, 255),
    'Yellow': (255, 255, 0),
    'Red':    (255, 0, 0),
}

LIST_COLOR_RANDOM = QColor('#c8e6c9')
LIST_COLOR_SCORED = QColor('#bbdefb')


# ------------------------------------------------------------------ #
#  Startup helpers                                                     #
# ------------------------------------------------------------------ #

def detect_rat_names(folder_path):
    tif_files = glob.glob(os.path.join(folder_path, "*.tif"))
    animal_re = re.compile(r'^[A-Za-z]{1,8}\d{4,}[A-Za-z0-9]*$')
    counts: Counter = Counter()
    for p in tif_files:
        name = os.path.splitext(os.path.basename(p))[0]
        for tok in re.split(r'[_\-\s]+', name):
            if animal_re.match(tok):
                counts[tok] += 1
    return [name for name, _ in counts.most_common()]


def _folder_tokens(folder_path, rat_name):
    tokens = set()
    for p in glob.glob(os.path.join(folder_path, f"*{rat_name}*.tif")):
        name = os.path.splitext(os.path.basename(p))[0]
        tokens.update(re.split(r'[_\-\s]+', name))
    return tokens


class RatSelectionDialog(QDialog):
    def __init__(self, rat_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Animal")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Detected animals in folder — select one or type a name below:"))
        self.list_widget = QListWidget()
        for name in rat_names:
            self.list_widget.addItem(name)
        if rat_names:
            self.list_widget.setCurrentRow(0)
        self.list_widget.currentTextChanged.connect(self._sync_edit)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)
        layout.addWidget(QLabel("Animal name:"))
        self.name_edit = QLineEdit(rat_names[0] if rat_names else "")
        layout.addWidget(self.name_edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _sync_edit(self, text):
        self.name_edit.setText(text)

    def get_name(self):
        return self.name_edit.text().strip()


# ------------------------------------------------------------------ #
#  Single-panel image window                                           #
# ------------------------------------------------------------------ #

class ImageViewWindow(QMainWindow):
    """One floating window showing a single image panel."""

    def __init__(self, title, img_arr, on_key_cb, cmap=None):
        super().__init__()
        self.setWindowTitle(title)
        self.figure = Figure(tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.setCentralWidget(self.canvas)
        self.ax = self.figure.add_axes([0, 0, 1, 1])
        self.ax.axis('off')
        self.im = self.ax.imshow(img_arr, cmap=cmap, aspect='equal')
        self.img_height, self.img_width = img_arr.shape[:2]
        self.canvas.mpl_connect('key_press_event', on_key_cb)
        self.canvas.mpl_connect('scroll_event', self._on_scroll)
        self.canvas.draw()

    def update_data(self, img_arr):
        self.im.set_data(img_arr)
        self.canvas.draw_idle()

    def apply_zoom(self, scale, cx, cy):
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        new_w = (xl[1] - xl[0]) * scale
        new_h = (yl[0] - yl[1]) * scale
        relx = (xl[1] - cx) / (xl[1] - xl[0])
        rely = (yl[0] - cy) / (yl[0] - yl[1])
        self.ax.set_xlim([cx - new_w * (1 - relx), cx + new_w * relx])
        self.ax.set_ylim([cy + new_h * (1 - rely), cy - new_h * rely])
        self.canvas.draw_idle()

    def reset_zoom(self):
        self.ax.set_xlim(-0.5, self.img_width - 0.5)
        self.ax.set_ylim(self.img_height - 0.5, -0.5)
        self.canvas.draw_idle()

    def _on_scroll(self, event):
        if event.inaxes != self.ax:
            return
        scale = 1 / 1.2 if event.button == 'up' else 1.2
        self.apply_zoom(scale, event.xdata, event.ydata)


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _make_range_row(label_text, lo_slider, lo_lbl, hi_slider, hi_lbl):
    """Build a two-row QVBoxLayout for a Lo/Hi slider pair."""
    box = QVBoxLayout()
    box.addWidget(QLabel(label_text))
    row_lo = QHBoxLayout()
    row_lo.addWidget(QLabel("Lo:"))
    row_lo.addWidget(lo_slider)
    row_lo.addWidget(lo_lbl)
    box.addLayout(row_lo)
    row_hi = QHBoxLayout()
    row_hi.addWidget(QLabel("Hi:"))
    row_hi.addWidget(hi_slider)
    row_hi.addWidget(hi_lbl)
    box.addLayout(row_hi)
    return box


# ------------------------------------------------------------------ #
#  Main reviewer window (list + controls)                              #
# ------------------------------------------------------------------ #

class ReviewerWindow(QMainWindow):
    def __init__(self, folder_path, rat_name, regions_file_path, cfos_folder=None):
        super().__init__()
        self.folder_path = folder_path
        self.rat_name = rat_name
        self.output_path = os.path.join(folder_path, f"{rat_name}_QC_Scores.xlsx")

        self.cfos_folder = cfos_folder
        self.main_channel_token = None
        self.cfos_channel_token = None
        if cfos_folder:
            self._detect_channel_tokens()

        self.results = []
        self.current_tif_path = None

        # raw float32 pixel arrays (unnormalized)
        self.tdt_raw: np.ndarray | None = None
        self.cfos_raw: np.ndarray | None = None
        self.tdt_raw_min = self.tdt_raw_max = 0
        self.cfos_raw_min = self.cfos_raw_max = 0

        self.contour_mask = None
        self.border_mask = None
        self.jpg_arr_gray = None
        self.img_height = self.img_width = 0
        self.mask_color = MASK_COLORS['Green']

        self.img_wins: dict[str, ImageViewWindow] = {}

        self._slider_timer = QTimer()
        self._slider_timer.setSingleShot(True)
        self._slider_timer.timeout.connect(self._apply_adjustments)

        self.target_regions_list = self._load_regions(regions_file_path)
        self.all_tif_files = sorted(glob.glob(
            os.path.join(folder_path, f"*{rat_name}*.tif")
        ))
        self.random_selected_paths = self._pick_random_paths()

        self._build_ui()
        self._populate_list()
        self.setWindowTitle(f"IEG Quality Checker — {rat_name}")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(screen.width() // 2, screen.height() // 2)
        self.show()
        self._advance_to_next_unscored()

    # ------------------------------------------------------------------ #
    #  Data helpers                                                        #
    # ------------------------------------------------------------------ #

    def _load_regions(self, path):
        try:
            df = pd.read_excel(path, header=None)
            lst = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
            lst.sort(key=len, reverse=True)
            return lst
        except Exception as e:
            print(f"Error reading Regions.xlsx: {e}")
            return []

    def extract_metadata(self, filename):
        name = os.path.splitext(filename)[0]
        tokens = re.split(r'[_\-\s]+', name)
        hemi = 'RH' if 'RH' in tokens else ('LH' if 'LH' in tokens else None)
        region = next((r for r in self.target_regions_list if r in tokens), None)
        return region, hemi

    def _find_jpg(self, tif_path):
        base = os.path.splitext(tif_path)[0]
        for ext in ('jpeg', 'jpg'):
            p = f"{base}_Object Predictions.{ext}"
            if os.path.exists(p):
                return p
        return None

    def _pick_random_paths(self):
        grouped = {}
        for p in self.all_tif_files:
            region, hemi = self.extract_metadata(os.path.basename(p))
            if region and hemi:
                grouped.setdefault(region, {'RH': [], 'LH': []})
                grouped[region][hemi].append(p)
        selected = set()
        for data in grouped.values():
            for lst in data.values():
                if lst:
                    chosen = random.choice(lst)
                    if self._find_jpg(chosen):
                        selected.add(chosen)
        return selected

    def _detect_channel_tokens(self):
        main_tokens = _folder_tokens(self.folder_path, self.rat_name)
        cfos_tokens = _folder_tokens(self.cfos_folder, self.rat_name)
        main_unique = main_tokens - cfos_tokens
        cfos_unique = cfos_tokens - main_tokens
        self.main_channel_token = max(main_unique, key=len) if main_unique else None
        self.cfos_channel_token = max(cfos_unique, key=len) if cfos_unique else None
        print(f"Channel tokens — main: {self.main_channel_token!r}, cfos: {self.cfos_channel_token!r}")

    def _find_cfos_tif(self, tif_path):
        if not self.cfos_folder or not self.main_channel_token or not self.cfos_channel_token:
            return None
        fname = os.path.basename(tif_path)
        cfos_fname = fname.replace(self.main_channel_token, self.cfos_channel_token, 1)
        cfos_path = os.path.join(self.cfos_folder, cfos_fname)
        return cfos_path if os.path.exists(cfos_path) else None

    @staticmethod
    def _load_raw(path):
        """Load a TIF and return a float32 2-D grayscale array (raw pixel values)."""
        img = Image.open(path)
        arr = np.array(img).astype(np.float32)
        if arr.ndim == 3:
            arr = arr.mean(axis=2)
        return arr

    # ------------------------------------------------------------------ #
    #  Normalization using current Lo/Hi sliders                           #
    # ------------------------------------------------------------------ #

    def _norm_tdt(self) -> np.ndarray:
        """Return uint8 gray (H,W) for tdTomato using current Lo/Hi."""
        lo = self.s_tdt_lo.value()
        hi = self.s_tdt_hi.value()
        if hi <= lo:
            return np.zeros((self.img_height, self.img_width), dtype=np.uint8)
        return np.clip((self.tdt_raw - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)

    def _norm_cfos(self) -> np.ndarray | None:
        """Return uint8 gray (H,W) for cfos using current Lo/Hi, or None."""
        if self.cfos_raw is None:
            return None
        lo = self.s_cfos_lo.value()
        hi = self.s_cfos_hi.value()
        if hi <= lo:
            return np.zeros((self.img_height, self.img_width), dtype=np.uint8)
        return np.clip((self.cfos_raw - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)

    # ------------------------------------------------------------------ #
    #  Morphological border computation                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _dilate(mask, w):
        result = mask.copy()
        for _ in range(w):
            result |= (np.roll(result,  1, 0) | np.roll(result, -1, 0) |
                       np.roll(result,  1, 1) | np.roll(result, -1, 1))
        return result

    @staticmethod
    def _erode(mask, w):
        result = mask.copy()
        for _ in range(w):
            result &= (np.roll(result,  1, 0) & np.roll(result, -1, 0) &
                       np.roll(result,  1, 1) & np.roll(result, -1, 1))
        return result

    def _recompute_border(self):
        if self.contour_mask is None:
            return
        if self.mask_type_combo.currentText() == 'Area':
            self.border_mask = self.contour_mask
        else:
            lw = self.lw_spinbox.value()
            self.border_mask = (
                self._dilate(self.contour_mask, lw) &
                ~self._erode(self.contour_mask, lw)
            )

    # ------------------------------------------------------------------ #
    #  UI construction                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_slider(lo, hi, val):
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    @staticmethod
    def _make_val_label(val):
        lbl = QLabel(str(val))
        lbl.setFixedWidth(60)
        return lbl

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        # ---- left: image list ---------------------------------------- #
        left_box = QGroupBox("All Images")
        left_box.setFixedWidth(260)
        left_vbox = QVBoxLayout(left_box)
        legend = QLabel(
            '<span style="background:#c8e6c9">&nbsp;&nbsp;</span> random selection&nbsp;&nbsp;'
            '<span style="background:#bbdefb">&nbsp;&nbsp;</span> scored'
        )
        legend.setTextFormat(Qt.RichText)
        left_vbox.addWidget(legend)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.setWordWrap(True)
        self.list_widget.currentItemChanged.connect(self._on_list_selection)
        left_vbox.addWidget(self.list_widget)
        outer.addWidget(left_box)

        # ---- right: controls ----------------------------------------- #
        right = QWidget()
        right_vbox = QVBoxLayout(right)
        right_vbox.setContentsMargins(0, 4, 0, 4)
        right_vbox.setSpacing(8)

        self.filename_label = QLabel("—")
        self.filename_label.setAlignment(Qt.AlignCenter)
        lf = QFont(); lf.setPointSize(9); lf.setBold(True)
        self.filename_label.setFont(lf)
        self.filename_label.setWordWrap(True)
        right_vbox.addWidget(self.filename_label)

        # mask controls
        mask_box = QGroupBox("Mask")
        mask_layout = QHBoxLayout(mask_box)
        mask_layout.addWidget(QLabel("Color:"))
        self.color_combo = QComboBox()
        for name in MASK_COLORS:
            self.color_combo.addItem(name)
        self.color_combo.setCurrentText('Green')
        self.color_combo.currentTextChanged.connect(self._on_color_changed)
        mask_layout.addWidget(self.color_combo)
        mask_layout.addSpacing(12)
        mask_layout.addWidget(QLabel("Type:"))
        self.mask_type_combo = QComboBox()
        self.mask_type_combo.addItems(['Outline', 'Area'])
        self.mask_type_combo.currentTextChanged.connect(self._on_mask_type_changed)
        mask_layout.addWidget(self.mask_type_combo)
        mask_layout.addSpacing(12)
        mask_layout.addWidget(QLabel("Width:"))
        self.lw_spinbox = QSpinBox()
        self.lw_spinbox.setRange(1, 8)
        self.lw_spinbox.setValue(1)
        self.lw_spinbox.setFixedWidth(50)
        self.lw_spinbox.valueChanged.connect(self._on_lw_changed)
        mask_layout.addWidget(self.lw_spinbox)
        mask_layout.addStretch()
        right_vbox.addWidget(mask_box)

        # ---- display range group ------------------------------------- #
        range_box = QGroupBox("Display Range (Min / Max)")
        range_vbox = QVBoxLayout(range_box)

        ch_main = self.main_channel_token or "tdTomato"
        ch_cfos = self.cfos_channel_token or "cfos"

        # tdTomato Lo
        self.s_tdt_lo = self._make_slider(0, 255, 0)
        self.lbl_tdt_lo = self._make_val_label(0)
        self.s_tdt_lo.valueChanged.connect(self._on_tdt_range)
        # tdTomato Hi
        self.s_tdt_hi = self._make_slider(0, 255, 255)
        self.lbl_tdt_hi = self._make_val_label(255)
        self.s_tdt_hi.valueChanged.connect(self._on_tdt_range)

        range_vbox.addLayout(
            _make_range_row(ch_main,
                            self.s_tdt_lo, self.lbl_tdt_lo,
                            self.s_tdt_hi, self.lbl_tdt_hi)
        )

        self.s_cfos_lo = self.s_cfos_hi = None
        self.lbl_cfos_lo = self.lbl_cfos_hi = None
        if self.cfos_folder:
            self.s_cfos_lo = self._make_slider(0, 255, 0)
            self.lbl_cfos_lo = self._make_val_label(0)
            self.s_cfos_lo.valueChanged.connect(self._on_cfos_range)
            self.s_cfos_hi = self._make_slider(0, 255, 255)
            self.lbl_cfos_hi = self._make_val_label(255)
            self.s_cfos_hi.valueChanged.connect(self._on_cfos_range)
            range_vbox.addLayout(
                _make_range_row(ch_cfos,
                                self.s_cfos_lo, self.lbl_cfos_lo,
                                self.s_cfos_hi, self.lbl_cfos_hi)
            )

        right_vbox.addWidget(range_box)

        # ---- image adjust (contrast / brightness) -------------------- #
        adj_box = QGroupBox("Image Adjust")
        adj_layout = QVBoxLayout(adj_box)

        row_c = QHBoxLayout()
        row_c.addWidget(QLabel("Contrast:"))
        self.s_contrast = QSlider(Qt.Horizontal)
        self.s_contrast.setRange(10, 300)
        self.s_contrast.setValue(100)
        self.lbl_contrast = QLabel("1.00×")
        self.lbl_contrast.setFixedWidth(44)
        self.s_contrast.valueChanged.connect(self._on_slider)
        row_c.addWidget(self.s_contrast)
        row_c.addWidget(self.lbl_contrast)
        adj_layout.addLayout(row_c)

        row_b = QHBoxLayout()
        row_b.addWidget(QLabel("Brightness:"))
        self.s_brightness = QSlider(Qt.Horizontal)
        self.s_brightness.setRange(-100, 100)
        self.s_brightness.setValue(0)
        self.lbl_brightness = QLabel("0")
        self.lbl_brightness.setFixedWidth(30)
        self.s_brightness.valueChanged.connect(self._on_slider)
        row_b.addWidget(self.s_brightness)
        row_b.addWidget(self.lbl_brightness)
        adj_layout.addLayout(row_b)

        right_vbox.addWidget(adj_box)

        # ---- alpha sliders (only when cfos folder loaded) ------------ #
        self.s_alpha_tdt = self.s_alpha_cfos = None
        self.lbl_alpha_tdt = self.lbl_alpha_cfos = None
        if self.cfos_folder:
            alpha_box = QGroupBox("Merge Alpha")
            alpha_layout = QVBoxLayout(alpha_box)

            row_t = QHBoxLayout()
            row_t.addWidget(QLabel(f"{ch_main}:"))
            self.s_alpha_tdt = QSlider(Qt.Horizontal)
            self.s_alpha_tdt.setRange(0, 100)
            self.s_alpha_tdt.setValue(100)
            self.lbl_alpha_tdt = QLabel("1.00")
            self.lbl_alpha_tdt.setFixedWidth(36)
            self.s_alpha_tdt.valueChanged.connect(self._on_slider)
            row_t.addWidget(self.s_alpha_tdt)
            row_t.addWidget(self.lbl_alpha_tdt)
            alpha_layout.addLayout(row_t)

            row_cf = QHBoxLayout()
            row_cf.addWidget(QLabel(f"{ch_cfos}:"))
            self.s_alpha_cfos = QSlider(Qt.Horizontal)
            self.s_alpha_cfos.setRange(0, 100)
            self.s_alpha_cfos.setValue(100)
            self.lbl_alpha_cfos = QLabel("1.00")
            self.lbl_alpha_cfos.setFixedWidth(36)
            self.s_alpha_cfos.valueChanged.connect(self._on_slider)
            row_cf.addWidget(self.s_alpha_cfos)
            row_cf.addWidget(self.lbl_alpha_cfos)
            alpha_layout.addLayout(row_cf)

            right_vbox.addWidget(alpha_box)

        hint = QLabel(
            "Score: 1=−2  2=−1  3=0  4=+1  5=+2  6=DISCARD\n"
            "Scroll / i / o = Zoom   r = Reset   Esc = Quit"
        )
        hint.setStyleSheet("color: #1a56db; font-weight: bold;")
        hint.setAlignment(Qt.AlignCenter)
        right_vbox.addWidget(hint)
        right_vbox.addStretch()
        outer.addWidget(right)

    def _populate_list(self):
        for tif_path in self.all_tif_files:
            fname = os.path.basename(tif_path)
            region, hemi = self.extract_metadata(fname)
            jpg = self._find_jpg(tif_path)
            display = f"[{hemi}] {region}\n{fname}" if (region and hemi) else fname
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole,     tif_path)
            item.setData(Qt.UserRole + 1, jpg)
            if tif_path in self.random_selected_paths:
                item.setBackground(QBrush(LIST_COLOR_RANDOM))
            if not jpg:
                item.setForeground(QBrush(QColor('#aaaaaa')))
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.list_widget.addItem(item)

    # ------------------------------------------------------------------ #
    #  Image loading & window management                                   #
    # ------------------------------------------------------------------ #

    def _close_all_image_windows(self):
        for w in self.img_wins.values():
            w.close()
        self.img_wins.clear()

    def _set_range_slider(self, s_lo, lbl_lo, s_hi, lbl_hi, raw_min, raw_max):
        """Update a Lo/Hi slider pair to the raw pixel range without triggering redraws."""
        for s in (s_lo, s_hi):
            s.blockSignals(True)
        s_lo.setRange(raw_min, raw_max)
        s_hi.setRange(raw_min, raw_max)
        s_lo.setValue(raw_min)
        s_hi.setValue(raw_max)
        lbl_lo.setText(str(raw_min))
        lbl_hi.setText(str(raw_max))
        for s in (s_lo, s_hi):
            s.blockSignals(False)

    def _load_image(self, tif_path, jpg_path):
        self.current_tif_path = tif_path
        fname = os.path.basename(tif_path)
        self.filename_label.setText(fname)

        try:
            tif_pil = Image.open(tif_path)
            self.tdt_raw = self._load_raw(tif_path)
            self.img_height, self.img_width = self.tdt_raw.shape[:2]
            self.tdt_raw_min = int(self.tdt_raw.min())
            self.tdt_raw_max = int(self.tdt_raw.max())
            self._set_range_slider(
                self.s_tdt_lo, self.lbl_tdt_lo,
                self.s_tdt_hi, self.lbl_tdt_hi,
                self.tdt_raw_min, self.tdt_raw_max,
            )

            jpg_img = Image.open(jpg_path).convert('L')
            if jpg_img.size != tif_pil.size:
                jpg_img = jpg_img.resize(tif_pil.size, Image.NEAREST)
            jpg_arr = np.array(jpg_img)
            self.jpg_arr_gray = jpg_arr
            self.contour_mask = jpg_arr > 127
            self._recompute_border()
        except Exception as e:
            print(f"Error loading {fname}: {e}")
            return

        # Load cfos
        self.cfos_raw = None
        cfos_path = self._find_cfos_tif(tif_path)
        if cfos_path:
            try:
                cfos = self._load_raw(cfos_path)
                if cfos.shape[:2] != (self.img_height, self.img_width):
                    cfos = np.array(
                        Image.fromarray(cfos.astype(np.float32)).resize(
                            (self.img_width, self.img_height), Image.NEAREST
                        )
                    )
                self.cfos_raw = cfos
                self.cfos_raw_min = int(cfos.min())
                self.cfos_raw_max = int(cfos.max())
                if self.s_cfos_lo is not None:
                    self._set_range_slider(
                        self.s_cfos_lo, self.lbl_cfos_lo,
                        self.s_cfos_hi, self.lbl_cfos_hi,
                        self.cfos_raw_min, self.cfos_raw_max,
                    )
            except Exception as e:
                print(f"Error loading cfos {os.path.basename(cfos_path)}: {e}")
        elif self.cfos_folder:
            print(f"No matching cfos TIF for {fname}")

        self._open_image_windows(fname)
        self.activateWindow()

    def _open_image_windows(self, fname):
        self._close_all_image_windows()
        adjusted, overlay = self._composite()
        region, hemi = self.extract_metadata(fname)
        loc = f"{region or '?'} ({hemi or '?'})"
        ch_main = self.main_channel_token or 'tdTomato'
        ch_cfos = self.cfos_channel_token or 'cfos'

        screen = QApplication.primaryScreen().availableGeometry()
        win_w = screen.width()  // 2
        win_h = screen.height() // 2
        step = 30

        idx = 0
        def win(title, img, cmap=None):
            nonlocal idx
            w = ImageViewWindow(title, img, self._on_key, cmap=cmap)
            x = screen.x() + (idx * step) % (screen.width()  // 4)
            y = screen.y() + (idx * step) % (screen.height() // 4)
            w.setGeometry(x, y, win_w, win_h)
            w.show()
            idx += 1
            return w

        self.img_wins['overlap'] = win(f"Overlap — {loc} — {fname}", overlay)
        self.img_wins['jpeg']    = win(f"Prediction Mask — {fname}", self.jpg_arr_gray, cmap='gray')
        self.img_wins['tif']     = win(f"{ch_main} — {fname}", adjusted)

        if self.cfos_folder and self.cfos_raw is not None:
            cfos_gray = self._norm_cfos()
            cfos_rgb = np.zeros((self.img_height, self.img_width, 3), dtype=np.uint8)
            cfos_rgb[:, :, 1] = cfos_gray
            merge = self._compute_merge()
            self.img_wins['cfos']  = win(f"{ch_cfos} — {fname}", cfos_rgb)
            self.img_wins['merge'] = win(
                f"Merge ({ch_main}=red  {ch_cfos}=green) — {fname}", merge
            )

    # ------------------------------------------------------------------ #
    #  Compositing                                                         #
    # ------------------------------------------------------------------ #

    def _composite(self):
        """Return (adjusted, overlay) uint8 RGB using current Lo/Hi + contrast/brightness."""
        gray = self._norm_tdt()
        c = self.s_contrast.value() / 100.0
        b = self.s_brightness.value()
        gray_adj = np.clip(gray.astype(np.float32) * c + b, 0, 255).astype(np.uint8)

        rgb = np.zeros((self.img_height, self.img_width, 3), dtype=np.uint8)
        rgb[:, :, 0] = gray_adj          # red channel → tdTomato

        overlay = rgb.copy()
        r, g, bv = self.mask_color
        overlay[self.border_mask, 0] = r
        overlay[self.border_mask, 1] = g
        overlay[self.border_mask, 2] = bv
        return rgb, overlay

    def _compute_merge(self):
        alpha_tdt  = self.s_alpha_tdt.value()  / 100.0 if self.s_alpha_tdt  else 1.0
        alpha_cfos = self.s_alpha_cfos.value() / 100.0 if self.s_alpha_cfos else 1.0
        merge = np.zeros((self.img_height, self.img_width, 3), dtype=np.float32)
        merge[:, :, 0] = self._norm_tdt().astype(np.float32) * alpha_tdt
        cfos_gray = self._norm_cfos()
        if cfos_gray is not None:
            merge[:, :, 1] = cfos_gray.astype(np.float32) * alpha_cfos
        return np.clip(merge, 0, 255).astype(np.uint8)

    # ------------------------------------------------------------------ #
    #  Event handlers                                                      #
    # ------------------------------------------------------------------ #

    def _on_list_selection(self, current, _):
        if current is None:
            return
        tif_path = current.data(Qt.UserRole)
        jpg_path = current.data(Qt.UserRole + 1)
        if tif_path and jpg_path:
            self._load_image(tif_path, jpg_path)

    def _on_tdt_range(self):
        """Enforce Lo < Hi then schedule redraw."""
        lo, hi = self.s_tdt_lo.value(), self.s_tdt_hi.value()
        if lo >= hi:
            # push the other slider away
            if self.sender() is self.s_tdt_lo:
                self.s_tdt_hi.setValue(lo + 1)
            else:
                self.s_tdt_lo.setValue(hi - 1)
        self.lbl_tdt_lo.setText(str(self.s_tdt_lo.value()))
        self.lbl_tdt_hi.setText(str(self.s_tdt_hi.value()))
        self._slider_timer.start(50)

    def _on_cfos_range(self):
        lo, hi = self.s_cfos_lo.value(), self.s_cfos_hi.value()
        if lo >= hi:
            if self.sender() is self.s_cfos_lo:
                self.s_cfos_hi.setValue(lo + 1)
            else:
                self.s_cfos_lo.setValue(hi - 1)
        self.lbl_cfos_lo.setText(str(self.s_cfos_lo.value()))
        self.lbl_cfos_hi.setText(str(self.s_cfos_hi.value()))
        self._slider_timer.start(50)

    def _on_slider(self):
        self.lbl_contrast.setText(f"{self.s_contrast.value() / 100:.2f}×")
        self.lbl_brightness.setText(str(self.s_brightness.value()))
        if self.lbl_alpha_tdt:
            self.lbl_alpha_tdt.setText(f"{self.s_alpha_tdt.value() / 100:.2f}")
        if self.lbl_alpha_cfos:
            self.lbl_alpha_cfos.setText(f"{self.s_alpha_cfos.value() / 100:.2f}")
        self._slider_timer.start(50)

    def _apply_adjustments(self):
        if self.tdt_raw is None or not self.img_wins:
            return
        adjusted, overlay = self._composite()
        if 'overlap' in self.img_wins:
            self.img_wins['overlap'].update_data(overlay)
        if 'tif' in self.img_wins:
            self.img_wins['tif'].update_data(adjusted)
        if 'cfos' in self.img_wins and self.cfos_raw is not None:
            cfos_gray = self._norm_cfos()
            cfos_rgb = np.zeros((self.img_height, self.img_width, 3), dtype=np.uint8)
            cfos_rgb[:, :, 1] = cfos_gray
            self.img_wins['cfos'].update_data(cfos_rgb)
        if 'merge' in self.img_wins:
            self.img_wins['merge'].update_data(self._compute_merge())

    def _on_color_changed(self, name):
        self.mask_color = MASK_COLORS[name]
        self._apply_adjustments()

    def _on_mask_type_changed(self, mask_type):
        self.lw_spinbox.setEnabled(mask_type == 'Outline')
        if self.contour_mask is not None:
            self._recompute_border()
            self._apply_adjustments()

    def _on_lw_changed(self):
        if self.contour_mask is not None:
            self._recompute_border()
            self._apply_adjustments()

    def _on_key(self, event):
        if event.key in SCORE_MAP:
            self._record_score(SCORE_MAP[event.key], event.key)
        elif event.key == 'r':
            self._reset_view()
        elif event.key in ('i', 'o') and self.img_wins:
            scale = 1 / 1.2 if event.key == 'i' else 1.2
            cx, cy = self.img_width / 2, self.img_height / 2
            for w in self.img_wins.values():
                w.apply_zoom(scale, cx, cy)
        elif event.key == 'escape':
            self.close()

    def _reset_view(self):
        for w in self.img_wins.values():
            w.reset_zoom()
        self.s_contrast.setValue(100)
        self.s_brightness.setValue(0)
        if self.s_alpha_tdt:
            self.s_alpha_tdt.setValue(100)
        if self.s_alpha_cfos:
            self.s_alpha_cfos.setValue(100)
        # reset Lo/Hi to full range
        if self.tdt_raw is not None:
            self._set_range_slider(
                self.s_tdt_lo, self.lbl_tdt_lo,
                self.s_tdt_hi, self.lbl_tdt_hi,
                self.tdt_raw_min, self.tdt_raw_max,
            )
        if self.cfos_raw is not None and self.s_cfos_lo is not None:
            self._set_range_slider(
                self.s_cfos_lo, self.lbl_cfos_lo,
                self.s_cfos_hi, self.lbl_cfos_hi,
                self.cfos_raw_min, self.cfos_raw_max,
            )
        self._apply_adjustments()

    def closeEvent(self, event):
        self._close_all_image_windows()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    #  Scoring & progress                                                  #
    # ------------------------------------------------------------------ #

    def _record_score(self, score, raw_key):
        if self.current_tif_path is None:
            return
        fname = os.path.basename(self.current_tif_path)
        existing_idx = next(
            (i for i, r in enumerate(self.results) if r['Filename'] == fname), None
        )
        if existing_idx is not None:
            old_score = self.results[existing_idx]['Score']
            reply = QMessageBox.question(
                self, "Image Already Scored",
                f'"{fname}" was already scored as {old_score}.\n\nOverwrite with {score}?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self.results.pop(existing_idx)
        region, hemi = self.extract_metadata(fname)
        self.results.append({
            'Filename':   fname,
            'Rat_ID':     self.rat_name,
            'Region':     region or 'Unknown',
            'Hemisphere': hemi or 'Unknown',
            'Score':      score,
            'Raw_Input':  raw_key,
        })
        print(f"Scored {score} for {fname}")
        self._save_progress()
        self._mark_current_scored()
        self._advance_to_next_unscored()

    def _mark_current_scored(self):
        item = self.list_widget.currentItem()
        if item:
            item.setBackground(QBrush(LIST_COLOR_SCORED))

    def _advance_to_next_unscored(self):
        scored = {r['Filename'] for r in self.results}
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not (item.flags() & Qt.ItemIsEnabled):
                continue
            tif_path = item.data(Qt.UserRole)
            if (tif_path in self.random_selected_paths and
                    os.path.basename(tif_path) not in scored):
                self.list_widget.setCurrentItem(item)
                return
        if self.results:
            print(f"\nAll randomly selected images reviewed. Total scored: {len(self.results)}")

    def _save_progress(self):
        if not self.results:
            return
        try:
            cols = ['Filename', 'Rat_ID', 'Region', 'Hemisphere', 'Score', 'Raw_Input']
            pd.DataFrame(self.results)[cols].to_excel(self.output_path, index=False)
        except Exception as e:
            print(f"WARNING: Save failed: {e}")


# ------------------------------------------------------------------ #
#  Entry point                                                         #
# ------------------------------------------------------------------ #

class ImageReviewer:
    def __init__(self):
        if getattr(sys, 'frozen', False):
            script_dir = os.path.dirname(sys.executable)
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))

        regions_file = os.path.join(script_dir, 'Regions.xlsx')
        if not os.path.exists(regions_file):
            print(f"CRITICAL ERROR: 'Regions.xlsx' not found in {script_dir}")
            return

        app = QApplication.instance() or QApplication(sys.argv)

        folder_path = QFileDialog.getExistingDirectory(None, "Select Image Folder")
        if not folder_path:
            return

        rat_names = detect_rat_names(folder_path)
        if rat_names:
            dlg = RatSelectionDialog(rat_names)
            if dlg.exec_() != QDialog.Accepted:
                return
            rat_name = dlg.get_name()
        else:
            rat_name, ok = QInputDialog.getText(
                None, "Input Required", "Enter Animal Name (e.g., Rat461707):"
            )
            if not ok:
                return
            rat_name = rat_name.strip()

        if not rat_name:
            return

        cfos_folder = None
        reply = QMessageBox.question(
            None, "Optional: Second Channel Folder",
            "Load a second folder for the cfos channel?\n"
            "(Opens extra windows for cfos and merge.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            cfos_folder = QFileDialog.getExistingDirectory(None, "Select cfos Folder")
            if not cfos_folder:
                cfos_folder = None

        window = ReviewerWindow(folder_path, rat_name, regions_file, cfos_folder=cfos_folder)
        window.show()
        sys.exit(app.exec_())


if __name__ == '__main__':
    ImageReviewer()
