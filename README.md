# panelpack

Compose sub-figure images into publication-ready composite figures from the command line.

**panelpack** auto-detects sub-figure files (PDF, PNG, JPG, TIFF, ...) by naming convention, infers panel order, and merges them into a single PDF with bold panel labels (A, B, C, ...).

All files in the same folder are treated as panels of **one** figure.

## Installation

```bash
pip install panelpack
```

Or install from source:

```bash
git clone https://github.com/panelpack/panelpack.git
cd panelpack
pip install -e .
```

Requires Python >= 3.9 and [PyMuPDF](https://pymupdf.readthedocs.io/).

## Quick start

```bash
# Auto-detect and compose all panels in current directory
panelpack

# Specify layout: 1 panel in row 1, 2 in row 2, 3 in row 3
panelpack --layout 1,2,3

# Layout with inline width ratios — all in one flag
panelpack --layout "3,2;(1:1:2)(1:1)"

# Preview layout without generating PDF
panelpack --dry-run -v

# Explicit panel mapping (for non-standard filenames)
panelpack --panels "A=volcano.pdf,B=heatmap.png,C=barplot.jpg"
```

## Supported formats

| Format | Extensions |
|--------|------------|
| PDF | `.pdf` |
| PNG | `.png` |
| JPEG | `.jpg`, `.jpeg` |
| TIFF | `.tiff`, `.tif` |
| BMP | `.bmp` |
| GIF | `.gif` |
| WebP | `.webp` |

PDF panels are embedded as vector graphics (lossless). Raster images are inserted at their native resolution.

## File naming convention

panelpack recognizes a wide range of naming patterns. The figure number is **optional** — all matched files in the same folder are always treated as panels of one figure.

### With figure number (used for output naming)

| Pattern | Example |
|---------|---------|
| `Fig{N}{L}` | `Fig3A_volcano.pdf` |
| `Fig.{N}{L}` | `Fig.3A_plot.png` |
| `Fig. {N} {L}` | `Fig. 3 A description.pdf` |
| `Figure {N}{L}` | `Figure 3A heatmap.pdf` |
| `Figure_{N}_{L}` | `Figure_4_D_plot.jpg` |

### Without figure number

| Pattern | Example |
|---------|---------|
| `Fig {L}` | `Fig A_something.pdf` |
| `Fig.{L}` | `Fig.B_plot.png` |
| `Fig. {L}` | `Fig. C description.tiff` |
| `Figure {L}` | `Figure D_heatmap.pdf` |
| `{L}.` | `A. description.pdf` |
| `{L}_` | `B_barplot.png` |
| `{L}-` | `C-scatter.jpg` |
| `{L}` | `D.pdf` (single letter filename) |

**Output naming**: If any panel has a figure number, the most common number is used (e.g. `Figure3_combined.pdf`). Otherwise: `Figure_combined.pdf`.

You can mix naming styles freely — `Figure 3A.pdf`, `Fig.3B.png`, `C_plot.jpg`, `D.tiff` all work together in the same folder.

## Layout syntax

The `--layout` flag controls how panels are arranged. Each row's panel count is separated by commas. Width ratios can be written inline with parentheses.

### Basic layout (equal width per row)

```bash
panelpack --layout 2,2          # 2 rows, 2 panels each, all equal width
panelpack --layout 1,2,3        # 3 rows: 1 + 2 + 3 panels
panelpack --layout 3,2          # 2 rows: 3 + 2 panels
```

By default, panels in the same row share **equal width**.

### Layout with inline ratios

Append width ratios in parentheses after a `;` separator. Each `(...)` group corresponds to one row:

```bash
# Row 1: A B C at 1:1:2, Row 2: D E at equal width
panelpack --layout "3,2;(1:1:2)(1:1)"

# Same thing — semicolon is optional
panelpack --layout "3,2(1:1:2)(1:1)"

# Only set ratios for row 3, rows 1-2 stay equal (empty parens)
panelpack --layout "1,2,3;()()(5:3:3)"
```

**Chinese punctuation is also supported** — useful for quick input:

```bash
panelpack --layout "3,2;（1：1：2）（1：1）"
```

### Separate `--ratios` flag

For more control, use `--ratios` separately. Rows are separated by `;`, columns by `:`:

```bash
# Row 1: equal, Row 2: equal, Row 3: 5:3:3
panelpack --layout 1,2,3 --ratios "auto;auto;5:3:3"

# All rows proportional to source widths
panelpack --layout 2,2 --ratios "prop;prop"
```

| Keyword | Meaning |
|---------|---------|
| `auto` or empty `()` | Equal width (default) |
| `prop` | Proportional to source image widths |
| `5:3:3` | Explicit ratio |

> `--ratios` takes priority over inline ratios in `--layout`.

### Visual summary

```
--layout "1,2,3;()()(5:3:3)"

Row 1:  [    A (full width)    ]
Row 2:  [   B   ] [   C   ]
Row 3:  [ D (5) ][ E (3)][ F (3)]
```

## Recommended sub-figure export sizes

To preserve text size after composing, export each sub-figure at the **exact size** it will occupy in the final layout. Use `panelpack --sizes` to calculate:

```
$ panelpack --sizes

Recommended sub-figure export sizes
  Page: A4 portrait (210x297 mm)
  Margin: 10pt, Gap: 6pt, Label: 14pt
  Aspect ratio: 1.33 (width/height)

  Panels/row        Width     Height R ggsave()
  -----------  ---------- ---------- ------------------------------
  1                197 mm     148 mm width=7.8, height=5.8
  2                 98 mm      73 mm width=3.8, height=2.9
  3                 64 mm      48 mm width=2.5, height=1.9
  4                 48 mm      36 mm width=1.9, height=1.4
```

### R / ggplot2 example

If your layout is `--layout 1,2,3` (row 1: 1 panel, row 2: 2 panels, row 3: 3 panels):

```r
library(ggplot2)

# Panel A — full width (1 per row)
ggsave("Fig1A_volcano.pdf", plot_a, width = 7.8, height = 5.8)

# Panels B, C — half width (2 per row)
ggsave("Fig1B_heatmap.pdf", plot_b, width = 3.8, height = 2.9)
ggsave("Fig1C_barplot.pdf", plot_c, width = 3.8, height = 2.9)

# Panels D, E, F — third width (3 per row)
ggsave("Fig1D_scatter.pdf", plot_d, width = 2.5, height = 1.9)
ggsave("Fig1E_boxplot.pdf", plot_e, width = 2.5, height = 1.9)
ggsave("Fig1F_survival.pdf", plot_f, width = 2.5, height = 1.9)
```

With these sizes, `panelpack` places each panel at **scale ~ 1.0**, so a `7pt` font in R stays `7pt` in the final figure.

### Other page sizes

```bash
panelpack --sizes --page-size A3 --landscape
panelpack --sizes --page-size letter
panelpack --sizes --page-size 180x240       # custom WxH in mm
panelpack --sizes --aspect-ratio 1.0        # square panels
```

## Python API

```python
from panelpack import interactive_compose

# One-liner: detect panels and compose
interactive_compose("./Figure4", layout="1,2,3;()()(5:3:3)")

# All options
interactive_compose(
    "./my_figures",
    layout="2,2",
    page_size="A4",
    label_size=14,
    output="Figure1.pdf",
    open_after=True,
)
```

## CLI reference

```
panelpack [options]
```

### Panel detection

| Option | Description |
|--------|-------------|
| `-d, --dir DIR` | Directory to scan (default: `.`) |
| `--figure N` | Override figure number for output naming |
| `--panels SPEC` | Explicit mapping: `A=file1.pdf,B=plot.png,...` |
| `--pattern REGEX` | Custom regex (must capture groups: figure number, panel label) |

### Layout

| Option | Description |
|--------|-------------|
| `--layout SPEC` | Panels per row with optional inline ratios: `1,2,3` or `3,2;(1:1:2)(1:1)` |
| `--ratios SPEC` | Width ratios per row: `auto;auto;5:3:3`. Overrides inline ratios. |
| `--row-heights SPEC` | Row height weights: `2:3:4`. Default: auto from aspect ratios. |

### Page & style

| Option | Description |
|--------|-------------|
| `--page-size SIZE` | `A4`, `A3`, `letter`, or `WxH` in mm (default: `A4`) |
| `--landscape` | Landscape orientation |
| `--label-size PT` | Panel label font size (default: `14`) |
| `--margin PT` | Page margin (default: `10`) |
| `--gap PT` | Gap between panels (default: `6`) |
| `--no-labels` | Omit panel labels |

### Utilities

| Option | Description |
|--------|-------------|
| `--sizes` | Print recommended export sizes and exit |
| `--aspect-ratio R` | Width/height ratio for `--sizes` (default: `1.33`) |
| `--max-cols N` | Max panels per row for `--sizes` table (default: `4`) |
| `--dry-run` | Preview layout without generating PDF |
| `--open` | Open output file after generation |
| `-v, --verbose` | Verbose output with scale info |
| `-o, --output FILE` | Output filename (default: `Figure<N>_combined.pdf`) |

## Examples

### Simple 2x2 grid

```bash
panelpack --layout 2,2 -o Figure1.pdf
```

### Layout with inline ratios

```bash
panelpack --layout "3,2;(1:1:2)(1:1)" -o Figure5.pdf
```

### Complex layout with separate ratios

```bash
panelpack --layout 1,2,3 --ratios "auto;auto;5:3:3" -o Figure4.pdf
```

### Mixed formats (PDF + PNG + JPG)

```bash
# Folder contains: A_volcano.pdf, B_heatmap.png, C_photo.jpg, D_gel.tiff
panelpack --layout 2,2
```

### A3 landscape for poster figures

```bash
panelpack --page-size A3 --landscape --layout 2,3 -o poster_fig.pdf
```

## License

MIT
