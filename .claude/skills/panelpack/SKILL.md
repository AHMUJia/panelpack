---
name: panelpack
description: Compose sub-figure files (PDF/PNG/JPG/TIFF) into publication-ready composite figures with panel labels. One command to merge panels into a single PDF with A,B,C labels, flexible layout, and R/ggplot2 size recommendations.
version: 0.1.0
author: AHMUJia
license: MIT
tags: [figure, panel, compose, publication, PDF, ggplot2, ggsave, subplot, composite]
dependencies: [pymupdf]
user_invocable: true
---

# panelpack - Publication-ready composite figures

Installed at `F:/panelpack`. Source: `F:/panelpack/panelpack/cli.py`.

## When to use

TRIGGER when: user wants to combine/merge sub-figures into a composite figure, arrange panels into a grid, add A/B/C labels to figures, or get recommended R/ggplot2 export sizes for panel figures.

## Quick start

```bash
panelpack                                       # auto-detect and compose
panelpack -d ./Figure3                          # specify directory
panelpack --layout 1,2,3                        # row1=1, row2=2, row3=3
panelpack --layout "3,2;(1:1:2)(1:1)"          # layout with width ratios
panelpack --dry-run -v                          # preview only
panelpack --sizes                               # R/ggplot2 export sizes
```

## Common workflows

### Workflow 1: Auto-detect and compose

Put sub-figure files in one folder with naming like `Fig3A.pdf`, `Figure 3B.png`, `C.jpg`, `D_barplot.tiff`:

```bash
cd /path/to/figure_folder
panelpack
# Output: Figure3_combined.pdf
```

### Workflow 2: Custom layout with ratios

```bash
panelpack --layout "1,2,3;()()(5:3:3)"         # row 3 width ratio 5:3:3
panelpack --layout 2,2 --ratios "prop;prop"     # proportional to source
```

### Workflow 3: Explicit panel mapping

```bash
panelpack --panels "A=heatmap.pdf,B=bar.png,C=volcano.pdf" --layout 1,2
```

### Workflow 4: R/ggplot2 recommended sizes

```bash
panelpack --sizes
panelpack --sizes --page-size A3 --landscape
```

### Workflow 5: Python API

```python
from panelpack import interactive_compose
interactive_compose("./Figure4", layout="1,2,3;()()(5:3:3)")
```

## File naming conventions

| Style | Examples |
|-------|----------|
| With figure number | `Fig3A_volcano.pdf`, `Figure 3B.png` |
| Without number | `Fig A.pdf`, `Fig.B_plot.png` |
| Bare label | `A.pdf`, `B_barplot.png`, `C.jpg` |

## Supported formats

PDF (vector lossless), PNG, JPG/JPEG, TIFF, BMP, GIF, WebP.

## CLI reference

| Option | Description |
|--------|-------------|
| `-d, --dir DIR` | Directory to scan (default: `.`) |
| `-o, --output FILE` | Output filename |
| `--layout SPEC` | Rows with optional ratios: `1,2,3` or `3,2;(1:1:2)(1:1)` |
| `--ratios SPEC` | Width ratios: `auto;auto;5:3:3` or `prop` |
| `--row-heights SPEC` | Row height weights: `2:3:4` |
| `--page-size SIZE` | `A4`, `A3`, `letter`, or `WxH` in mm |
| `--landscape` | Landscape orientation |
| `--label-size PT` | Label font size (default: 14) |
| `--margin PT` | Page margin (default: 10) |
| `--gap PT` | Gap between panels (default: 6) |
| `--no-labels` | Omit panel labels |
| `--figure N` | Override figure number |
| `--panels SPEC` | Explicit: `A=file.pdf,B=img.png` |
| `--sizes` | Print recommended export sizes and exit |
| `--dry-run` | Preview layout only |
| `--open` | Open output after generation |
| `-v, --verbose` | Verbose output |

## Layout syntax

```
--layout 2,2                        # equal width
--layout "3,2;(1:1:2)(1:1)"        # inline ratios
--layout "1,2,3;()()(5:3:3)"       # empty () = equal

Row 1:  [    A (full width)    ]
Row 2:  [   B   ] [   C   ]
Row 3:  [ D (5) ][ E (3)][ F (3)]
```

## Installation

```bash
cd F:/panelpack && pip install -e . --target F:/PythonLibs
```
