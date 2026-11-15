"""Graph-based UML layout, compartmented class boxes, and routed edges."""
from __future__ import annotations

from collections import defaultdict, deque
import heapq
import html
import math
from pathlib import Path
import shutil
import subprocess
import textwrap

from uml_analysis import visibility

COLORS = {'BIS': '#e9f2fb', 'BRNS': '#eaf5eb', 'BRC': '#fff2df'}
KINDS = {'inherits': ('empty', 'solid', '--|>'),
         'implements': ('empty', 'dashed', '..|>'),
         'composition': ('diamond', 'solid', '*--'),
         'aggregation': ('odiamond', 'solid', 'o--'),
         'association': ('vee', 'solid', '-->'),
         'creates': ('vee', 'dashed', '..>'), 'calls': ('vee', 'dashed', '..>'),
         'http': ('vee', 'dashed', '..>')}


def identifier(key):
    return 'C_' + key.replace('.', '_')


def reduced_edges(relationships, flow=False):
    grouped = defaultdict(set)
    priority = {'inherits': 0, 'implements': 1, 'composition': 2,
                'aggregation': 3, 'association': 4, 'creates': 5, 'calls': 6, 'http': 7}
    for source, target, kind, label, _ in relationships:
        if flow and kind not in ('calls', 'creates', 'http'):
            continue
        grouped[source, target, kind].add(label)
    result = []
    for (source, target, kind), labels in sorted(grouped.items()):
        if not flow and kind in ('creates', 'calls') and any(
                s == source and t == target and priority[k] < priority[kind]
                for s, t, k in grouped):
            continue
        label = ', '.join(sorted(filter(None, labels)))
        result.append((source, target, kind, label))
    return result


def sections(record, compact=False):
    stereotype = '<<interface>>' if record['name'].endswith('Interface') else '<<abstract>>' if record['abstract'] else 'class'
    header = [stereotype + ' ' + record['name'], record['module']]
    attrs = [visibility(n) + ' ' + n + ': ' + t for n, t in sorted(record['attributes'].items())]
    return [header] if compact else [header, attrs or [' '], record['methods'] or [' ']]


def sources(classes, edges, flow=False):
    dot = ['digraph BiteFinder {', 'graph [rankdir=TB, nodesep=0.65, ranksep=1.0, overlap=false, splines=polyline, bgcolor="white"];',
           'node [shape=plain, fontname="Helvetica"];', 'edge [fontname="Helvetica", fontsize=10];']
    plant = ['@startuml', 'skinparam classBackgroundColor #F0F0F0', 'skinparam classBorderColor #777777']
    for key, record in sorted(classes.items()):
        rows = []
        for group in sections(record, flow):
            lines = [html.escape(line) for member in group for line in (textwrap.wrap(member, 65) or [' '])]
            rows.append('<TR><TD ALIGN="LEFT">' + '<BR ALIGN="LEFT"/>'.join(lines) + '<BR ALIGN="LEFT"/></TD></TR>')
        table = '<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="6" BGCOLOR="' + COLORS[record['subsystem']] + '">' + '<HR/>'.join(rows) + '</TABLE>'
        dot.append(f'{identifier(key)} [label=<{table}>];')
        kind = 'interface' if record['name'].endswith('Interface') else 'abstract class' if record['abstract'] else 'class'
        plant.append(f'{kind} "{record["name"]}" as {identifier(key)} {{')
        for group in sections(record)[1:]:
            plant.extend(group)
            plant.append('--')
        plant.append('}')
    for source, target, kind, label in reduced_edges(edges, flow):
        head, style, arrow = KINDS[kind]
        escaped = (kind + (': ' + label if label else '')).replace('"', '\\"')
        if kind in ('composition', 'aggregation'):
            dot.append(f'{identifier(source)} -> {identifier(target)} [dir=both, arrowtail={head}, arrowhead=none, style={style}, label="{escaped}"];')
        else:
            dot.append(f'{identifier(source)} -> {identifier(target)} [arrowhead={head}, style={style}, label="{escaped}"];')
        plant.append(f'{identifier(source)} {arrow} {identifier(target)} : {escaped}')
    return '\n'.join(plant + ['@enduml']) + '\n', '\n'.join(dot + ['}']) + '\n'


def graph_layout(classes, edges, compact=False):
    """Place connected neighborhoods in multiple rows, ordered by graph distance."""
    adjacency = {key: set() for key in classes}
    for s, t, *_ in edges:
        if s in adjacency and t in adjacency and s != t:
            adjacency[s].add(t)
            adjacency[t].add(s)
    components, unseen = [], set(classes)
    while unseen:
        start = min(unseen)
        queue, component = [start], set()
        while queue:
            key = queue.pop()
            if key in component:
                continue
            component.add(key)
            queue.extend(adjacency[key] - component)
        unseen -= component
        components.append(component)
    singles = set().union(*(c for c in components if len(c) == 1)) if components else set()
    components = [c for c in components if len(c) > 1]
    if singles:
        components.append(singles)
    boxes, y = {}, 130
    width = 420 if compact else 650
    columns = max(2, min(6, math.ceil(math.sqrt(len(classes) or 1))))
    for component in sorted(components, key=lambda c: (-len(c), min(c))):
        # Central collaborators begin the neighborhood; graph distance orders rows.
        start = min(component, key=lambda k: (-len(adjacency[k]), k))
        queue, depth = deque([start]), {start: 0}
        while queue:
            key = queue.popleft()
            for neighbor in sorted(adjacency[key]):
                if neighbor not in depth:
                    depth[neighbor] = depth[key] + 1
                    queue.append(neighbor)
        ordered = sorted(component, key=lambda k: (depth.get(k, 1), -len(adjacency[k]), k))
        for index in range(0, len(ordered), columns):
            row = ordered[index:index + columns]
            heights = []
            for col, key in enumerate(row):
                wrapped = [[line for member in group for line in (textwrap.wrap(member, 65 if not compact else 45, break_long_words=True) or [' '])]
                           for group in sections(classes[key], compact)]
                height = sum(len(group) * 22 + 20 for group in wrapped)
                boxes[key] = (80 + col * (width + 180), y, width, height, wrapped)
                heights.append(height)
            y += max(heights) + 150
        y += 80
    return boxes, columns * (width + 180) + 80, y + 60


def route_edges(boxes, edges, width, height):
    """A* routing on a shared grid; class interiors are excluded from routes."""
    step = 30
    blocked, usage = set(), defaultdict(int)
    for x, y, w, h, _ in boxes.values():
        for gx in range(math.floor(x / step), math.ceil((x + w) / step) + 1):
            for gy in range(math.floor(y / step), math.ceil((y + h) / step) + 1):
                blocked.add((gx, gy))
    xmax, ymax = math.ceil(width / step), math.ceil(height / step)

    def ports(key):
        x, y, w, h, _ = boxes[key]
        return [((math.floor(x / step) - 1, round((y + h / 2) / step)), (x, y + h / 2)),
                ((math.ceil((x + w) / step) + 1, round((y + h / 2) / step)), (x + w, y + h / 2)),
                ((round((x + w / 2) / step), math.floor(y / step) - 1), (x + w / 2, y)),
                ((round((x + w / 2) / step), math.ceil((y + h) / step) + 1), (x + w / 2, y + h))]

    routes = []
    for source, target, kind, label in edges:
        if source not in boxes or target not in boxes:
            continue
        start, end = min(((a, b) for a in ports(source) for b in ports(target)),
                         key=lambda pair: math.dist(pair[0][0], pair[1][0]))
        first, last = start[0], end[0]
        heap, previous, cost = [(0, first)], {}, {first: 0}
        while heap:
            _, current = heapq.heappop(heap)
            if current == last:
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbor = (current[0] + dx, current[1] + dy)
                if neighbor in blocked or not (0 <= neighbor[0] <= xmax and 3 <= neighbor[1] <= ymax):
                    continue
                new = cost[current] + 1 + min(usage[neighbor], 4) * .2
                if new < cost.get(neighbor, float('inf')):
                    previous[neighbor], cost[neighbor] = current, new
                    heuristic = abs(neighbor[0] - last[0]) + abs(neighbor[1] - last[1])
                    heapq.heappush(heap, (new + heuristic, neighbor))
        if last != first and last not in previous:
            raise RuntimeError(f'Cannot route {source} -> {target}; install Graphviz for this graph.')
        path, current = [last], last
        while current != first:
            current = previous[current]
            path.append(current)
        path.reverse()
        for point in path:
            usage[point] += 1
        points = [start[1]] + [(x * step, y * step) for x, y in path] + [end[1]]
        # Remove collinear points for compact SVG and labels on straight segments.
        simplified = [points[0]]
        for index in range(1, len(points) - 1):
            a, b, c = simplified[-1], points[index], points[index + 1]
            if (b[0] - a[0]) * (c[1] - b[1]) != (b[1] - a[1]) * (c[0] - b[0]):
                simplified.append(b)
        routes.append((simplified + [points[-1]], kind, label))
    return routes


def render(classes, edges, path, compact=False):
    from PIL import Image, ImageDraw, ImageFont
    plant, dot_source = sources(classes, edges, compact)
    displayed = reduced_edges(edges, compact)
    import json
    path.with_suffix('.edges.json').write_text(json.dumps([
        dict(number=index, source=s, target=t, kind=k, detail=label)
        for index, (s, t, k, label) in enumerate(displayed, 1)
    ], indent=2), encoding='utf-8')
    path.with_suffix('.puml').write_text(plant, encoding='utf-8')
    path.with_suffix('.dot').write_text(dot_source, encoding='utf-8')
    dot = shutil.which('dot')
    if dot:
        for suffix in ('png', 'svg'):
            subprocess.run([dot, '-T' + suffix, str(path.with_suffix('.dot')), '-o', str(path.with_suffix('.' + suffix))], check=True)
        return
    boxes, width, height = graph_layout(classes, edges, compact)
    routes = route_edges(boxes, displayed, width, height)
    image = Image.new('RGB', (width, height), 'white')
    draw, font = ImageDraw.Draw(image), ImageFont.load_default(size=16)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="white"/>']
    def line(a, b, dashed=False):
        length = math.dist(a, b)
        if dashed and length:
            for distance in range(0, math.ceil(length), 14):
                p = tuple(a[i] + (b[i] - a[i]) * distance / length for i in (0, 1))
                q = tuple(a[i] + (b[i] - a[i]) * min(distance + 8, length) / length for i in (0, 1))
                draw.line((p, q), fill='#555555', width=2)
        else:
            draw.line((a, b), fill='#555555', width=2)
        svg.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#555" stroke-width="2"' + (' stroke-dasharray="8 6"' if dashed else '') + '/>')
    def label(position, value, color='black'):
        draw.text(position, value, font=font, fill=color)
        svg.append(f'<text x="{position[0]}" y="{position[1] + 16}" font-family="monospace" font-size="16" fill="{color}">{html.escape(value)}</text>')
    label((40, 20), 'BiteFinder: ' + ('static method dependencies' if compact else 'UML classes and source-evidenced relationships'))
    label((40, 48), 'Triangle: inheritance / interface | Diamond: owned construction / injected collection | Arrow: association / dependency')
    occupied_labels = []
    def intersects(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
    obstacles = [(x, y, x + w, y + h) for x, y, w, h, _ in boxes.values()]
    for number, (points, kind, name) in enumerate(routes, 1):
        svg.append('<g><title>' + html.escape(f'#{number} {kind}: {name}') + '</title>')
        for a, b in zip(points, points[1:]):
            line(a, b, kind in ('implements', 'creates', 'calls', 'http'))
        tail = kind in ('composition', 'aggregation')
        end, before = (points[0], points[1]) if tail else (points[-1], points[-2])
        dx, dy = before[0] - end[0], before[1] - end[1]
        length = math.hypot(dx, dy) or 1
        ux, uy = dx / length, dy / length
        arrow = [end, (end[0] + ux * 15 - uy * 7, end[1] + uy * 15 + ux * 7)]
        if tail:
            arrow.append((end[0] + ux * 30, end[1] + uy * 30))
        arrow.append((end[0] + ux * 15 + uy * 7, end[1] + uy * 15 - ux * 7))
        fill = 'white' if kind in ('inherits', 'implements', 'aggregation') else '#555555'
        if kind in ('creates', 'calls', 'association', 'http'):
            draw.line((arrow[1], arrow[0], arrow[-1]), fill='#555555', width=2)
            svg.append('<polyline points="' + ' '.join(f'{x},{y}' for x, y in [arrow[1], arrow[0], arrow[-1]]) + '" fill="none" stroke="#555" stroke-width="2"/>')
        else:
            draw.polygon(arrow, fill=fill, outline='#555555', width=2)
            svg.append('<polygon points="' + ' '.join(f'{x},{y}' for x, y in arrow) + f'" fill="{fill}" stroke="#555" stroke-width="2"/>')
        caption = f'#{number} {kind}' + (': ' + name if name and not compact else '')
        chunks = textwrap.wrap(caption, 38)
        label_width = max(draw.textlength(chunk, font=font) for chunk in chunks) + 8
        label_height = len(chunks) * 18 + 4
        location = None
        for a, b in sorted(zip(points, points[1:]), key=lambda pair: -math.dist(*pair)):
            for fraction in (.5, .25, .75):
                mid = (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)
                for dx, dy in ((6, 6), (-label_width - 6, 6), (6, -label_height - 6)):
                    rect = (mid[0] + dx, mid[1] + dy, mid[0] + dx + label_width, mid[1] + dy + label_height)
                    if rect[0] >= 0 and rect[1] >= 75 and rect[2] < width and rect[3] < height and not any(intersects(rect, other) for other in obstacles + occupied_labels):
                        location = rect
                        break
                if location:
                    break
            if location:
                break
        if location:
            occupied_labels.append(location)
            draw.rectangle(location, fill='white')
            svg.append(f'<rect x="{location[0]}" y="{location[1]}" width="{label_width}" height="{label_height}" fill="white"/>')
            for index, chunk in enumerate(chunks):
                label((location[0] + 2, location[1] + index * 18), chunk, '#555555')
        # Every edge retains its full detail in SVG tooltips and .edges.json.
        svg.append('</g>')
    for key, (x, y, w, h, groups) in boxes.items():
        fill = COLORS[classes[key]['subsystem']]
        draw.rectangle((x, y, x + w, y + h), fill=fill, outline='#777777', width=2)
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#777"/>')
        cursor = y
        for index, group in enumerate(groups):
            if index:
                line((x, cursor), (x + w, cursor))
            cursor += 10
            for member in group:
                label((x + 12, cursor), member)
                cursor += 22
            cursor += 10
    image.save(path)
    path.with_suffix('.svg').write_text('\n'.join(svg + ['</svg>']), encoding='utf-8')
