# Genzel IEG Checker

An interactive GUI tool for quality control (QC) scoring of neuroscience brain region images. Researchers visually inspect segmentation prediction masks overlaid on original tissue scans and assign quality scores, which are saved to an Excel file.

---

## What It Does

The tool loads pairs of images — an original TIF brain scan and its corresponding JPEG prediction mask — and displays them side-by-side with an overlay. The reviewer scores each image using keyboard shortcuts. Results accumulate in an Excel file, saved incrementally after each score.

One image is randomly sampled per brain region per hemisphere (left/right), so the reviewer sees a representative cross-section rather than every image in the folder.

---

## Prerequisites

**Python 3.8+** is required.

Install dependencies:

```bash
pip install -r requirements.txt
```

Key packages used: `PyQt5`, `matplotlib`, `Pillow`, `pandas`, `openpyxl`, `numpy`.

---

## How to Run

```bash
python quality_checker.py
```

On launch, two dialogs appear:

1. **Select folder** — choose the folder containing your TIF images and JPEG prediction masks.
2. **Enter Rat ID** — type the rat identifier (e.g. `Rat461707`). This is used to filter files by name and label the output file.

---

## File Naming Conventions

The tool discovers files using these patterns:

**TIF images** (original scans):
```
*{RatID}*.tif
```

**JPEG prediction masks** (must share the same base name):
```
{base_name}_Object Predictions.jpeg
{base_name}_Object Predictions.jpg
```

**Region and hemisphere** are extracted from the filename by splitting on `_`, `-`, and spaces, then matching tokens against the list in `Regions.xlsx`. The tool looks for `RH` or `LH` tokens to identify the hemisphere.

---

## Regions.xlsx

This file contains the list of valid brain region names (one per row, column A). Regions are matched against filename tokens. Longer region names take priority over shorter ones to prefer specific matches (e.g. `vlORB` over `ORB`).

Do not rename this file — the tool expects it in the same directory as `quality_checker.py`.

---

## The Review Interface

The matplotlib window shows three panels:

| Panel | Contents |
|-------|----------|
| **Overlap** (large, left) | Original TIF with red contour of the prediction mask overlaid |
| **Prediction** (top right) | Grayscale prediction mask alone |
| **Original** (bottom right) | Original TIF image |

The title bar displays the region name, hemisphere, score legend, and available controls.

---

## Controls

### Scoring (keyboard)

| Key | Score | Meaning |
|-----|-------|---------|
| `1` | `-2` | Very poor quality |
| `2` | `-1` | Poor quality |
| `3` | `0` | Acceptable / neutral |
| `4` | `1` | Good quality |
| `5` | `2` | Excellent quality |
| `6` | `DISCARD` | Discard this image |

Pressing a score key immediately records the result and advances to the next image.

### Navigation & View

| Key / Action | Effect |
|--------------|--------|
| `i` | Zoom in (1.2×) |
| `o` | Zoom out (1.2×) |
| Scroll wheel | Zoom in/out at cursor position |
| `r` | Reset zoom and sliders to defaults |
| `Escape` | Exit the application |

### Sliders

- **Contrast** — range 0.1 to 3.0 (applied as a multiplier)
- **Brightness** — range −100 to +100 (applied as an offset)

Adjustments apply in real-time to the Overlap and Original panels using:
```
output = clamp(input × contrast + brightness, 0, 255)
```

---

## Output

Results are saved to:

```
{input_folder}/{RatID}_QC_Scores.xlsx
```

The file is updated after every scored image (incremental save), so partial progress is not lost if the tool is closed early.

### Output columns

| Column | Description |
|--------|-------------|
| `Filename` | Original TIF filename |
| `Rat_ID` | Rat identifier entered at startup |
| `Region` | Brain region extracted from filename |
| `Hemisphere` | `LH` or `RH` |
| `Score` | Numeric score (−2 to 2) or `DISCARD` |
| `Raw_Input` | Keyboard key that was pressed (`1`–`6`) |

---

## Sampling Strategy

To avoid reviewing every image in large datasets, the tool groups files by **(Region, Hemisphere)** and randomly selects **one image per group**. This ensures:

- Coverage across all regions and both hemispheres
- A manageable number of images per session
- Representative sampling if multiple images exist per group

---

## Debugging

`debug.py` is a standalone diagnostic script for troubleshooting filename parsing and sampling logic. Edit the hardcoded paths at lines 8–9 to point at your folder and rat ID, then run:

```bash
python debug.py
```

It prints token indices from an example filename, verifies hemisphere extraction, and simulates the grouping and sampling logic without opening the GUI.

---

## Workflow Summary

```
1. Launch → select folder → enter Rat ID
2. Tool finds all *{RatID}*.tif files
3. Filenames are parsed for region and hemisphere
4. One TIF + matching JPEG pair sampled per (region, hemisphere)
5. For each pair:
     - Display 3-panel view with overlay
     - Adjust contrast/brightness/zoom as needed
     - Press 1–6 to score → auto-advances
6. Results written to {RatID}_QC_Scores.xlsx
```
