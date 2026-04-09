"""panelpack — combine sub-figure PDFs into a single composite figure."""

from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pymupdf  # PyMuPDF

from panelpack import __version__

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

# Supported file extensions
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp"}
PDF_EXT = {".pdf"}
ALL_EXTS = PDF_EXT | IMAGE_EXTS


@dataclass
class Panel:
    label: str
    path: Path
    src_w: float = 0.0
    src_h: float = 0.0

    @property
    def is_pdf(self) -> bool:
        return self.path.suffix.lower() in PDF_EXT

    def load_dims(self):
        if self.is_pdf:
            doc = pymupdf.open(str(self.path))
            page = doc[0]
            self.src_w = page.rect.width
            self.src_h = page.rect.height
            doc.close()
        else:
            # Raster image — get pixel dimensions, treat as 72 dpi for pt
            pix = pymupdf.Pixmap(str(self.path))
            self.src_w = float(pix.width)
            self.src_h = float(pix.height)
            pix = None


@dataclass
class PanelRect:
    panel: Panel
    x: float
    y: float
    w: float
    h: float
    label_x: float
    label_y: float


# ---------------------------------------------------------------------------
# 1. Detection — find sub-figure PDFs and extract labels
# ---------------------------------------------------------------------------

# Priority 1: Fig/Figure with number AND label
#   Fig3A, Fig.3A, Fig. 3A, Figure 3A, Figure_3_A, Fig3-A …
_PAT_WITH_NUM = re.compile(
    r"[Ff]ig(?:ure)?\.?\s*[_\s\-]*(\d+)\s*[_\s\-]*([A-Za-z])(?![a-zA-Z])"
)

# Priority 2: Fig/Figure with label only (no number)
#   Fig A, Fig.A, Fig. A, Figure A, FigA …
_PAT_NO_NUM = re.compile(
    r"[Ff]ig(?:ure)?\.?\s*[_\s\-]*([A-Za-z])(?![a-zA-Z])"
)

# Priority 3: Bare number+label at the start of filename
#   1B., 1e., 2A_, 3C-description …
_PAT_NUM_LABEL = re.compile(r"^(\d+)\s*([A-Za-z])(?![a-zA-Z])")

# Priority 4: Bare label at the start of filename
#   A., A_, A-, A<space>, A_something, or just "A" (single letter stem)
_PAT_BARE = re.compile(r"^([A-Za-z])(?:[\.\s_\-]|$)")


def _extract_panel_info(stem: str) -> tuple[int | None, str] | None:
    """Extract ``(figure_number_or_None, label)`` from a filename stem.

    Tries four patterns in priority order so that all of these work::

        Figure 3A, Figure A, Fig A, Fig.A, Fig. A,
        Fig3A, Fig.3A, Fig. 3A, 1B., 1e., A., A_description …
    """
    m = _PAT_WITH_NUM.search(stem)
    if m:
        return int(m.group(1)), m.group(2).upper()

    m = _PAT_NO_NUM.search(stem)
    if m:
        return None, m.group(1).upper()

    m = _PAT_NUM_LABEL.match(stem)  # anchored to start
    if m:
        return int(m.group(1)), m.group(2).upper()

    m = _PAT_BARE.match(stem)  # anchored to start
    if m:
        return None, m.group(1).upper()

    return None


def detect_panels(
    directory: Path,
    pattern: re.Pattern | None = None,
) -> tuple[list[Panel], int | None]:
    """Scan *directory* for PDFs matching the naming convention.

    All recognised PDFs in the same directory are treated as panels of
    **one** figure.  Returns ``(panels, figure_number)`` where
    *figure_number* is the most common number found (or ``None``).
    """
    panels: list[Panel] = []
    fig_nums: list[int] = []

    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in ALL_EXTS:
            continue

        if pattern:
            m = pattern.search(entry.stem)
            if not m:
                continue
            fig_nums.append(int(m.group(1)))
            label = m.group(2).upper()
        else:
            info = _extract_panel_info(entry.stem)
            if info is None:
                continue
            raw_num, label = info
            if raw_num is not None:
                fig_nums.append(raw_num)

        panels.append(Panel(label=label, path=entry))

    # Deduplicate: keep first match per label
    seen: dict[str, Panel] = {}
    for p in panels:
        if p.label not in seen:
            seen[p.label] = p
    panels = sorted(seen.values(), key=lambda p: p.label)

    # Figure number: most common among detected numbers, or None
    detected_num = None
    if fig_nums:
        from collections import Counter
        detected_num = Counter(fig_nums).most_common(1)[0][0]

    return panels, detected_num


# ---------------------------------------------------------------------------
# 2. Layout — decide how many panels go in each row
# ---------------------------------------------------------------------------

def parse_layout_spec(spec: str) -> tuple[list[int], str | None]:
    """Parse combined layout+ratio spec.

    Supports these formats::

        "3,2"                       → layout [3,2], no inline ratios
        "3,2;(1:1:2)(1:1)"         → layout [3,2], ratios per row
        "1,2,3;()()(5:3:3)"        → layout [1,2,3], rows 1-2 equal, row 3 = 5:3:3

    Chinese punctuation ``（）`` and ``：`` are accepted alongside ``()`` and ``:``.
    Returns ``(layout, ratios_spec_or_None)``.
    """
    # Normalise Chinese punctuation → ASCII
    spec = spec.replace("\uff08", "(").replace("\uff09", ")")
    spec = spec.replace("\uff1a", ":").replace("\u3001", ",")

    # Split on ';' — left = layout, right = inline ratios
    if ";" in spec:
        layout_part, ratio_part = spec.split(";", 1)
    elif "(" in spec:
        # Allow omitting ';': "3,2(1:1:2)(1:1)"
        idx = spec.index("(")
        layout_part = spec[:idx]
        ratio_part = spec[idx:]
    else:
        layout_part = spec
        ratio_part = None

    layout = [int(x.strip()) for x in layout_part.strip().rstrip(",").split(",")]

    if not ratio_part or ratio_part.strip() == "":
        return layout, None

    # Extract ratio groups from parentheses: "(1:1:2)(1:1)" → ["1:1:2", "1:1"]
    groups = re.findall(r"\(([^)]*)\)", ratio_part)
    if not groups:
        return layout, None

    if len(groups) != len(layout):
        raise ValueError(
            f"Layout has {len(layout)} rows but {len(groups)} ratio groups given"
        )

    # Convert to standard ratios spec: "1:1:2;1:1"
    # Empty parens "()" → "auto"
    parts = []
    for g in groups:
        g = g.strip()
        parts.append(g if g else "auto")
    ratios_spec = ";".join(parts)

    return layout, ratios_spec


def compute_layout(n: int, spec: str | None = None) -> tuple[list[int], str | None]:
    """Return ``(panels_per_row, inline_ratios_or_None)``.

    *spec* examples: ``"1,2,3"``, ``"3,2;(1:1:2)(1:1)"``.
    """
    if spec:
        layout, inline_ratios = parse_layout_spec(spec)
        if sum(layout) != n:
            raise ValueError(
                f"Layout {spec} sums to {sum(layout)} but there are {n} panels"
            )
        return layout, inline_ratios

    if n <= 3:
        return [n], None
    if n == 4:
        return [2, 2], None
    if n == 5:
        return [2, 3], None
    if n == 6:
        return [2, 2, 2], None
    if n == 7:
        return [2, 3, 2], None
    if n == 8:
        return [2, 3, 3], None
    if n == 9:
        return [3, 3, 3], None
    rows = []
    remaining = n
    while remaining > 0:
        rows.append(min(3, remaining))
        remaining -= min(3, remaining)
    return rows, None


# ---------------------------------------------------------------------------
# 3. Width ratios per row
# ---------------------------------------------------------------------------

def compute_ratios(
    layout: list[int],
    spec: str | None,
    panel_rows: list[list[Panel]],
) -> list[list[float]]:
    """Return normalised width ratios for each row.

    *spec* format: rows separated by ``';'``, columns by ``':'``.
    ``"auto;auto;5:3:3"`` → rows 1-2 equal width, row 3 = 5:3:3.
    Use ``prop`` for proportional-to-source-width per row.
    ``None`` → equal width everywhere.
    """
    def _equal(row_panels: list[Panel]) -> list[float]:
        n = len(row_panels)
        return [1.0 / n] * n

    def _proportional(row_panels: list[Panel]) -> list[float]:
        widths = [p.src_w for p in row_panels]
        total = sum(widths)
        return [w / total for w in widths]

    if not spec:
        return [_equal(rp) for rp in panel_rows]

    row_specs = spec.split(";")
    if len(row_specs) == 1 and len(layout) > 1:
        row_specs = row_specs * len(layout)
    if len(row_specs) != len(layout):
        raise ValueError(
            f"Ratio spec has {len(row_specs)} rows but layout has {len(layout)}"
        )
    result = []
    for rs, n_cols, rp in zip(row_specs, layout, panel_rows):
        rs = rs.strip()
        if not rs or rs.lower() == "auto":
            result.append(_equal(rp))
            continue
        if rs.lower() == "prop":
            result.append(_proportional(rp))
            continue
        vals = [float(v.strip()) for v in rs.split(":")]
        if len(vals) == 1:
            vals = vals * n_cols
        if len(vals) != n_cols:
            raise ValueError(
                f"Row ratio '{rs}' has {len(vals)} values but row has {n_cols} panels"
            )
        total = sum(vals)
        result.append([v / total for v in vals])
    return result


def parse_row_heights(spec: str | None, n_rows: int) -> list[float] | None:
    """Parse ``--row-heights`` spec like ``"3:3:4"`` into normalised weights."""
    if not spec:
        return None
    vals = [float(v.strip()) for v in spec.split(":")]
    if len(vals) != n_rows:
        raise ValueError(
            f"Row-heights has {len(vals)} values but layout has {n_rows} rows"
        )
    total = sum(vals)
    return [v / total for v in vals]


# ---------------------------------------------------------------------------
# 4. Geometry — compute rectangles for every panel
# ---------------------------------------------------------------------------

PAGE_SIZES = {
    "a4": (595.28, 841.89),
    "a3": (841.89, 1190.55),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
}


def parse_page_size(spec: str) -> tuple[float, float]:
    key = spec.lower().strip()
    if key in PAGE_SIZES:
        return PAGE_SIZES[key]
    m = re.match(r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)", spec)
    if m:
        mm_to_pt = 72.0 / 25.4
        return float(m.group(1)) * mm_to_pt, float(m.group(2)) * mm_to_pt
    raise ValueError(f"Unknown page size: {spec!r}")


def compute_geometry(
    panel_rows: list[list[Panel]],
    ratios: list[list[float]],
    page_w: float,
    page_h: float,
    margin: float,
    gap: float,
    label_size: float,
    no_labels: bool,
    row_height_weights: list[float] | None = None,
) -> list[PanelRect]:
    """Compute placement rectangles for all panels.

    If *row_height_weights* is given, vertical space is distributed by those
    weights instead of being derived from aspect ratios.
    """
    label_col = 0.0 if no_labels else (label_size + 2)
    content_w = page_w - 2 * margin - label_col
    n_rows = len(panel_rows)
    available_h = page_h - 2 * margin - (n_rows - 1) * gap

    if row_height_weights:
        # Explicit row height allocation
        row_heights = [w * available_h for w in row_height_weights]
    else:
        # Auto: derive from aspect ratios, then scale to fit page
        raw_heights = []
        for row_panels, row_ratios in zip(panel_rows, ratios):
            n_cols = len(row_panels)
            avail_w = content_w - (n_cols - 1) * gap
            col_widths = [r * avail_w for r in row_ratios]
            h = max(cw / (p.src_w / p.src_h) for p, cw in zip(row_panels, col_widths))
            raw_heights.append(h)
        total_raw = sum(raw_heights)
        if total_raw > available_h:
            scale = available_h / total_raw
            row_heights = [h * scale for h in raw_heights]
        else:
            row_heights = raw_heights

    # Build rectangles
    rects: list[PanelRect] = []
    y = margin
    for row_panels, row_ratios, row_h in zip(panel_rows, ratios, row_heights):
        n_cols = len(row_panels)
        avail_w = content_w - (n_cols - 1) * gap
        col_widths = [r * avail_w for r in row_ratios]

        x = margin + label_col
        for p, cw in zip(row_panels, col_widths):
            aspect = p.src_w / p.src_h
            # Fit panel in (cw × row_h) keeping aspect ratio
            if cw / row_h > aspect:
                dh = row_h
                dw = row_h * aspect
            else:
                dw = cw
                dh = cw / aspect

            # Centre within cell
            dx = x + (cw - dw) / 2
            dy = y + (row_h - dh) / 2
            lx = x - label_col
            ly = y

            rects.append(PanelRect(
                panel=p, x=dx, y=dy, w=dw, h=dh,
                label_x=lx, label_y=ly,
            ))
            x += cw + gap
        y += row_h + gap

    # Actual content height (last gap replaced by margin)
    actual_h = y - gap + margin

    return rects, actual_h


# ---------------------------------------------------------------------------
# 5. Compose — render the combined PDF
# ---------------------------------------------------------------------------

def compose(
    rects: list[PanelRect],
    page_w: float,
    page_h: float,
    label_size: float,
    no_labels: bool,
) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=page_w, height=page_h)

    for pr in rects:
        target = pymupdf.Rect(pr.x, pr.y, pr.x + pr.w, pr.y + pr.h)
        if pr.panel.is_pdf:
            src = pymupdf.open(str(pr.panel.path))
            page.show_pdf_page(target, src, 0)
            src.close()
        else:
            page.insert_image(target, filename=str(pr.panel.path))

        if not no_labels:
            page.insert_text(
                pymupdf.Point(pr.label_x, pr.label_y + label_size),
                pr.panel.label,
                fontsize=label_size,
                fontname="hebo",  # Helvetica Bold
                color=(0, 0, 0),
            )

    return doc


# ---------------------------------------------------------------------------
# 6. CLI
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6a. Size calculator — recommended ggsave dimensions for each layout slot
# ---------------------------------------------------------------------------

PT_PER_INCH = 72.0
PT_PER_MM = 72.0 / 25.4


def calc_panel_sizes(
    page_size: str = "A4",
    landscape: bool = False,
    margin: float = 10,
    gap: float = 6,
    label_size: float = 14,
    no_labels: bool = False,
    max_cols: int = 4,
    aspect_ratio: float = 4 / 3,
) -> list[dict]:
    """Calculate recommended export dimensions for 1..max_cols panels per row.

    Returns a list of dicts with keys: n_cols, width_mm, width_inch,
    height_mm, height_inch (height assumes *aspect_ratio*).
    """
    page_w, page_h = parse_page_size(page_size)
    if landscape:
        page_w, page_h = page_h, page_w

    label_col = 0.0 if no_labels else (label_size + 2)
    content_w = page_w - 2 * margin - label_col

    results = []
    for n in range(1, max_cols + 1):
        avail = content_w - (n - 1) * gap
        w_pt = avail / n
        w_mm = w_pt / PT_PER_MM
        w_inch = w_pt / PT_PER_INCH
        h_inch = w_inch / aspect_ratio
        h_mm = h_inch * 25.4
        results.append({
            "n_cols": n,
            "width_mm": w_mm,
            "width_inch": w_inch,
            "height_mm": h_mm,
            "height_inch": h_inch,
        })
    return results


def print_size_table(
    page_size: str = "A4",
    landscape: bool = False,
    margin: float = 10,
    gap: float = 6,
    label_size: float = 14,
    no_labels: bool = False,
    max_cols: int = 4,
    aspect_ratio: float = 4 / 3,
):
    """Print a table of recommended ggsave / export dimensions."""
    sizes = calc_panel_sizes(
        page_size, landscape, margin, gap, label_size, no_labels,
        max_cols, aspect_ratio,
    )
    page_w, page_h = parse_page_size(page_size)
    if landscape:
        page_w, page_h = page_h, page_w

    orient = "landscape" if landscape else "portrait"
    print(f"\nRecommended sub-figure export sizes")
    print(f"  Page: {page_size} {orient} ({page_w/PT_PER_MM:.0f}\u00d7{page_h/PT_PER_MM:.0f} mm)")
    print(f"  Margin: {margin}pt, Gap: {gap}pt, Label: {label_size}pt")
    print(f"  Aspect ratio: {aspect_ratio:.2f} (width/height)\n")
    print(f"  {'Panels/row':<12} {'Width':>10} {'Height':>10} {'R ggsave()'}")
    print(f"  {'-'*11:<12} {'-'*10:>10} {'-'*10:>10} {'-'*30}")
    for s in sizes:
        w_i = s["width_inch"]
        h_i = s["height_inch"]
        w_m = s["width_mm"]
        h_m = s["height_mm"]
        r_code = f"width={w_i:.1f}, height={h_i:.1f}"
        print(f"  {s['n_cols']:<12} {w_m:>7.0f} mm {h_m:>7.0f} mm {r_code}")
    print()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="panelpack",
        description="Compose sub-figure PDFs into a publication-ready composite figure.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  panelpack                                    # auto-detect & compose
  panelpack --layout 1,2,3                     # specify rows
  panelpack --layout 1,2,3 --ratios "auto;auto;5:3:3"
  panelpack --layout 1,2,3 --row-heights 2:3:4
  panelpack --page-size A3 --landscape -o Fig4.pdf
  panelpack --dry-run -v                       # preview only
  panelpack --panels "A=heatmap.pdf,B=bar.pdf" # explicit mapping
""",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "-d", "--dir", default=".", metavar="DIR",
        help="directory to scan (default: .)",
    )
    p.add_argument(
        "-o", "--output", default=None, metavar="FILE",
        help="output filename (default: Figure<N>_combined.pdf)",
    )
    p.add_argument(
        "--layout", default=None, metavar="SPEC",
        help="panels per row, e.g. '1,2,3'. Auto if omitted.",
    )
    p.add_argument(
        "--ratios", default=None, metavar="SPEC",
        help="width ratios per row: 'auto;auto;5:3:3' (';' separates rows, ':' columns). "
             "'auto' = equal width, 'prop' = proportional to source width. Default: equal.",
    )
    p.add_argument(
        "--row-heights", default=None, metavar="SPEC",
        help="row height weights, e.g. '2:3:4'. Default: auto from aspect ratios.",
    )
    p.add_argument(
        "--page-size", default="A4", metavar="SIZE",
        help="A4 | A3 | letter | WxH in mm (default: A4)",
    )
    p.add_argument("--landscape", action="store_true", help="landscape orientation")
    p.add_argument(
        "--label-size", type=float, default=14, metavar="PT",
        help="panel label font size in pt (default: 14)",
    )
    p.add_argument(
        "--margin", type=float, default=10, metavar="PT",
        help="page margin in pt (default: 10)",
    )
    p.add_argument(
        "--gap", type=float, default=6, metavar="PT",
        help="gap between panels in pt (default: 6)",
    )
    p.add_argument("--no-labels", action="store_true", help="omit panel labels")
    p.add_argument(
        "--figure", type=int, default=None, metavar="N",
        help="override figure number for output naming (e.g. --figure 3 -> Figure3_combined.pdf)",
    )
    p.add_argument(
        "--panels", default=None, metavar="SPEC",
        help="explicit panel mapping: 'A=file1.pdf,B=file2.pdf,...'",
    )
    p.add_argument(
        "--pattern", default=None, metavar="REGEX",
        help="custom regex (must capture groups: figure number, panel label)",
    )
    p.add_argument(
        "--sizes", action="store_true",
        help="print recommended sub-figure export sizes (R ggsave dimensions) and exit",
    )
    p.add_argument(
        "--aspect-ratio", type=float, default=4/3, metavar="R",
        help="width/height ratio for --sizes calculation (default: 1.33 i.e. 4:3)",
    )
    p.add_argument(
        "--max-cols", type=int, default=4, metavar="N",
        help="max panels per row for --sizes table (default: 4)",
    )
    p.add_argument("--dry-run", action="store_true", help="preview layout, don't generate PDF")
    p.add_argument("--open", action="store_true", help="open output after generation")
    p.add_argument("-v", "--verbose", action="store_true", help="verbose output")
    return p


def parse_explicit_panels(spec: str, directory: Path) -> list[Panel]:
    """Parse ``--panels 'A=file.pdf,B=file.pdf,...'``"""
    panels = []
    for item in spec.split(","):
        item = item.strip()
        if "=" not in item:
            raise ValueError(f"Invalid panel spec: {item!r} (expected LABEL=FILE)")
        label, fname = item.split("=", 1)
        path = directory / fname.strip()
        if not path.exists():
            raise FileNotFoundError(f"Panel {label}: {path} not found")
        panels.append(Panel(label=label.strip().upper(), path=path))
    panels.sort(key=lambda p: p.label)
    return panels


def open_file(path: Path):
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    else:
        subprocess.run(["xdg-open", str(path)])


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    # --- Size calculator mode ---
    if args.sizes:
        print_size_table(
            page_size=args.page_size,
            landscape=args.landscape,
            margin=args.margin,
            gap=args.gap,
            label_size=args.label_size,
            no_labels=args.no_labels,
            max_cols=args.max_cols,
            aspect_ratio=args.aspect_ratio,
        )
        return

    directory = Path(args.dir).resolve()

    # --- Detect or load panels ---
    if args.panels:
        panels = parse_explicit_panels(args.panels, directory)
        fig_num = args.figure  # None if not specified
    else:
        pat = re.compile(args.pattern) if args.pattern else None
        panels, detected_num = detect_panels(directory, pattern=pat)
        if not panels:
            print("Error: no matching sub-figure PDFs found.", file=sys.stderr)
            print(f"  Scanned: {directory}", file=sys.stderr)
            print("  Tip: use --panels 'A=file.pdf,B=file.pdf' for explicit mapping",
                  file=sys.stderr)
            sys.exit(1)
        fig_num = args.figure if args.figure is not None else detected_num

    for p in panels:
        p.load_dims()

    n = len(panels)
    fig_label = f"Figure {fig_num}" if fig_num is not None else "Figure"
    print(f"{fig_label}: {n} panels detected")
    for p in panels:
        print(f"  {p.label}: {p.path.name}  ({p.src_w:.0f}\u00d7{p.src_h:.0f} pt)")

    # --- Layout ---
    layout, inline_ratios = compute_layout(n, args.layout)
    print(f"Layout: {','.join(map(str, layout))}")

    panel_rows: list[list[Panel]] = []
    idx = 0
    for row_n in layout:
        panel_rows.append(panels[idx : idx + row_n])
        idx += row_n

    # --- Ratios & row heights ---
    # --ratios flag takes priority, then inline ratios from --layout
    ratios_spec = args.ratios or inline_ratios
    ratios = compute_ratios(layout, ratios_spec, panel_rows)
    row_height_weights = parse_row_heights(args.row_heights, len(layout))

    if args.verbose:
        for i, (rr, pr) in enumerate(zip(ratios, panel_rows)):
            labels = [p.label for p in pr]
            ratio_str = ":".join(f"{r:.2f}" for r in rr)
            print(f"  Row {i+1}: [{','.join(labels)}] ratios={ratio_str}")

    # --- Page size ---
    page_w, page_h = parse_page_size(args.page_size)
    if args.landscape:
        page_w, page_h = page_h, page_w

    # --- Geometry ---
    rects, actual_h = compute_geometry(
        panel_rows, ratios, page_w, page_h,
        args.margin, args.gap, args.label_size, args.no_labels,
        row_height_weights,
    )
    # Trim page height to actual content (keep width unchanged)
    final_h = min(page_h, actual_h)

    # Print scale info
    if args.verbose:
        for pr in rects:
            s = pr.w / pr.panel.src_w
            print(f"  {pr.panel.label}: scale={s:.3f}  "
                  f"({pr.panel.src_w:.0f}\u00d7{pr.panel.src_h:.0f} "
                  f"\u2192 {pr.w:.0f}\u00d7{pr.h:.0f})")

    if args.dry_run:
        print("[dry-run] No PDF generated.")
        return

    # --- Compose ---
    if args.output:
        output = args.output
    elif fig_num is not None:
        output = f"Figure{fig_num}_combined.pdf"
    else:
        output = "Figure_combined.pdf"
    output_path = directory / output

    doc = compose(rects, page_w, final_h, args.label_size, args.no_labels)
    doc.save(str(output_path))
    doc.close()
    print(f"Saved: {output_path}")

    if args.open:
        open_file(output_path)


# ---------------------------------------------------------------------------
# 8. Programmatic / interactive entry point
# ---------------------------------------------------------------------------

def interactive_compose(
    directory: str | Path,
    layout: str | None = None,
    ratios: str | None = None,
    row_heights: str | None = None,
    output: str | None = None,
    page_size: str = "A4",
    landscape: bool = False,
    label_size: float = 14,
    margin: float = 10,
    gap: float = 6,
    figure: int | None = None,
    no_labels: bool = False,
    open_after: bool = False,
) -> Path:
    """High-level API for composing figures — suitable for scripting or
    calling from Claude Code conversations.

    Returns the path to the generated PDF.
    """
    directory = Path(directory).resolve()
    panels, detected_num = detect_panels(directory)

    if not panels:
        raise FileNotFoundError(f"No panels found in {directory}")

    for p in panels:
        p.load_dims()

    fig_num = figure if figure is not None else detected_num
    n = len(panels)

    fig_label = f"Figure {fig_num}" if fig_num is not None else "Figure"
    print(f"{fig_label}: {n} panels detected")
    for p in panels:
        fmt = p.path.suffix.lower().lstrip(".")
        print(f"  {p.label}: {p.path.name}  ({p.src_w:.0f}\u00d7{p.src_h:.0f}, {fmt})")

    layout_list, inline_ratios = compute_layout(n, layout)
    print(f"Layout: {','.join(map(str, layout_list))}")

    panel_rows: list[list[Panel]] = []
    idx = 0
    for row_n in layout_list:
        panel_rows.append(panels[idx : idx + row_n])
        idx += row_n

    ratios_spec = ratios or inline_ratios
    ratio_list = compute_ratios(layout_list, ratios_spec, panel_rows)
    rh_weights = parse_row_heights(row_heights, len(layout_list))

    page_w, page_h = parse_page_size(page_size)
    if landscape:
        page_w, page_h = page_h, page_w

    rects, actual_h = compute_geometry(
        panel_rows, ratio_list, page_w, page_h,
        margin, gap, label_size, no_labels, rh_weights,
    )
    final_h = min(page_h, actual_h)

    if output:
        out_name = output
    elif fig_num is not None:
        out_name = f"Figure{fig_num}_combined.pdf"
    else:
        out_name = "Figure_combined.pdf"
    output_path = directory / out_name

    doc = compose(rects, page_w, final_h, label_size, no_labels)
    doc.save(str(output_path))
    doc.close()
    print(f"Saved: {output_path}")

    if open_after:
        open_file(output_path)

    return output_path
