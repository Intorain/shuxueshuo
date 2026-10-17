"""Compose synthetic worksheet pages with known question boxes for segmentation tests.

Run from server/: uv run python tools/build_segment_pages.py
Writes page.png + gold.json per page under tests/search/fixtures/segment-pages/.
Record OCR afterwards with tools/record_segment_ocr.py.
"""

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

SERVER = Path(__file__).resolve().parents[1]
CORPUS = SERVER / "tests/solver/fixtures/graph-guided-stage-one/quadratic-always"
OUT = SERVER / "tests/search/fixtures/segment-pages"
SONG = "/System/Library/Fonts/Supplemental/Songti.ttc"
PAPER = (246, 244, 238)


def font(size):
    return ImageFont.truetype(SONG, size)


def question(case, width):
    image = Image.open(CORPUS / case / "source.png").convert("RGB")
    return image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)


def ink_rows(image):
    """First text row's vertical centre, so the number sits on the first line."""
    gray = image.convert("L")
    w, h = gray.size
    rows = [any(gray.getpixel((x, y)) < 128 for x in range(0, w, 3)) for y in range(h)]
    top = rows.index(True)
    bottom = top
    while bottom < h and rows[bottom]:
        bottom += 1
    return (top + bottom) / 2


def ink_box(image, left, top):
    gray = image.convert("L").point(lambda v: 255 if v < 160 else 0)
    box = gray.getbbox()
    return [left + box[0], top + box[1], left + box[2], top + box[3]]


def union(*boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


class Page:
    def __init__(self, width, height):
        self.image = Image.new("RGB", (width, height), PAPER)
        self.draw = ImageDraw.Draw(self.image)
        self.gold = []

    def text(self, xy, value, size, anchor="la"):
        self.draw.text(xy, value, fill=(25, 25, 25), font=font(size), anchor=anchor)
        return list(self.draw.textbbox(xy, value, font=font(size), anchor=anchor))

    def paste(self, image, x, y):
        """Multiply onto the paper so pasted questions have no white card around them."""
        region = (x, y, x + image.width, y + image.height)
        self.image.paste(ImageChops.multiply(self.image.crop(region), image), region[:2])

    def question(self, number, case, x, y, width, number_size=44):
        image = question(case, width)
        self.paste(image, x, y)
        centre = y + ink_rows(image)
        mark = self.text((x - 8, centre), f"{number}.", number_size, anchor="rm")
        box = union(mark, ink_box(image, x, y))
        self.gold.append({"number": number, "case": case, "box": box})
        return y + image.height

    def text_question(self, number, lines, x, y, size=48, gap=22):
        boxes = [self.text((x - 8, y), f"{number}.", size, anchor="ra")]
        for line in lines:
            boxes.append(self.text((x, y), line, size))
            y += size + gap
        self.gold.append({"number": number, "case": None, "box": union(*boxes)})
        return y

    def parabola(self, x, y, w, h):
        d = self.draw
        d.line((x, y + h * .75, x + w, y + h * .75), fill=(30, 30, 30), width=3)
        d.line((x + w * .35, y, x + w * .35, y + h), fill=(30, 30, 30), width=3)
        points = [(x + w * t / 60, y + h * .1 + (h * .8) * ((t / 60 - .55) / .45) ** 2) for t in range(61)]
        d.line([p for p in points if p[1] <= y + h], fill=(30, 30, 30), width=4)
        d.text((x + w * .35 + 10, y + h * .75 + 8), "O", fill=(30, 30, 30), font=font(36))
        d.text((x + w - 30, y + h * .75 + 8), "x", fill=(30, 30, 30), font=font(36))
        d.text((x + w * .35 + 10, y), "y", fill=(30, 30, 30), font=font(36))
        return [x, y, x + w, y + h]

    def save(self, name, note):
        directory = OUT / name
        directory.mkdir(parents=True, exist_ok=True)
        self.image.save(directory / "page.png")
        w, h = self.image.size
        gold = [{**g, "box": [round(v) for v in g["box"]]} for g in self.gold]
        (directory / "gold.json").write_text(json.dumps(
            {"page": name, "note": note, "width": w, "height": h, "questions": gold},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def single_column():
    page = Page(2100, 3000)
    page.text((1050, 90), "高一数学 · 不等式恒成立专项练习", 64, anchor="ma")
    page.text((1050, 190), "班级 ________    姓名 ________", 42, anchor="ma")
    y = 300
    y = page.question(7, "q01", 170, y, 1840) + 40
    y = page.text_question(8, ["求函数 y = sin x + cos x 的最大值。"], 230, y + 30) + 60
    y = page.question(9, "q04", 170, y, 1840) + 40
    y = page.question(10, "q10", 170, y, 1840) + 40
    y = page.question(11, "q02", 170, y, 1840) + 40
    page.question(12, "q11", 170, y, 1840)
    page.save("single-column", "题号 7–12 单栏；第 8 题为不支持的文字题")


def photo_skew():
    """single-column photographed slightly rotated, with uneven light."""
    import math

    source = OUT / "single-column"
    image = Image.open(source / "page.png")
    gold = json.loads((source / "gold.json").read_text(encoding="utf-8"))
    angle = 2.5
    rotated = image.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(90, 84, 76))
    shade = Image.linear_gradient("L").resize(rotated.size).point(lambda v: 255 - v // 4)
    rotated = ImageChops.multiply(rotated, Image.merge("RGB", (shade, shade, shade)))
    page = Page(*rotated.size)
    page.image = rotated
    cx, cy = image.width / 2, image.height / 2
    nx, ny = rotated.width / 2, rotated.height / 2
    a = math.radians(angle)

    def turn(x, y):
        dx, dy = x - cx, y - cy
        return nx + dx * math.cos(a) + dy * math.sin(a), ny - dx * math.sin(a) + dy * math.cos(a)

    for q in gold["questions"]:
        x0, y0, x1, y1 = q["box"]
        corners = [turn(x, y) for x in (x0, x1) for y in (y0, y1)]
        page.gold.append({**q, "box": [min(c[0] for c in corners), min(c[1] for c in corners),
                                       max(c[0] for c in corners), max(c[1] for c in corners)]})
    page.save("photo-skew", "single-column 旋转 2.5° 并加光照渐变")


def two_column():
    page = Page(2400, 1900)
    page.text((1200, 70), "第一章 测试卷（二）", 60, anchor="ma")
    page.draw.line((1200, 180, 1200, 1850), fill=(170, 170, 170), width=2)
    y = 200
    for number, case in ((1, "q01"), (2, "q02"), (3, "q04"), (4, "q09")):
        y = page.question(number, case, 130, y, 1020) + 60
    y = 200
    for number, case in ((5, "q05"), (6, "q06"), (7, "q07"), (8, "q03")):
        y = page.question(number, case, 1330, y, 1020) + 60
    page.save("two-column", "双栏，左 1–4、右 5–8，中间竖线")


def figure_and_sections():
    page = Page(2100, 2700)
    page.text((120, 80), "二、填空题（本大题共 2 小题）", 52)
    y = 180
    y = page.question(13, "q03", 200, y, 1800) + 50
    y = page.text_question(14, ["如图，二次函数 y = f(x) 的图象与 x 轴交于 A、B 两点，",
                                "且对任意 x∈[1,3]，y < 0 恒成立，求 c 的取值范围。"], 260, y)
    figure = page.parabola(1200, y + 20, 520, 420)
    page.gold[-1]["box"] = union(page.gold[-1]["box"], figure)
    page.gold[-1]["has_figure"] = True
    y = figure[3] + 80
    page.text((120, y), "三、解答题（本大题共 1 小题，解答应写出文字说明）", 52)
    y += 110
    page.question(15, "q08", 200, y, 1800)
    page.save("figure-and-sections", "大题标题分隔；第 14 题配图在题干下方")


def single_unnumbered():
    page = Page(2000, 620)
    image = question("q10", 1900)
    page.paste(image, 50, 70)
    page.gold.append({"number": None, "case": "q10", "box": ink_box(image, 50, 70)})
    page.save("single-unnumbered", "单题截图、没有题号")


if __name__ == "__main__":
    single_column()
    photo_skew()
    two_column()
    figure_and_sections()
    single_unnumbered()
    print(OUT)
