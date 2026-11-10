"""Generate source-derived UML boxes and relationships without running BiteFinder.

Run: python project_overview/test_uml.py
Requires Pillow (requirements-dev.txt). Graphviz's optional `dot` executable
provides automatic edge routing. Otherwise a Pillow layout is used. Outputs
PNG, DOT, PlantUML and relationship evidence JSON in project_overview/uml/.
Static references show dependencies, not runtime sequence or proven ownership.
"""
from __future__ import annotations

import ast
from collections import defaultdict
import html
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).resolve().parent / 'uml'
SUBSYSTEMS = ('BIS', 'BRNS', 'BRC')


def safe_id(value):
    return re.sub(r'\W', '_', value)


def visibility(name):
    return '-' if name.startswith('__') and not name.endswith('__') else '#' if name.startswith('_') and not name.startswith('__') else '+'


def expression(node):
    return ast.unparse(node) if node is not None else '?'


def discover_classes(root=ROOT):
    """Resolve qualified names, including re-exports; never pick by short name."""
    classes, modules, aliases = {}, {}, {}
    for subsystem in SUBSYSTEMS:
        for path in sorted((root / subsystem).rglob('*.py')):
            if '__pycache__' in path.parts or '.venv' in path.parts:
                continue
            parts = list(path.relative_to(root).with_suffix('').parts)
            package = parts[-1] == '__init__'
            if package:
                parts.pop()
            module = '.'.join(parts)
            tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
            modules[module] = tree
            names = aliases.setdefault(module, {})
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    base = parts if package else parts[:-1]
                    prefix = '.'.join(base[:len(base) - node.level + 1]) if node.level else ''
                    prefix = '.'.join(filter(None, (prefix, node.module)))
                    for item in node.names:
                        names[item.asname or item.name] = prefix + '.' + item.name
                elif isinstance(node, ast.Import):
                    for item in node.names:
                        names[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                key = module + '.' + node.name
                attributes, methods = {}, []
                for member in node.body:
                    if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
                        attributes[member.target.id] = expression(member.annotation)
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        params = []
                        for arg in member.args.posonlyargs + member.args.args + member.args.kwonlyargs:
                            if arg.arg not in ('self', 'cls'):
                                params.append(arg.arg + (': ' + expression(arg.annotation) if arg.annotation else ''))
                        methods.append(visibility(member.name) + ' ' + member.name + '(' + ', '.join(params) + ')' + (' : ' + expression(member.returns) if member.returns else ''))
                        for assignment in ast.walk(member):
                            targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target] if isinstance(assignment, ast.AnnAssign) else []
                            for target in targets:
                                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                                    annotation = assignment.annotation if isinstance(assignment, ast.AnnAssign) else None
                                    attributes[target.attr] = expression(annotation) if annotation else '?'
                classes[key] = dict(name=node.name, module=module, subsystem=subsystem,
                                    node=node, attributes=attributes, methods=methods,
                                    path=str(path.relative_to(root)), line=node.lineno)

    def resolve(module, name):
        value = module + '.' + name if name.split('.')[0] not in aliases[module] else aliases[module][name.split('.')[0]] + name[len(name.split('.')[0]):]
        seen = set()
        while value not in seen:
            seen.add(value)
            if value in classes:
                return value
            prefix, _, tail = value.rpartition('.')
            replacement = aliases.get(prefix, {}).get(tail)
            if not replacement:
                break
            value = replacement
        return None

    relationships = set()
    for key, record in classes.items():
        node, module = record['node'], record['module']
        for base in node.bases:
            target = resolve(module, expression(base))
            if target:
                kind = 'implements' if classes[target]['name'].endswith('Interface') else 'inherits'
                relationships.add((key, target, kind, f"{record['path']}:{base.lineno}"))
        # Only this class's body, not every constructor in the containing module.
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                target = resolve(module, expression(child.func))
                if target and target != key:
                    relationships.add((key, target, 'creates', f"{record['path']}:{child.lineno}"))
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                target = resolve(module, child.id)
                if target and target != key and child.id not in [expression(b) for b in node.bases]:
                    relationships.add((key, target, 'uses', f"{record['path']}:{child.lineno}"))
    return classes, sorted(relationships)


def members(record):
    return [visibility(name) + ' ' + name + ': ' + typ for name, typ in sorted(record['attributes'].items())], record['methods']


def render_diagrams(classes, relationships):
    """Generate editable UML and Graphviz sources with compartmented boxes."""
    dot = ['digraph BiteFinder {', 'graph [rankdir=TB, nodesep=0.5, ranksep=1.0, bgcolor="white", overlap=false];', 'node [shape=plain, fontname="Helvetica"];', 'edge [fontname="Helvetica", fontsize=10, color="#555555"];']
    plant = ['@startuml', 'skinparam classBackgroundColor #F0F0F0', 'skinparam classBorderColor #777777', 'hide circle']
    for subsystem in SUBSYSTEMS:
        dot.append(f'subgraph cluster_{subsystem} {{ label="{subsystem}"; color="#CCCCCC";')
        plant.append(f'package {subsystem} {{')
        for key, record in sorted(classes.items()):
            if record['subsystem'] != subsystem:
                continue
            attrs, methods = members(record)
            title = record['name']
            rows = [f'<B>{html.escape(title)}</B><BR/><FONT POINT-SIZE="9">{html.escape(record["module"])}</FONT>']
            rows += ['<BR ALIGN="LEFT"/>'.join(html.escape(text) for text in group) + '<BR ALIGN="LEFT"/>' if group else ' ' for group in (attrs, methods)]
            table = '<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="6" BGCOLOR="#F0F0F0">' + '<HR/>'.join('<TR><TD ALIGN="LEFT">' + row + '</TD></TR>' for row in rows) + '</TABLE>'
            dot.append(f'{safe_id(key)} [label=<{table}>];')
            plant.extend([f'class "{title}" as {safe_id(key)} {{', *attrs, '--', *methods, '}'])
        dot.append('}')
        plant.append('}')
    edges = sorted({(s, t, k) for s, t, k, _ in relationships})
    for source, target, kind in edges:
        if kind == 'uses' and any(s == source and t == target and k != 'uses' for s, t, k in edges):
            continue
        head = 'empty' if kind in ('inherits', 'implements') else 'vee'
        style = 'solid' if kind == 'inherits' else 'dashed'
        dot.append(f'{safe_id(source)} -> {safe_id(target)} [arrowhead={head}, style={style}, label="{kind}"];')
        arrow = '--|>' if kind == 'inherits' else '..|>' if kind == 'implements' else '..>'
        plant.append(f'{safe_id(source)} {arrow} {safe_id(target)} : {kind}')
    return '\n'.join(plant + ['@enduml']) + '\n', '\n'.join(dot + ['}']) + '\n'


def render_png(classes, relationships, path):
    """Render with Graphviz when installed; use a dependency-free Pillow layout otherwise."""
    dot = shutil.which('dot')
    if dot:
        subprocess.run([dot, '-Tpng', str(path.with_suffix('.dot')), '-o', str(path)], check=True)
        return
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.load_default(size=15)
    title_font = ImageFont.load_default(size=18)
    probe = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    boxes, groups = {}, defaultdict(list)
    for key in sorted(classes):
        record = classes[key]
        attrs, methods = members(record)
        groups[record['subsystem']].append((key, [[record['name'], record['module']], attrs or [' '], methods or [' ']]))
    x, canvas_height = 50, 0
    for subsystem in SUBSYSTEMS:
        group = groups[subsystem]
        if not group:
            continue
        width = max([400] + [math.ceil(probe.textlength(line, font=font)) + 36 for _, sections in group for section in sections for line in section])
        y = 120
        for key, sections in group:
            height = sum(max(1, len(s)) * 23 + 18 for s in sections)
            boxes[key] = (x, y, width, height, sections)
            y += height + 100
        canvas_height = max(canvas_height, y)
        x += width + 220
    image = Image.new('RGB', (x, canvas_height + 80), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((40, 20), 'BiteFinder UML | dashed dependencies; hollow triangles: inheritance / implementation', fill='black', font=font)
    # Route edges outside compartments, then paint boxes on top.
    for source, target, kind in sorted({(s, t, k) for s, t, k, _ in relationships}):
        sx, sy, sw, sh, _ = boxes[source]
        tx, ty, tw, th, _ = boxes[target]
        start, end = (sx + sw, sy + sh // 2), (tx + tw, ty + th // 2)
        lane = max(start[0], end[0]) + 30 + sum(map(ord, source + target)) % 110
        points = [start, (lane, start[1]), (lane, end[1]), end]
        for a, b in zip(points, points[1:]):
            length = math.dist(a, b)
            if kind == 'inherits':
                draw.line((a, b), fill='#777777', width=2)
            elif length:
                for offset in range(0, math.ceil(length), 12):
                    start_point = tuple(a[i] + (b[i] - a[i]) * offset / length for i in (0, 1))
                    end_point = tuple(a[i] + (b[i] - a[i]) * min(offset + 7, length) / length for i in (0, 1))
                    draw.line((start_point, end_point), fill='#777777', width=2)
        draw.polygon([end, (end[0] + 12, end[1] - 6), (end[0] + 12, end[1] + 6)], fill='white' if kind in ('inherits', 'implements') else '#777777', outline='#777777')
        draw.text((lane + 3, (start[1] + end[1]) // 2), kind, fill='#555555', font=font)
    for key, (left, top, width, height, sections) in boxes.items():
        draw.rectangle((left, top, left + width, top + height), fill='#f0f0f0', outline='#777777', width=1)
        y = top
        for index, section in enumerate(sections):
            if index:
                draw.line((left, y, left + width, y), fill='#777777')
            y += 9
            for line in section:
                draw.text((left + 12, y), line, fill='#111111', font=title_font if index == 0 else font)
                y += 23
            y += 9
        if key == groups[classes[key]['subsystem']][0][0]:
            draw.text((left, 75), classes[key]['subsystem'], fill='black', font=title_font)
    image.save(path)


def generate():
    classes, relationships = discover_classes()
    OUTPUT_DIR.mkdir(exist_ok=True)
    for name in ('bitefinder', *SUBSYSTEMS):
        selected = classes if name == 'bitefinder' else {k: v for k, v in classes.items() if v['subsystem'] == name}
        edges = [e for e in relationships if e[0] in selected and e[1] in selected]
        plant, dot = render_diagrams(selected, edges)
        (OUTPUT_DIR / f'{name}.puml').write_text(plant, encoding='utf-8')
        (OUTPUT_DIR / f'{name}.dot').write_text(dot, encoding='utf-8')
        render_png(selected, edges, OUTPUT_DIR / f'{name}.png')
    (OUTPUT_DIR / 'relationships.json').write_text(json.dumps(relationships, indent=2), encoding='utf-8')
    return classes, relationships


class UMLGeneratorTests(unittest.TestCase):
    def test_duplicate_names_and_class_scoped_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in SUBSYSTEMS:
                (root / name).mkdir()
                (root / name / 'manager.py').write_text('class Manager: pass\n')
            (root / 'BIS' / 'workflow.py').write_text(
                'from BRNS.manager import Manager as Target\n'
                'class Caller:\n'
                '    def run(self): return Target()\n'
                'class Unrelated: pass\n')
            _, relationships = discover_classes(root)
            creates = {(s, t) for s, t, k, _ in relationships if k == 'creates'}
            self.assertEqual(creates, {('BIS.workflow.Caller', 'BRNS.manager.Manager')})

    def test_generate_complete_diagrams(self):
        classes, relationships = generate()
        self.assertEqual(set(SUBSYSTEMS), {r['subsystem'] for r in classes.values()})
        self.assertTrue(relationships)
        for source, target, _, _ in relationships:
            self.assertIn(source, classes)
            self.assertIn(target, classes)


if __name__ == '__main__':
    unittest.main()
