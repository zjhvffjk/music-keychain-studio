"""Deterministic print-ready exports for the packaging workbench.

AI is never asked to draw dimensions, bleed, cutting or folding guides.  All
geometry in this module is calculated in millimetres and rendered at 300 DPI.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

import make_minicd as MINI

DPI = 300
BLEED_MM = 3.0
SAFE_MM = 3.0
PAGES = {"a4": (297.0, 210.0), "a3": (420.0, 297.0)}


def mm(value, dpi=DPI):
    return int(round(value * dpi / 25.4))


def _crop(im, width, height):
    return ImageOps.fit(im.convert("RGB"), (width, height), Image.Resampling.LANCZOS)


def _guides(canvas, box, bleed=BLEED_MM, safe=SAFE_MM, dpi=DPI, fold_x=()):
    """Draw cut = solid black, bleed = red, safe = green, fold = blue dashed."""
    d = ImageDraw.Draw(canvas)
    x, y, w, h = box
    b, s = mm(bleed, dpi), mm(safe, dpi)
    d.rectangle((x, y, x + w, y + h), outline=(16, 16, 16), width=max(2, mm(.35, dpi)))
    d.rectangle((x - b, y - b, x + w + b, y + h + b), outline=(208, 72, 68), width=max(1, mm(.22, dpi)))
    if w > 2 * s and h > 2 * s:
        d.rectangle((x + s, y + s, x + w - s, y + h - s), outline=(64, 144, 100), width=max(1, mm(.2, dpi)))
    for offset in fold_x:
        xx = x + offset
        dash = mm(2, dpi)
        for yy in range(y, y + h, dash * 2):
            d.line((xx, yy, xx, min(yy + dash, y + h)), fill=(50, 100, 176), width=max(1, mm(.24, dpi)))


def _page(kind, dpi=DPI):
    w_mm, h_mm = PAGES[kind]
    return Image.new("RGB", (mm(w_mm, dpi), mm(h_mm, dpi)), "white"), w_mm, h_mm


def _label(draw, xy, name, size=mm(3)):
    from PIL import ImageFont
    import fonts
    f = ImageFont.truetype(fonts.find_regular(), size)
    draw.text(xy, name, font=f, fill=(70, 70, 70))


def export_print_ready(root, assets, album, artist, page_kind="a4", dpi=DPI):
    """Export flat artwork at exact physical dimensions and one A4/A3 cut sheet.

    Specs are a mini CD package: disc Ø40mm (Ø5mm hole), folded booklet
    82×41mm, and continuous back strip 111.2×38mm.  The delivered manifest
    lets a later product-specific template replace these dimensions safely.
    """
    root = Path(root) / "print-ready"
    root.mkdir(exist_ok=True)
    source = {k: Image.open(v).convert("RGB") for k, v in assets.items()}
    parts = {}
    # Exact flat parts, expanded with 3 mm bleed around the finished trim size.
    specs = {
        "front": (41.0, 41.0, "01-front-with-bleed.png"),
        "back": (48.0, 38.0, "02-back-with-bleed.png"),
        "booklet_cover": (41.0, 41.0, "03-booklet-cover-with-bleed.png"),
        "booklet_spread": (82.0, 41.0, "04-booklet-spread-with-bleed.png"),
        "lyrics": (41.0, 41.0, "05-lyrics-with-bleed.png"),
        "inner_sleeve": (48.0, 38.0, "06-inner-sleeve-with-bleed.png"),
    }
    manifest = {"dpi": dpi, "bleed_mm": BLEED_MM, "safe_area_mm": SAFE_MM,
                "page": page_kind.upper(), "product": "Mini CD package",
                "disc": {"outer_diameter_mm": MINI.DISC_D, "center_hole_mm": MINI.DISC_HOLE},
                "files": []}
    for key, (w_mm, h_mm, filename) in specs.items():
        if key not in source:
            continue
        finished = _crop(source[key], mm(w_mm, dpi), mm(h_mm, dpi))
        full = _crop(source[key], mm(w_mm + BLEED_MM * 2, dpi), mm(h_mm + BLEED_MM * 2, dpi))
        d = ImageDraw.Draw(full)
        b, s = mm(BLEED_MM, dpi), mm(SAFE_MM, dpi)
        d.rectangle((b, b, full.width-b, full.height-b), outline=(16, 16, 16), width=max(2, mm(.35, dpi)))
        d.rectangle((b+s, b+s, full.width-b-s, full.height-b-s), outline=(64, 144, 100), width=max(1, mm(.2, dpi)))
        full.save(root / filename, dpi=(dpi, dpi))
        parts[key] = finished
        manifest["files"].append({"file": filename, "trim_mm": [w_mm, h_mm]})

    disc_d, hole_d = mm(MINI.DISC_D, dpi), mm(MINI.DISC_HOLE, dpi)
    disc = _crop(source["disc"], disc_d, disc_d)
    mask = Image.new("L", (disc_d, disc_d), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, disc_d-1, disc_d-1), fill=255)
    disc_sheet = Image.new("RGB", (disc_d + 2*mm(BLEED_MM, dpi), disc_d + 2*mm(BLEED_MM, dpi)), "white")
    disc_sheet.paste(disc, (mm(BLEED_MM, dpi), mm(BLEED_MM, dpi)), mask)
    dd = ImageDraw.Draw(disc_sheet)
    cx = disc_sheet.width // 2
    cy = disc_sheet.height // 2
    dd.ellipse((cx - disc_d//2, cy - disc_d//2, cx + disc_d//2, cy + disc_d//2), outline=(16,16,16), width=max(2, mm(.35,dpi)))
    dd.ellipse((cx - hole_d//2, cy - hole_d//2, cx + hole_d//2, cy + hole_d//2), fill="white", outline=(16,16,16), width=max(1,mm(.25,dpi)))
    disc_sheet.save(root / "07-disc-with-bleed.png", dpi=(dpi, dpi))
    manifest["files"].append({"file": "07-disc-with-bleed.png", "trim_mm": [MINI.DISC_D, MINI.DISC_D], "hole_mm": MINI.DISC_HOLE})

    # Use the existing proven mini-CD geometry to make a cut/fold sheet.
    mini_parts = {
        "cover": (parts.get("front", source["front"]), False),
        "inner": (parts.get("booklet_cover", source.get("booklet_cover", source["front"])), False),
        "back": (parts.get("back", source["back"]), False),
        "tray": (parts.get("inner_sleeve", source.get("inner_sleeve", source["back"])), False),
        "disc": (disc, False),
    }
    # The three physical strips need A4 landscape; portrait A4 is too narrow.
    page_arg = "a4l"
    page, sets, _ = MINI.build_page(mini_parts, dpi, page=page_arg, max_sets=1, artist=artist, album=album)
    page.save(root / f"08-cut-fold-sheet-{page_kind.upper()}-300dpi.png", dpi=(dpi, dpi))
    page.save(root / f"08-cut-fold-sheet-{page_kind.upper()}-300dpi.pdf", "PDF", resolution=dpi)
    manifest["files"].append({"file": f"08-cut-fold-sheet-{page_kind.upper()}-300dpi.png", "page_mm": list(PAGES[page_kind]), "sets": sets, "cut_line": "black", "fold_line": "blue dashed", "safe_area": "green"})
    # A3 is a separate exact physical page.  The production geometry remains
    # unscaled, so trim sizes are identical when either page is printed at 100%.
    a3 = Image.new("RGB", (mm(420, dpi), mm(297, dpi)), "white")
    a3.paste(page, ((a3.width - page.width) // 2, (a3.height - page.height) // 2))
    a3.save(root / "09-cut-fold-sheet-A3-300dpi.png", dpi=(dpi, dpi))
    a3.save(root / "09-cut-fold-sheet-A3-300dpi.pdf", "PDF", resolution=dpi)
    manifest["files"].append({"file": "09-cut-fold-sheet-A3-300dpi.png", "page_mm": [420, 297], "sets": sets, "note": "same 100% production geometry, centered on A3"})
    (root / "print-ready-manifest.json").write_text(__import__("json").dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return [{"name": "A4 裁切折线拼版", "file": f"print-ready/08-cut-fold-sheet-{page_kind.upper()}-300dpi.png", "kind": "print"},
            {"name": "A3 裁切折线拼版", "file": "print-ready/09-cut-fold-sheet-A3-300dpi.png", "kind": "print"},
            {"name": "印刷规格说明", "file": "print-ready/print-ready-manifest.json", "kind": "manifest"}]
