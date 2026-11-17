"""Local, page-sized UML rendering with matching SVG and 300-DPI PNG."""

import html
import math
import os
from functools import lru_cache
from pathlib import Path
import textwrap


WIDTH, HEIGHT = 3200, 2200
FONT_SIZE, LINE = 40, 52
COLORS = {
    "BIS": "#eaf1f8",
    "BRNS": "#eef5eb",
    "BRC": "#fff3e4",
    "common": "#f3f3f3",
}


@lru_cache(maxsize=16)
def load_font(path, size):
    from PIL import ImageFont

    return (
        ImageFont.truetype(path, size)
        if path
        else ImageFont.load_default(size=size)
    )


class Sheet:
    """Draw the same geometry to raster and vector surfaces."""

    def __init__(self, title, subtitle, font_path=None):
        from PIL import Image, ImageDraw

        self.image = Image.new("RGB", (WIDTH, HEIGHT), "white")
        self.draw = ImageDraw.Draw(self.image)
        path = font_path or os.getenv("BITEFINDER_UML_FONT")
        self.font_path = path
        self.font = load_font(path, FONT_SIZE)
        self.svg = [
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}">',
            '<rect width="100%" height="100%" fill="white"/>',
        ]
        self.boxes = {}
        self.bounds = []
        self.pending = []
        self.text((75, 35), title, size=48)
        self.text((75, 105), subtitle, size=30)

    def text(self, point, content, size=FONT_SIZE, color="#171717"):
        font = load_font(self.font_path, size)
        self.draw.text(point, content, font=font, fill=color)
        self.svg.append(
            f'<text x="{point[0]}" y="{point[1] + size}" '
            f'font-family="monospace" font-size="{size}" '
            f'fill="{color}">{html.escape(content)}</text>'
        )
        box = self.draw.textbbox(point, content, font=font)
        self.bounds.append(box)
        if box[2] > WIDTH - 30 or box[3] > HEIGHT - 25:
            raise ValueError(f"Text exceeds page bounds: {content}")

    def line(self, points, dashed=False, width=3, dotted=False):
        if dotted:
            for a, b in zip(points, points[1:]):
                length = math.dist(a, b)
                for offset in range(0, int(length) + 1, 12):
                    if length:
                        x = a[0] + (b[0] - a[0]) * offset / length
                        y = a[1] + (b[1] - a[1]) * offset / length
                        radius = width / 2
                        self.draw.ellipse(
                            (x - radius, y - radius, x + radius, y + radius),
                            fill="#333333",
                        )
        elif dashed:
            for a, b in zip(points, points[1:]):
                length = math.dist(a, b)
                for offset in range(0, int(length), 20):
                    end = min(offset + 11, length)
                    if length:
                        self.draw.line(
                            [
                                (
                                    a[0] + (b[0] - a[0]) * v / length,
                                    a[1] + (b[1] - a[1]) * v / length,
                                )
                                for v in (offset, end)
                            ],
                            fill="#333333",
                            width=width,
                        )
        else:
            self.draw.line(points, fill="#333333", width=width)
        coordinates = " ".join(f"{x},{y}" for x, y in points)
        dash = (
            ' stroke-dasharray="1 11" stroke-linecap="round"'
            if dotted
            else ' stroke-dasharray="12 8"'
            if dashed
            else ""
        )
        self.svg.append(
            f'<polyline points="{coordinates}" fill="none" '
            f'stroke="#333" stroke-width="{width}"{dash}/>'
        )

    def polygon(self, points, fill):
        self.draw.polygon(points, fill=fill, outline="#222222", width=3)
        coordinates = " ".join(f"{x},{y}" for x, y in points)
        self.svg.append(
            f'<polygon points="{coordinates}" fill="{fill}" '
            'stroke="#222" stroke-width="3"/>'
        )

    def rectangle(self, box, fill="white", outline=True):
        self.draw.rectangle(
            box, fill=fill, outline="#333333" if outline else None, width=3
        )
        x, y, r, b = box
        stroke = ' stroke="#333" stroke-width="3"' if outline else ""
        self.svg.append(
            f'<rect x="{x}" y="{y}" width="{r - x}" '
            f'height="{b - y}" fill="{fill}"{stroke}/>'
        )

    def wrapped(self, value, width):
        # Start with monospace columns, then measure for fallback fonts too.
        characters = max(12, int((width - 50) / (FONT_SIZE * 0.63)))
        lines = textwrap.wrap(
            value, characters, break_long_words=True, break_on_hyphens=False
        ) or [" "]
        result = []
        for line in lines:
            while self.draw.textlength(line, font=self.font) > width - 50:
                split = len(line) - 1
                while (
                    self.draw.textlength(line[:split], font=self.font)
                    > width - 50
                ):
                    split -= 1
                result.append(line[:split])
                line = line[split:]
            result.append(line)
        return result

    def box(
        self, key, title, groups, position, subsystem="common", context=False
    ):
        x, y, width = position
        lines = [
            [line for member in group for line in self.wrapped(member, width)]
            for group in ([title] + groups)
        ]
        height = sum(max(1, len(group)) * LINE + 28 for group in lines)
        if y + height > HEIGHT - 220:
            raise ValueError(f"Class box exceeds page: {key}")
        box = (x, y, x + width, y + height)
        self.rectangle(
            box, COLORS.get(subsystem, "#f3f3f3") if context else "white"
        )
        cursor = y
        for index, group in enumerate(lines):
            if index:
                self.line([(x, cursor), (x + width, cursor)])
            for offset, line in enumerate(group or [" "]):
                self.text((x + 20, cursor + 10 + offset * LINE), line)
            cursor += max(1, len(group)) * LINE + 28
        self.boxes[key] = box
        return height

    def relation(self, relation, number=0, detail=False):
        # Route only after every box exists, including later context boxes.
        self.pending.append((relation, number))

    def draw_relations(self):
        from uml_rendering import route_edges

        if not self.pending:
            return
        boxes = {
            key: (x, y, r - x, b - y, [])
            for key, (x, y, r, b) in self.boxes.items()
        }
        relations = [
            (r["from"], r["to"], r["kind"], str(n)) for r, n in self.pending
        ]
        ordinary = [r for r in relations if r[0] != r[1]]
        routed = iter(route_edges(boxes, ordinary, WIDTH, HEIGHT - 220))
        routes = []
        for source, target, kind, label in relations:
            if source != target:
                routes.append(next(routed))
                continue
            x, y, right, bottom, _ = boxes[source]
            right += x
            bottom += y
            side, gutter = (
                (right, right + 80) if right + 80 < WIDTH - 25 else (x, x - 60)
            )
            points = [
                (side, y + 60),
                (gutter, y + 60),
                (gutter, bottom - 60),
                (side, bottom - 60),
            ]
            routes.append((points, kind, label))
        occupied = []
        for (relation, number), (points, kind, _) in zip(self.pending, routes):
            start, end = points[0], points[-1]
            self.line(
                points,
                dashed=kind in ("dependency", "realisation"),
                dotted=kind == "association",
            )
            if kind in (
                "generalisation",
                "realisation",
                "dependency",
            ) or relation.get("directed"):
                self.marker(
                    end,
                    points[-2],
                    "triangle"
                    if kind in ("generalisation", "realisation")
                    else "arrow",
                )
            if kind in ("composition", "aggregation"):
                self.marker(
                    start,
                    points[1],
                    "filled" if kind == "composition" else "hollow",
                )
            for point, value, key, source_end in (
                (
                    start,
                    relation.get("from_multiplicity"),
                    relation["from"],
                    True,
                ),
                (end, relation.get("to_multiplicity"), relation["to"], False),
            ):
                if not value:
                    continue
                x, y, r, b = self.boxes[key]
                side_offset = -45 if source_end else 10
                if point[0] == x:
                    location = (max(0, x - 110), point[1] + side_offset)
                elif point[0] == r:
                    location = (r + 10, point[1] + side_offset)
                elif point[1] == y:
                    location = (point[0] + 20, y - 50)
                else:
                    location = (point[0] - 100, b + 10)
                self.text(location, value, size=30)
            label = str(number) if number else ""
            labels = relation.get("labels", [])
            if labels and not label:
                raw = labels[0]
                label = (
                    "HTTP"
                    if "HTTP" in raw
                    else "in-process"
                    if "in-process" in raw
                    else raw.removesuffix(" (default)").lstrip("_")
                )
                if len(label) > 25:
                    label = "uses" if kind == "dependency" else kind
            if label:
                font = load_font(self.font_path, 28)
                label_width = self.draw.textlength(label, font=font) + 16
                for first, last in sorted(
                    zip(points, points[1:]), key=lambda pair: -math.dist(*pair)
                ):
                    middle = (
                        (first[0] + last[0]) / 2,
                        (first[1] + last[1]) / 2,
                    )
                    rect = (
                        middle[0] - label_width / 2,
                        middle[1] - 20,
                        middle[0] + label_width / 2,
                        middle[1] + 30,
                    )

                    def overlaps(other):
                        return not (
                            rect[2] < other[0]
                            or rect[0] > other[2]
                            or rect[3] < other[1]
                            or rect[1] > other[3]
                        )

                    if any(
                        overlaps(other)
                        for other in list(self.boxes.values()) + occupied
                    ):
                        continue
                    self.rectangle(rect, outline=False)
                    self.text((rect[0] + 8, rect[1]), label, size=28)
                    occupied.append(rect)
                    break
        self.pending.clear()

    def marker(self, tip, toward, kind):
        dx, dy = toward[0] - tip[0], toward[1] - tip[1]
        length = math.hypot(dx, dy) or 1
        ux, uy = dx / length, dy / length
        size = 40
        side_a = (tip[0] + ux * size - uy * 15, tip[1] + uy * size + ux * 15)
        side_b = (tip[0] + ux * size + uy * 15, tip[1] + uy * size - ux * 15)
        if kind == "arrow":
            self.line([side_a, tip, side_b])
        elif kind == "triangle":
            self.polygon([tip, side_a, side_b], "white")
        else:
            other = (tip[0] + ux * size * 2, tip[1] + uy * size * 2)
            self.polygon(
                [tip, side_a, other, side_b],
                "black" if kind == "filled" else "white",
            )

    def footer(self, notes):
        font = load_font(self.font_path, 28)
        lines = []
        for note in notes:
            words, current = note.split(), ""
            for word in words:
                candidate = (current + " " + word).strip()
                if (
                    current
                    and self.draw.textlength(candidate, font=font) > 3050
                ):
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
        if len(lines) > 5:
            raise ValueError("Standalone annotations exceed the footer area")
        for index, note in enumerate(lines):
            self.text((75, HEIGHT - 195 + index * 35), note, size=28)

    def save(self, path):
        self.draw_relations()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(
            path.with_suffix(".png"), dpi=(300, 300), compress_level=1
        )
        path.with_suffix(".svg").write_text(
            "\n".join(self.svg + ["</svg>"]), encoding="utf-8"
        )
