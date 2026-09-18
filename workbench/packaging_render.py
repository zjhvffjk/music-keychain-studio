"""Editorial concept layouts. No invented tracks, lyrics or publisher marks."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
import fonts
from design_parts import read_design

NOTICE = "个人设计概念 · 非官方物料 · 非印刷文件"
PARTS = [("front", "Front Cover", "正面"), ("back", "Back Cover", "封底"),
         ("spine", "Spine", "侧脊"), ("disc", "CD Disc", "CD 盘面"),
         ("booklet_cover", "Booklet Cover", "歌词本封面"),
         ("booklet_spread", "Booklet Inside / Spread", "歌词本内页跨页"),
         ("lyrics", "Lyrics Page", "歌词页"),
         ("inner_sleeve", "Inner Sleeve / Gatefold", "内封套／折页"),
         ("poster", "Poster", "海报"), ("postcard", "Postcard", "明信片")]


def font(size, bold=False):
    return ImageFont.truetype(fonts.find_bold() if bold else fonts.find_regular(), size)


def text(draw, xy, value, size=32, fill="#eeeae1", width=1000, bold=False):
    value = str(value)
    f = font(size, bold)
    while draw.textlength(value, font=f) > width and size > 14:
        size -= 2
        f = font(size, bold)
    while draw.textlength(value, font=f) > width and len(value) > 1:
        value = value[:-2] + "…"
    draw.text(xy, value, font=f, fill=fill)


def style_of(im):
    d = read_design(im)
    return {"palette": ["#%02x%02x%02x" % tuple(c) for c in d["palette"]],
            "mood": d["mood"], "style": d["style"],
            "method": "封面色彩、明暗与边缘密度分析（不含人物或场景语义识别）"}


def fit(im, size):
    return ImageOps.fit(im.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def band(im, label):
    draw = ImageDraw.Draw(im)
    h = max(34, int(im.height * .03))
    draw.rectangle((0, im.height - h, im.width, im.height), fill="#181b1b")
    text(draw, (16, im.height - h + 6), label, size=max(16, h // 2), width=im.width - 32)
    return im


def scene_expansion(cover, style, seed=0):
    """Fallback scene language, deliberately not a crop of the supplied cover.

    It is a deterministic art-direction sketch for when an image workflow is
    unavailable: palette, grain, geometry and light are carried forward, but
    no portrait pixels are re-used. A generated scene can replace it later.
    """
    import numpy as np
    from PIL import ImageFilter
    palette = [tuple(int(x[i:i+2], 16) for i in (1, 3, 5)) for x in style["palette"][:5]]
    w = h = 1500
    rng = np.random.default_rng(seed + 913)
    base = Image.new("RGB", (w, h), palette[0])
    d = ImageDraw.Draw(base, "RGBA")
    for _ in range(24):
        color = palette[int(rng.integers(0, len(palette)))] + (int(rng.integers(20, 95)),)
        x, y = int(rng.integers(-300, w)), int(rng.integers(-300, h))
        r = int(rng.integers(120, 700))
        d.ellipse((x-r, y-r, x+r, y+r), fill=color)
    for i in range(18):
        y = int((i + .5) * h / 18)
        d.line((0, y, w, y + int(rng.integers(-60, 60))), fill=(255,255,255,10), width=int(rng.integers(1,8)))
    return base.filter(ImageFilter.GaussianBlur(18))


def _paper_texture(size, style, seed):
    import numpy as np
    rng = np.random.default_rng(seed)
    main = tuple(int(x[i:i+2], 16) for i in (1,3,5) for x in [style["palette"][2] if len(style["palette"]) > 2 else "#e7e1d5"])
    arr = np.full((size[1], size[0], 3), main, dtype=np.int16)
    arr += rng.normal(0, 3.8, arr.shape).astype(np.int16)
    return Image.fromarray(np.clip(arr,0,255).astype(np.uint8), "RGB")


def _asset(name, label, image, index, root):
    filename = f"parts/{index:02d}-{name}.png"
    image.save(root / filename)
    return {"id": name, "name": label, "file": filename, "width": image.width, "height": image.height,
            "status": "draft", "locked": False, "revision": 1}


def presentation_from_assets(directory, assets, album, artist):
    """Build the portfolio board from the currently approved asset files."""
    root = Path(directory)
    images = {key: Image.open(root / assets[key]).convert("RGB") for key, _, _ in PARTS}
    paper, ink = "#f3eee4", "#252b2a"
    board = Image.new("RGB", (2200, 1700), "#e5e0d6")
    d = ImageDraw.Draw(board)
    text(d, (80, 55), album, 54, ink, 1500, True)
    text(d, (84, 132), artist + " / PACKAGING STUDY", 24, ink, 1500)
    cells = [(80, 220, 340, 340), (450, 220, 340, 340), (825, 220, 110, 340), (980, 220, 340, 340),
             (1360, 220, 340, 340), (1730, 220, 390, 340), (80, 690, 290, 380), (420, 690, 450, 380),
             (940, 690, 300, 520), (1320, 690, 800, 520)]
    for number, ((key, en, label), (x, y, w, h)) in enumerate(zip(PARTS, cells), 1):
        im = images[key].copy()
        im.thumbnail((w, h - 44))
        px, py = x + (w - im.width) // 2, y + (h - 44 - im.height) // 2
        shadow = Image.new("RGBA", (im.width + 40, im.height + 40))
        ImageDraw.Draw(shadow).rectangle((20, 20, im.width + 20, im.height + 20), fill=(0, 0, 0, 55))
        shadow = shadow.filter(ImageFilter.GaussianBlur(12))
        board.paste(shadow, (px - 12, py - 10), shadow)
        board.paste(im, (px, py))
        text(d, (x, y + h - 24), f"{number:02d}  {en} / {label}", 18, ink, w)
    (root / "mockup").mkdir(exist_ok=True)
    filename = "mockup/album-packaging-presentation.png"
    band(board, NOTICE).save(root / filename)
    return {"name": "Presentation Mockup", "file": filename, "width": 2200, "height": 1700}


def render(directory, cover, artwork, album, artist, style, update, seed=0):
    root = Path(directory)
    p = root / "parts"
    p.mkdir(exist_ok=True)
    dark = tuple(max(8, int(v * .24)) for v in cover.resize((1, 1)).getpixel((0, 0)))
    paper, ink = "#f3eee4", "#252b2a"
    accent = style["palette"][min(1, len(style["palette"]) - 1)]
    images, results = {}, []
    # The reference is reserved for Front Cover. All other work starts from an
    # expanded scene (AI if supplied, otherwise a visibly labelled abstract
    # art-direction study) rather than another crop of the supplied cover.
    def scene_for(key):
        if isinstance(artwork, dict) and artwork.get(key) is not None:
            return artwork[key]
        if artwork is not None and not isinstance(artwork, dict):
            return artwork
        return scene_expansion(cover, style, seed + sum(ord(c) for c in key))

    front = Image.new("RGB", (1200, 1200), paper)
    front.paste(fit(cover, (1080, 950)), (60, 54))
    d = ImageDraw.Draw(front)
    text(d, (60, 1026), album, 54, ink, 840, True)
    text(d, (64, 1100), artist, 24, ink, 840)
    text(d, (970, 1095), "01 / COVER", 18, ink, 180)
    images["front"] = front

    back = Image.new("RGB", (1200, 1200), dark)
    back.paste(fit(scene_for("back"), (440, 1010)), (700, 65))
    d = ImageDraw.Draw(back)
    text(d, (64, 65), "THE OTHER SIDE", 22, width=560)
    d.line((64, 122, 636, 122), fill=accent, width=5)
    text(d, (64, 190), album, 70, width=570, bold=True)
    text(d, (68, 304), artist, 30, width=560)
    text(d, (68, 710), "曲目区留白", 36, width=560)
    text(d, (68, 775), "可在后续编辑中添加已核实的曲目", 24, width=560)
    text(d, (68, 1050), "PERSONAL DESIGN STUDY / 02", 20, width=560)
    images["back"] = back

    spine = Image.new("RGB", (180, 1200), dark)
    row = Image.new("RGB", (1030, 180), dark)
    d = ImageDraw.Draw(row)
    text(d, (35, 60), album + "   /   " + artist, 42, width=970, bold=True)
    spine.paste(row.rotate(90, expand=True), (0, 50))
    images["spine"] = spine

    disc = Image.new("RGB", (1200, 1200), paper)
    texture = fit(scene_for("disc"), (1080, 1080))
    mask = Image.new("L", texture.size)
    ImageDraw.Draw(mask).ellipse((0, 0, 1079, 1079), fill=255)
    disc.paste(texture, (60, 42), mask)
    d = ImageDraw.Draw(disc)
    d.ellipse((510, 492, 690, 672), fill=paper, outline="#c6c2b8", width=4)
    d.ellipse((90, 72, 1110, 1092), outline="#d0c7b0", width=3)
    d.rectangle((170, 860, 1030, 985), fill=dark)
    text(d, (208, 876), album, 36, width=790, bold=True)
    text(d, (210, 935), artist, 22, width=790)
    images["disc"] = disc

    booklet_cover = Image.new("RGB", (1200, 1200), dark)
    booklet_cover.paste(fit(scene_for("booklet_cover"), (1030, 840)), (85, 90))
    d = ImageDraw.Draw(booklet_cover)
    text(d, (88, 975), "NOTES / " + album, 48, "#f3eee4", 1020, True)
    text(d, (92, 1050), artist, 24, "#f3eee4", 1020)
    images["booklet_cover"] = booklet_cover

    booklet = _paper_texture((1800, 1200), style, seed)
    booklet.paste(fit(scene_for("booklet_spread"), (825, 1164)), (0, 0))
    d = ImageDraw.Draw(booklet)
    text(d, (975, 80), "NOTES & WORDS", 24, ink, 720)
    text(d, (975, 175), album, 58, ink, 730, True)
    text(d, (979, 280), artist, 26, ink, 720)
    d.rectangle((980, 460, 1028, 464), fill=accent)
    text(d, (980, 550), "歌词与创作手记", 38, ink, 720)
    text(d, (980, 625), "为你有权使用的文字保留位置。", 27, ink, 720)
    text(d, (980, 1000), "本页仅展示版式，不自动填写歌词。", 22, ink, 720)
    d.line((900, 0, 900, 1164), fill="#cec9bd", width=2)
    images["booklet_spread"] = booklet

    lyrics = _paper_texture((1200, 1200), style, seed + 1)
    lyrics.paste(fit(scene_for("lyrics"), (1040, 260)), (80, 390))
    d = ImageDraw.Draw(lyrics)
    text(d, (80, 84), "LYRICS / NOTES", 25, ink, 1000)
    text(d, (80, 165), album, 62, ink, 1000, True)
    text(d, (83, 255), artist, 26, ink, 1000)
    d.line((80, 345, 1120, 345), fill=accent, width=5)
    for row in range(8):
        y = 420 + row * 82
        d.line((82, y, 1080 - (row % 3) * 150, y), fill="#bcb5aa", width=2)
    text(d, (82, 1080), "留给已授权的歌词或创作文字", 22, ink, 1000)
    images["lyrics"] = lyrics

    sleeve = Image.new("RGB", (1800, 1200), dark)
    sleeve.paste(fit(scene_for("inner_sleeve"), (850, 1070)), (870, 60))
    d = ImageDraw.Draw(sleeve)
    text(d, (90, 100), "SIDE A", 24, "#f3eee4", 650)
    text(d, (90, 820), album, 76, "#f3eee4", 680, True)
    text(d, (94, 932), artist, 32, "#f3eee4", 680)
    d.line((900, 70, 900, 1130), fill=accent, width=3)
    images["inner_sleeve"] = sleeve

    poster = fit(scene_for("poster"), (1200, 1700))
    shade = Image.new("RGBA", poster.size)
    sd = ImageDraw.Draw(shade)
    for y in range(1700):
        a = int(220 * max(0, (y - 700) / 1000))
        sd.line((0, y, 1200, y), fill=(0, 0, 0, a))
    poster = Image.alpha_composite(poster.convert("RGBA"), shade).convert("RGB")
    d = ImageDraw.Draw(poster)
    text(d, (72, 78), "A PERSONAL ALBUM STUDY", 24, width=1056)
    text(d, (70, 1280), album, 104, width=1050, bold=True)
    text(d, (77, 1460), artist, 40, width=1040)
    images["poster"] = poster

    postcard = _paper_texture((1500, 1000), style, seed + 2)
    postcard.paste(fit(scene_for("postcard"), (900, 900)), (50, 50))
    d = ImageDraw.Draw(postcard)
    text(d, (1060, 90), "POSTCARD", 22, ink, 390)
    text(d, (1060, 460), album, 44, ink, 390, True)
    text(d, (1060, 560), artist, 24, ink, 390)
    for y in (730, 790, 850):
        d.line((1060, y, 1430, y), fill="#c5bfae", width=2)
    images["postcard"] = postcard

    for i, (key, en, label) in enumerate(PARTS, 1):
        im = band(images[key], NOTICE if key != "spine" else "非官方概念")
        results.append(_asset(key, en + " / " + label, im, i, root))
        update("正在设计：" + en, done=i, total=12)

    mockup = presentation_from_assets(root, {item["id"]: item["file"] for item in results}, album, artist)
    return results, mockup
