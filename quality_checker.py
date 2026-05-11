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
    QDialog, QPushButton, QLineEdit, QSpinBox, QDialogButtonBox, QMessageBox,
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

LIST_COLOR_RANDOM = QColor('#c8e6c9')   # light green — randomly selected
LIST_COLOR_SCORED = QColor('#bbdefb')   # light blue  — already scored


# ------------------------------------------------------------------ #
#  Startup helpers                                                     #
# ------------------------------------------------------------------ #

def detect_rat_names(folder_path):
    """Scan TIF filenames and return tokens that look like animal IDs.

    Pattern: 1-8 letters followed by 4+ digits (e.g. Rat461707, Mouse2345).
    Results are sorted by number of files they appear in (most common first).
    """
    tif_files = glob.glob(os.path.join(folder_path, "*.tif"))
    animal_re = re.compile(r'^[A-Za-z]{1,8}\d{4,}[A-Za-z0-9]*$')
    counts: Counter = Counter()
    for p in tif_files:
        name = os.path.splitext(os.path.basename(p))[0]
        for tok in re.split(r'[_\-\s]+', name):
            if animal_re.match(tok):
                counts[tok] += 1
    return [name for name, _ in counts.most_common()]


class RatSelectionDialog(QDialog):
    """Pop-up that lists detected animal names and lets the user pick or type one."""

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
#  Main reviewer window                                                #
# ------------------------------------------------------------------ #

class ReviewerWindow(QMainWindow):
    def __init__(self, folder_path, rat_name, regions_file_path):
        super().__init__()
        self.folder_path = folder_path
        self.rat_name = rat_name
        self.output_path = os.path.join(folder_path, f"{rat_name}_QC_Scores.xlsx")

        self.results = []
        self.current_tif_path = None
        self.original_tif_arr = None
        self.contour_mask = None    # raw binary prediction mask
        self.border_mask = None     # derived mask used for overlay (outline or area)
        self.jpg_arr_gray = None
        self.img_height = self.img_width = 0
        self.mask_color = MASK_COLORS['Green']
        self.ax_dict = {}
        self.im_overlap = self.im_jpeg = self.im_tif = None

        # Debounce: only redraw 50 ms after the last slider tick
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
        self.showMaximized()
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
        """Update self.border_mask from contour_mask + current UI settings."""
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

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        # ---- left: image list ---------------------------------------- #
        left_box = QGroupBox("All Images")
        left_box.setFixedWidth(250)
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

        # ---- right: canvas + controls --------------------------------- #
        right = QWidget()
        right_vbox = QVBoxLayout(right)
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.setSpacing(2)

        # filename label
        self.filename_label = QLabel("—")
        self.filename_label.setAlignment(Qt.AlignCenter)
        lf = QFont()
        lf.setPointSize(9)
        lf.setBold(True)
        self.filename_label.setFont(lf)
        self.filename_label.setWordWrap(True)
        right_vbox.addWidget(self.filename_label)

        # matplotlib canvas
        self.figure = Figure(figsize=(13, 8))
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.mpl_connect('key_press_event', self._on_key)
        self.canvas.mpl_connect('scroll_event', self._on_scroll)
        right_vbox.addWidget(self.canvas)

        # --- controls row 1: mask options + sliders ------------------- #
        row1 = QWidget()
        r1 = QHBoxLayout(row1)
        r1.setContentsMargins(6, 2, 6, 2)

        r1.addWidget(QLabel("Mask color:"))
        self.color_combo = QComboBox()
        for name in MASK_COLORS:
            self.color_combo.addItem(name)
        self.color_combo.setCurrentText('Green')
        self.color_combo.currentTextChanged.connect(self._on_color_changed)
        r1.addWidget(self.color_combo)

        r1.addSpacing(12)
        r1.addWidget(QLabel("Mask type:"))
        self.mask_type_combo = QComboBox()
        self.mask_type_combo.addItems(['Outline', 'Area'])
        self.mask_type_combo.currentTextChanged.connect(self._on_mask_type_changed)
        r1.addWidget(self.mask_type_combo)

        r1.addSpacing(12)
        r1.addWidget(QLabel("Border width:"))
        self.lw_spinbox = QSpinBox()
        self.lw_spinbox.setRange(1, 8)
        self.lw_spinbox.setValue(1)
        self.lw_spinbox.setFixedWidth(50)
        self.lw_spinbox.setToolTip("Width in pixels of the outline (1 = ~2 px, 8 = ~16 px)")
        self.lw_spinbox.valueChanged.connect(self._on_lw_changed)
        r1.addWidget(self.lw_spinbox)

        r1.addSpacing(16)
        r1.addWidget(QLabel("Contrast:"))
        self.s_contrast = QSlider(Qt.Horizontal)
        self.s_contrast.setRange(10, 300)
        self.s_contrast.setValue(100)
        self.s_contrast.setFixedWidth(150)
        self.lbl_contrast = QLabel("1.00×")
        self.lbl_contrast.setFixedWidth(44)
        self.s_contrast.valueChanged.connect(self._on_slider)
        r1.addWidget(self.s_contrast)
        r1.addWidget(self.lbl_contrast)

        r1.addSpacing(16)
        r1.addWidget(QLabel("Brightness:"))
        self.s_brightness = QSlider(Qt.Horizontal)
        self.s_brightness.setRange(-100, 100)
        self.s_brightness.setValue(0)
        self.s_brightness.setFixedWidth(150)
        self.lbl_brightness = QLabel("0")
        self.lbl_brightness.setFixedWidth(30)
        self.s_brightness.valueChanged.connect(self._on_slider)
        r1.addWidget(self.s_brightness)
        r1.addWidget(self.lbl_brightness)
        r1.addStretch()
        right_vbox.addWidget(row1)

        # --- controls row 2: score / keyboard hint -------------------- #
        row2 = QWidget()
        r2 = QHBoxLayout(row2)
        r2.setContentsMargins(6, 0, 6, 2)
        hint = QLabel(
            "Score: 1=−2  2=−1  3=0  4=+1  5=+2  6=DISCARD   |   "
            "Scroll / i / o = Zoom   r = Reset   Esc = Quit"
        )
        hint.setStyleSheet("color: #1a56db; font-weight: bold;")
        r2.addWidget(hint)
        r2.addStretch()
        right_vbox.addWidget(row2)

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
    #  Image loading & compositing                                         #
    # ------------------------------------------------------------------ #

    def _load_image(self, tif_path, jpg_path):
        self.current_tif_path = tif_path
        self.filename_label.setText(os.path.basename(tif_path))
        try:
            tif_raw = Image.open(tif_path)
            # Single-channel fluorescence TIFs carry no colour metadata.
            # Map pixel values to the red channel so the display matches
            # the Red LUT used by ImageJ/FIJI.
            if tif_raw.mode in ('L', 'I', 'F', 'P') or ';' in tif_raw.mode:
                raw = np.array(tif_raw).astype(np.float32)
                lo, hi = raw.min(), raw.max()
                if hi > lo:
                    gray = ((raw - lo) / (hi - lo) * 255).astype(np.uint8)
                else:
                    gray = np.zeros_like(raw, dtype=np.uint8)
                rgb = np.zeros((gray.shape[0], gray.shape[1], 3), dtype=np.uint8)
                rgb[:, :, 0] = gray
                self.original_tif_arr = rgb
            else:
                self.original_tif_arr = np.array(tif_raw.convert('RGB'))

            jpg_img = Image.open(jpg_path).convert('L')
            if jpg_img.size != tif_raw.size:
                jpg_img = jpg_img.resize(tif_raw.size, Image.NEAREST)
            jpg_arr = np.array(jpg_img)
            self.jpg_arr_gray = jpg_arr
            self.contour_mask = jpg_arr > 127
            self._recompute_border()

            self.img_height, self.img_width = self.original_tif_arr.shape[:2]
        except Exception as e:
            print(f"Error loading {os.path.basename(tif_path)}: {e}")
            return

        self._build_figure()
        self.canvas.setFocus()

    def _composite(self):
        """Return (adjusted, overlay) uint8 RGB arrays."""
        c = self.s_contrast.value() / 100.0
        b = self.s_brightness.value()
        adjusted = np.clip(
            self.original_tif_arr.astype(np.float32) * c + b, 0, 255
        ).astype(np.uint8)
        overlay = adjusted.copy()
        r, g, bv = self.mask_color
        overlay[self.border_mask, 0] = r
        overlay[self.border_mask, 1] = g
        overlay[self.border_mask, 2] = bv
        return adjusted, overlay

    def _build_figure(self):
        self.figure.clear()
        layout = [['overlap', 'jpeg'], ['overlap', 'tif']]
        self.ax_dict = self.figure.subplot_mosaic(layout)
        self.figure.subplots_adjust(
            left=0.01, right=0.99, top=0.96, bottom=0.01,
            wspace=0.08, hspace=0.08,
        )
        adjusted, overlay = self._composite()

        self.im_overlap = self.ax_dict['overlap'].imshow(overlay)
        region, hemi = self.extract_metadata(os.path.basename(self.current_tif_path))
        self.ax_dict['overlap'].set_title(
            f"Region: {region or '?'} ({hemi or '?'})",
            fontsize=11, color='blue', fontweight='bold',
        )
        self.ax_dict['overlap'].axis('off')

        self.im_jpeg = self.ax_dict['jpeg'].imshow(self.jpg_arr_gray, cmap='gray')
        self.ax_dict['jpeg'].set_title("Prediction Mask", fontsize=9)
        self.ax_dict['jpeg'].axis('off')

        self.im_tif = self.ax_dict['tif'].imshow(adjusted)
        self.ax_dict['tif'].set_title("Original TIF", fontsize=9)
        self.ax_dict['tif'].axis('off')

        self.canvas.draw()

    # ------------------------------------------------------------------ #
    #  Event handlers                                                      #
    # ------------------------------------------------------------------ #

    def _on_list_selection(self, current, _previous):
        if current is None:
            return
        tif_path = current.data(Qt.UserRole)
        jpg_path = current.data(Qt.UserRole + 1)
        if tif_path and jpg_path:
            self._load_image(tif_path, jpg_path)

    def _on_slider(self):
        self.lbl_contrast.setText(f"{self.s_contrast.value() / 100:.2f}×")
        self.lbl_brightness.setText(str(self.s_brightness.value()))
        self._slider_timer.start(50)

    def _apply_adjustments(self):
        if self.original_tif_arr is None or self.im_overlap is None:
            return
        adjusted, overlay = self._composite()
        self.im_overlap.set_data(overlay)
        self.im_tif.set_data(adjusted)
        self.canvas.draw_idle()

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
        elif event.key in ('i', 'o') and self.ax_dict:
            scale = 1 / 1.2 if event.key == 'i' else 1.2
            ref = self.ax_dict['overlap']
            xl, yl = ref.get_xlim(), ref.get_ylim()
            self._apply_zoom(scale, (xl[0] + xl[1]) / 2, (yl[0] + yl[1]) / 2)
        elif event.key == 'escape':
            self.close()

    def _on_scroll(self, event):
        if not self.ax_dict or event.inaxes not in self.ax_dict.values():
            return
        scale = 1 / 1.2 if event.button == 'up' else 1.2
        self._apply_zoom(scale, event.xdata, event.ydata)

    def _apply_zoom(self, scale, cx, cy):
        for ax in self.ax_dict.values():
            xl, yl = ax.get_xlim(), ax.get_ylim()
            new_w = (xl[1] - xl[0]) * scale
            new_h = (yl[0] - yl[1]) * scale
            relx = (xl[1] - cx) / (xl[1] - xl[0])
            rely = (yl[0] - cy) / (yl[0] - yl[1])
            ax.set_xlim([cx - new_w * (1 - relx), cx + new_w * relx])
            ax.set_ylim([cy + new_h * (1 - rely), cy - new_h * rely])
        self.canvas.draw_idle()

    def _reset_view(self):
        if not self.ax_dict:
            return
        for ax in self.ax_dict.values():
            ax.set_xlim(-0.5, self.img_width - 0.5)
            ax.set_ylim(self.img_height - 0.5, -0.5)
        self.s_contrast.setValue(100)
        self.s_brightness.setValue(0)
        self.canvas.draw_idle()

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
                self,
                "Image Already Scored",
                f'"{fname}" was already scored as {old_score}.\n\n'
                f'Overwrite with new score {score}?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
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
            print(f"\nAll randomly selected images reviewed. "
                  f"Total scored: {len(self.results)}")

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

        print("Please select the Image Folder in the pop-up...")
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

        window = ReviewerWindow(folder_path, rat_name, regions_file)
        window.show()
        sys.exit(app.exec_())


if __name__ == '__main__':
    ImageReviewer()
