# Genzel IEG Checker

An interactive GUI tool for quality control (QC) scoring of fluorescence brain section images. Researchers visually inspect segmentation prediction masks overlaid on original tissue scans, optionally compare two channels side-by-side, and assign quality scores saved to an Excel file.

---

## What It Does

The tool loads pairs of images — an original TIF brain scan and its corresponding JPEG prediction mask — and opens each panel in its own floating window. The reviewer scores each image using keyboard shortcuts. Results accumulate in an Excel file, saved incrementally after each score.

One image is randomly sampled per brain region per hemisphere (left/right), so the reviewer sees a representative cross-section rather than every image in the folder.

Optionally, a second folder containing a second fluorescence channel (e.g. cfos) can be loaded alongside the first (e.g. tdTomato). This enables a per-channel display range control and a merged overlay window.

---

## Prerequisites

**Python 3.8+** is required.

Install dependencies:

```bash
pip install -r requirements.txt
```

Key packages: `PyQt5`, `matplotlib`, `Pillow`, `pandas`, `openpyxl`, `numpy`.

---

## How to Run

```bash
python quality_checker.py
```

On launch, a sequence of dialogs appears:

1. **Select image folder** — the folder containing TIF images and JPEG prediction masks.
2. **Select animal** — detected animal IDs are listed; pick one or type manually.
3. **Optional: second channel folder** — choose a cfos folder to enable the merge view (or skip).
4. If yes: **Select cfos folder** — the folder containing the matching cfos TIF files.

---

## File Naming Conventions

### TIF images (main channel, e.g. tdTomato)
```
OS_TRAP_m464102_tdTomato_Parietal_1-6_20x_HPC-DG_RH.tif
```

### TIF images (second channel, e.g. cfos)
```
OS_TRAP_m464102_cfos_Parietal_1-6_20x_HPC-DG_RH.tif
```

The tool automatically detects which token differs between the two folders (e.g. `tdTomato` vs `cfos`) and uses it to match corresponding files across folders.

### JPEG prediction masks
```
{base_name}_Object Predictions.jpeg
{base_name}_Object Predictions.jpg
```

**Region** and **hemisphere** are extracted from the filename by splitting on `_`, `-`, and spaces, then matching tokens against `Regions.xlsx`. `RH` or `LH` tokens identify the hemisphere.

---

## Regions.xlsx

Contains valid brain region names (one per row, column A). Longer names take priority over shorter ones (e.g. `vlORB` over `ORB`).

Must be in the same directory as `quality_checker.py`.

---

## Windows

Each panel opens in its own resizable floating window (default size: half the screen width × half the screen height, cascaded with 30 px offsets). When a new image is selected from the list, all windows close and a fresh set opens.

### Without cfos folder (3 windows)

| Window | Contents |
|--------|----------|
| **Overlap** | tdTomato TIF with prediction mask contour overlaid |
| **Prediction Mask** | Grayscale JPEG mask alone |
| **tdTomato** | Original TIF, adjusted by display range + contrast/brightness |

### With cfos folder (5 windows)

| Window | Contents |
|--------|----------|
| **Overlap** | tdTomato TIF with prediction mask contour overlaid |
| **Prediction Mask** | Grayscale JPEG mask alone |
| **tdTomato** | tdTomato channel (red) |
| **cfos** | cfos channel (green) |
| **Merge** | tdTomato (red) + cfos (green) blended, alpha-adjustable |

Display is normalised per-image to the actual pixel min/max, matching ImageJ's auto-contrast behaviour.

---

## Controls

### Scoring (keyboard, works from any window)

| Key | Score | Meaning |
|-----|-------|---------|
| `1` | `−2` | Very poor quality |
| `2` | `−1` | Poor quality |
| `3` | `0` | Acceptable / neutral |
| `4` | `+1` | Good quality |
| `5` | `+2` | Excellent quality |
| `6` | `DISCARD` | Discard this image |

Pressing a score key immediately records the result and advances to the next unscored image. If an image has already been scored, a confirmation dialog appears before overwriting.

### Navigation & zoom (keyboard, works from any window)

| Key / Action | Effect |
|--------------|--------|
| `i` | Zoom in 1.2× (all windows simultaneously) |
| `o` | Zoom out 1.2× (all windows simultaneously) |
| Scroll wheel | Zoom in/out at cursor position (that window only) |
| `r` | Reset zoom, display range, contrast, brightness, and alpha to defaults |
| `Escape` | Exit the application |

### Control panel sliders

**Display Range (Min / Max)**

Sets the black point (Lo) and white point (Hi) using actual pixel values from the raw TIF. Equivalent to ImageJ's Brightness/Contrast sliders. Each channel has its own Lo/Hi pair; the range is automatically initialised to the image's actual pixel min and max when a new image loads.

**Image Adjust**

- **Contrast** — multiplier applied after display-range normalisation (0.1 × to 3.0 ×)
- **Brightness** — offset applied after contrast (−100 to +100)

```
output = clamp(normalised × contrast + brightness, 0, 255)
```

**Merge Alpha** *(visible only when cfos folder is loaded)*

- One slider per channel (0–1), controlling how strongly each channel contributes to the Merge window.

---

## Output

Results are saved to:

```
{input_folder}/{AnimalID}_QC_Scores.xlsx
```

The file is updated after every scored image so partial progress is never lost.

### Output columns

| Column | Description |
|--------|-------------|
| `Filename` | Original TIF filename |
| `Rat_ID` | Animal identifier selected at startup |
| `Region` | Brain region extracted from filename |
| `Hemisphere` | `LH` or `RH` |
| `Score` | Numeric score (−2 to 2) or `DISCARD` |
| `Raw_Input` | Keyboard key pressed (`1`–`6`) |

---

## Sampling Strategy

Files are grouped by **(Region, Hemisphere)** and one image is randomly selected per group. This ensures:

- Coverage across all regions and both hemispheres
- A manageable number of images per session
- Representative sampling when multiple slices exist per group

Images without a matching JPEG prediction mask are shown in grey in the list and cannot be selected.

---

## Workflow Summary

```
1. Launch → select image folder → select animal ID
2. Optionally select cfos folder
3. Tool finds all *{AnimalID}*.tif files, groups by region/hemisphere,
   randomly picks one per group
4. For each selected image:
     a. All panel windows open (3 or 5 depending on cfos)
     b. Adjust display range / contrast / brightness / zoom as needed
     c. Press 1–6 to score → windows close, next image opens
5. Results written to {AnimalID}_QC_Scores.xlsx after each score
```

---

## Debugging

`debug.py` is a standalone diagnostic script for troubleshooting filename parsing and sampling logic. Edit the hardcoded paths at lines 8–9 to point at your folder and animal ID, then run:

```bash
python debug.py
```

It prints token indices from an example filename, verifies hemisphere extraction, and simulates the grouping and sampling logic without opening the GUI.
