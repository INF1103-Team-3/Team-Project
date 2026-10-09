r"""Draw source call graphs, or trace a real BIS session with --trace.

Run from the repository root with ``.venv/bin/python visualise_functions.py``
on Linux/macOS. On Windows, use
``.\.venv\Scripts\python.exe visualise_functions.py``.
PNGs are written to ``function_graphs/``. The default graphs are static: they
include functions even when the chatbot or live APIs are not run. Calls through
runtime values, callbacks, and dynamic imports cannot always be resolved.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict, deque
from dataclasses import dataclass
import os
from pathlib import Path
import runpy
import sys
from typing import Optional, Union


ROOT = Path(__file__).resolve().parent

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError as error:
    if error.name != "PIL":
        raise
    raise SystemExit(
        "Pillow is missing from this Python interpreter: " + sys.executable
        + "\nFrom the BiteFinder folder, install dependencies with the "
        "Python command used to start the script:\n"
        "  python -m pip install -r requirements-dev.txt\n"
        "Then run visualise_functions.py again."
    ) from error

SOURCE_DIRS = ("BIS", "BRNS", "BRC", "shared")
OUTPUT_DIR = ROOT / "function_graphs"
ENTRY = "BIS.main.main"
NODE_WIDTH = 290
NODE_HEIGHT = 48
ROW_GAP = 18
COL_GAP = 110
MARGIN = 55
TOP = 100
COLORS = {
    "BIS": "#dceeff",
    "BRNS": "#dbf5e6",
    "BRC": "#fff0d7",
    "shared": "#eee5ff",
}


@dataclass
class Function:
    module: str
    qualname: str
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    owner: Optional[str] = None


def module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def import_target(current: str, name: str, level: int) -> str:
    if not level:
        return name
    package = current.split(".")[:-1]
    prefix = package[: len(package) - level + 1]
    return ".".join(prefix + ([name] if name else []))


def collect_definitions():
    trees = {}
    functions = {}
    imports = {}
    for directory in SOURCE_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            module = module_name(path)
            tree = ast.parse(
                path.read_text(encoding="utf-8"), filename=str(path)
            )
            trees[module] = tree
            aliases = {}
            for statement in tree.body:
                if isinstance(statement, ast.Import):
                    for item in statement.names:
                        key = item.asname or item.name.split(".")[0]
                        aliases[key] = item.name
                elif isinstance(statement, ast.ImportFrom):
                    base = import_target(
                        module, statement.module or "", statement.level
                    )
                    for item in statement.names:
                        if item.name != "*":
                            key = item.asname or item.name
                            aliases[key] = base + "." + item.name
            imports[module] = aliases

            def visit(body, prefix="", owner=None):
                for statement in body:
                    if isinstance(statement, (ast.FunctionDef,
                                              ast.AsyncFunctionDef)):
                        qualname = prefix + statement.name
                        key = module + "." + qualname
                        functions[key] = Function(
                            module, qualname, statement, owner
                        )
                        visit(statement.body, qualname + ".", owner)
                    elif isinstance(statement, ast.ClassDef):
                        visit(statement.body, prefix + statement.name + ".",
                              statement.name)

            visit(tree.body)
    return functions, imports, set(trees)


def dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return base + "." + node.attr if base else None
    return None


class Calls(ast.NodeVisitor):
    def __init__(self):
        self.names = set()

    def visit_Call(self, node):
        name = dotted_name(node.func)
        if name:
            self.names.add(name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        return  # A nested function's body belongs to its own graph node.

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        return


def resolve_call(name, source, functions, imports, modules):
    info = functions[source]
    module = info.module
    parts = name.split(".")
    if parts[0] in {"self", "cls"} and info.owner:
        candidate = module + "." + info.owner + "." + ".".join(parts[1:])
        return candidate if candidate in functions else None
    alias = imports[module].get(parts[0])
    if alias:
        suffix = "." + ".".join(parts[1:]) if len(parts) > 1 else ""
        candidate = alias + suffix
        if candidate in functions:
            return candidate
        # ``import io_manager`` inside BIS/BRNS refers to that local module.
        package = module.split(".")[0]
        local = package + "." + candidate
        if local in functions:
            return local
    candidate = module + "." + name
    if candidate in functions:
        return candidate
    if info.owner and len(parts) == 1:
        candidate = module + "." + info.owner + "." + name
        if candidate in functions:
            return candidate
    if len(parts) > 1 and parts[0] in modules:
        candidate = name
        if candidate in functions:
            return candidate
    return None


def build_graph():
    functions, imports, modules = collect_definitions()
    edges = set()
    for source, info in functions.items():
        calls = Calls()
        for statement in info.node.body:
            calls.visit(statement)
        for name in calls.names:
            target = resolve_call(name, source, functions, imports, modules)
            if target:
                edges.add((source, target))
    return functions, edges


def reachable(start, edges):
    outgoing = defaultdict(set)
    for source, target in edges:
        outgoing[source].add(target)
    seen = {start}
    queue = deque([start])
    depth = {start: 0}
    while queue:
        source = queue.popleft()
        for target in sorted(outgoing[source]):
            if target not in seen:
                seen.add(target)
                depth[target] = depth[source] + 1
                queue.append(target)
    return seen, depth


def bis_to_brns_nodes(edges):
    seen, depth = reachable(ENTRY, edges)
    brns = {node for node in seen if node.startswith("BRNS.")}
    if not brns:
        raise RuntimeError("No BIS.main.main → BRNS call path was resolved.")
    incoming = defaultdict(set)
    for source, target in edges:
        incoming[target].add(source)
    nodes = set(brns)
    queue = deque(brns)
    while queue:
        for parent in incoming[queue.popleft()]:
            if parent in seen and parent not in nodes:
                nodes.add(parent)
                queue.append(parent)
    return nodes, depth


def font(size, bold=False):
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf"] if bold
             else ["DejaVuSans.ttf", "arial.ttf"])
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in names:
        for candidate in (name, str(windows_fonts / name)):
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def label_for(node):
    if node == "__main__":
        return "BIS session entry"
    if "." not in node:
        return node
    package, rest = node.split(".", 1)
    return package + ": " + rest


def draw_graph(path, title, nodes, edges, groups):
    if not nodes:
        raise ValueError("Cannot draw an empty call graph")
    if all(str(name).startswith("Step ") for name in groups):
        columns = sorted(groups, key=lambda name: int(str(name).split()[1]))
    else:
        columns = sorted(groups)
    ordered = {column: sorted(groups[column]) for column in columns}
    max_rows = max(len(items) for items in ordered.values())
    width = (2 * MARGIN + 80 + len(columns) * NODE_WIDTH
             + (len(columns) - 1) * COL_GAP)
    height = TOP + max_rows * (NODE_HEIGHT + ROW_GAP) + MARGIN
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    title_font = font(23, True)
    heading_font = font(16, True)
    text_font = font(12)
    draw.text((MARGIN, 24), title, font=title_font, fill="#15283a")
    caption = f"{len(nodes)} functions  •  {len(edges)} resolved calls"
    draw.text((MARGIN, 58), caption, font=text_font, fill="#536477")
    positions = {}
    for col, name in enumerate(columns):
        x = MARGIN + col * (NODE_WIDTH + COL_GAP)
        draw.text((x, TOP - 26), str(name), font=heading_font, fill="#24384c")
        for row, node in enumerate(ordered[name]):
            y = TOP + row * (NODE_HEIGHT + ROW_GAP)
            positions[node] = (x, y)

    # Draw the arrows underneath the cards so labels remain readable.
    for source, target in sorted(edges):
        if source not in positions or target not in positions:
            continue
        sx, sy = positions[source]
        tx, ty = positions[target]
        cross_package = source.split(".")[0] != target.split(".")[0]
        color = "#cc624d" if cross_package else "#b9c8d5"
        if tx > sx:
            start = (sx + NODE_WIDTH, sy + NODE_HEIGHT // 2)
            end = (tx, ty + NODE_HEIGHT // 2)
        elif tx < sx:
            start = (sx, sy + NODE_HEIGHT // 2)
            end = (tx + NODE_WIDTH, ty + NODE_HEIGHT // 2)
        else:
            lane = sx + NODE_WIDTH + 18 + (sum(map(ord, source)) % 5) * 8
            start = (sx + NODE_WIDTH, sy + NODE_HEIGHT // 2)
            end = (tx + NODE_WIDTH, ty + NODE_HEIGHT // 2)
            draw.line((start, (lane, start[1]), (lane, end[1]), end),
                      fill=color, width=2 if cross_package else 1)
            continue
        draw.line((start, end), fill=color, width=2 if cross_package else 1)
        direction = 1 if tx > sx else -1
        draw.polygon((end, (end[0] - direction * 8, end[1] - 4),
                      (end[0] - direction * 8, end[1] + 4)), fill=color)

    for node, (x, y) in positions.items():
        package = node.split(".")[0]
        fill = COLORS.get(package, "#e9edf2")
        draw.rounded_rectangle((x, y, x + NODE_WIDTH, y + NODE_HEIGHT),
                               radius=8, fill=fill, outline="#7b8da0", width=1)
        label = label_for(node)
        if len(label) > 39:
            label = label[:36] + "..."
        draw.text((x + 10, y + 15), label, font=text_font, fill="#1a2b3c")
    image.save(path, "PNG")
    print(f"Created {path.relative_to(ROOT)} ({len(nodes)} functions)")


def grouped_by_package(nodes):
    groups = defaultdict(list)
    for node in nodes:
        groups[node.split(".")[0]].append(node)
    return groups


def grouped_by_depth(nodes, depth):
    groups = defaultdict(list)
    for node in nodes:
        groups[f"Step {depth[node]}"].append(node)
    return groups


def draw_arrow(draw, points, color, width=5):
    draw.line(points, fill=color, width=width, joint="curve")
    end = points[-1]
    before = points[-2]
    if end[0] == before[0]:
        direction = 1 if end[1] > before[1] else -1
        head = ((end[0], end[1]),
                (end[0] - 10, end[1] - direction * 15),
                (end[0] + 10, end[1] - direction * 15))
    else:
        direction = 1 if end[0] > before[0] else -1
        head = ((end[0], end[1]),
                (end[0] - direction * 15, end[1] - 10),
                (end[0] - direction * 15, end[1] + 10))
    draw.polygon(head, fill=color)


def draw_manager_card(draw, box, title, module, choices, reached, outgoing):
    x0, y0, x1, y1 = box
    active = any(node.startswith(module + ".") for node in reached)
    package = module.split(".")[0]
    fill = COLORS[package] if active else "#f1f3f5"
    border = "#6688a4" if active else "#a7afb8"
    title_color = "#17334e" if active else "#687582"
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=border, width=3)
    draw.text((x0 + 23, y0 + 18), title, font=font(26, True),
              fill=title_color)
    count = sum(node.startswith(module + ".") for node in reached)
    status = (f"{count} reachable functions" if active
              else "Not called in this flow")
    draw.text((x0 + 23, y0 + 56), status, font=font(16),
              fill="#53677c" if active else "#7d8791")
    shown = [name for name in choices if module + "." + name in reached]
    if not active:
        shown = choices[:3]
    for index, name in enumerate(shown[:5]):
        y = y0 + 98 + index * 39
        draw.rounded_rectangle((x0 + 22, y, x1 - 22, y + 32), radius=7,
                               fill="#ffffff" if active else "#e5e8eb")
        draw.text((x0 + 35, y + 5), name + "()", font=font(17),
                  fill="#23384e" if active else "#78838d")
    if outgoing and active:
        draw.text((x0 + 23, y1 - 36), outgoing, font=font(15),
                  fill="#52677b")


def draw_main_card(draw, box, title, functions, subtitle, package):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=20, fill=COLORS[package],
                           outline="#3d617e", width=4)
    draw.text((x0 + 28, y0 + 20), title, font=font(28, True),
              fill="#17334e")
    draw.text((x0 + 28, y0 + 62), subtitle, font=font(17),
              fill="#52677b")
    for index, name in enumerate(functions):
        column = index % 3
        row = index // 3
        x = x0 + 28 + column * 292
        y = y0 + 104 + row * 53
        draw.rounded_rectangle((x, y, x + 266, y + 41), radius=8,
                               fill="#ffffff", outline="#a5b8c9", width=1)
        draw.text((x + 13, y + 9), name + "()", font=font(17),
                  fill="#243a4d")


def draw_flow_overview(path, reached, edges):
    """Draw a grouped, readable view of the BIS to BRNS handoff."""
    image = Image.new("RGB", (2350, 1860), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.text((80, 32), "BiteFinder | BIS to BRNS function flow",
              font=font(38, True), fill="#132e43")
    draw.text((80, 85), "Reachable functions and ordered manager stages",
              font=font(19), fill="#52677b")
    draw.rounded_rectangle((90, 130, 2220, 930), radius=23,
                           fill="#fafdff", outline="#c9d9e7", width=3)
    draw.rounded_rectangle((90, 1050, 2220, 1830), radius=23,
                           fill="#fbfefc", outline="#c9e3d4", width=3)
    draw.text((120, 145), "BIS · chatbot and profile", font=font(25, True),
              fill="#225a87")
    draw.text((120, 1065), "BRNS · restaurant search", font=font(25, True),
              fill="#24704c")

    bis_main = (725, 195, 1625, 445)
    brns_main = (725, 1110, 1625, 1355)
    bis_cards = [(125 + i * 530, 590, 605 + i * 530, 900)
                 for i in range(4)]
    brns_cards = [(125 + i * 530, 1500, 605 + i * 530, 1810)
                  for i in range(4)]
    blue = "#3180b9"
    green = "#3d976c"
    red = "#c55548"

    if any(a.startswith("BIS.main.") and b.startswith("BIS.io_manager.")
           for a, b in edges):
        draw_arrow(draw, [(790, 445), (790, 515),
                          (365, 515), (365, 590)], blue)
    bis_stages = ("io_manager", "ai_manager", "logic_manager",
                  "data_manager")
    if all(any(node.startswith("BIS." + module + ".")
               for node in reached) for module in bis_stages):
        for index in range(3):
            left, right = bis_cards[index], bis_cards[index + 1]
            draw_arrow(draw, [(left[2], 730), (right[0], 730)], blue)

    if any(a.startswith("BRNS.main.") and b.startswith("BRNS.io_manager.")
           for a, b in edges):
        draw_arrow(draw, [(790, 1355), (790, 1410),
                          (365, 1410), (365, 1500)], green)
    stage_modules = ("io_manager", "ai_manager", "logic_manager",
                     "data_manager")
    if all(any(node.startswith("BRNS." + module + ".")
               for node in reached) for module in stage_modules):
        for index in range(3):
            left, right = brns_cards[index], brns_cards[index + 1]
            draw_arrow(draw, [(left[2], 1640), (right[0], 1640)], green)

    if ("BIS.main.run_search", "BRNS.main.search") in edges:
        draw_arrow(draw, [(2195, 740), (2265, 740), (2265, 1220),
                          (1625, 1220)], red, width=7)
        draw.rounded_rectangle((1690, 953, 2240, 1025), radius=12,
                               fill="#fff4f1", outline=red, width=2)
        draw.text((1710, 966), "BIS Data JSON → BRNS IO",
                  font=font(21, True), fill="#9b3d34")
        draw.text((1710, 994), "via BRNS.main.search()",
                  font=font(17), fill="#9b3d34")

    if any(a.startswith("BIS.main.") and b.startswith("BRNS.io_manager.")
           for a, b in edges):
        draw_arrow(draw, [(125, 1655), (67, 1655), (67, 340), (725, 340)],
                   red, width=4)
        draw.rounded_rectangle((105, 960, 545, 1030), radius=12,
                               fill="#fff4f1", outline=red, width=2)
        draw.text((125, 972), "BRNS results → BIS display",
                  font=font(20, True), fill="#9b3d34")
        draw.text((125, 1000), "and optional route", font=font(17),
                  fill="#9b3d34")

    bis_main_names = [name for name in ("main", "run_accounts",
                                        "run_session", "handle_action",
                                        "run_search")
                      if "BIS.main." + name in reached]
    brns_main_names = [name for name in ("search", "route_to")
                       if "BRNS.main." + name in reached]
    draw_main_card(draw, bis_main, "BIS.main", bis_main_names,
                   "Collect → AI intent → validate → confirm → JSON", "BIS")
    draw_main_card(draw, brns_main, "BRNS.main", brns_main_names,
                   "IO facts → AI reasons → Logic checks → Data stores", "BRNS")

    bis_details = (
        ("1 · IO", "io_manager", ("collect_search", "ask_search_intent",
                                  "confirm_search_request",
                                  "display_search_summary"),
         "Collects and confirms today's search"),
        ("2 · AI", "ai_manager", ("interpret_search_request", "process",
                                  "interpret_location", "_call_openrouter"),
         "Interprets today's free-text wish"),
        ("3 · Logic", "logic_manager", ("validate_search_request",
                                        "apply_updates", "next_field",
                                        "parse_local_answer"),
         "Protects confirmed choices"),
        ("4 · Data", "data_manager", ("serialize_search_request",
                                      "save_preferences", "resolve_location",
                                      "get_state"),
         "Serializes search JSON"),
    )
    brns_details = (
        ("1 · IO", "io_manager", ("accept_bis_json", "find_candidates",
                                  "show_results", "show_route"),
         "Places and routes via IO client"),
        ("2 · AI", "ai_manager", ("recommend_candidates",
                                  "_call_openrouter", "_call_gemini",
                                  "parse_json_reply"),
         "Orders IDs with reason codes"),
        ("3 · Logic", "logic_manager", ("rank_restaurants",
                                        "decide_outcome",
                                        "normalize_candidate"),
         "Verifies AI reasons and requirements"),
        ("4 · Data", "data_manager", ("save_search_results",
                                      "save_history", "load_history",
                                      "_save_json"),
         "Stores validated search summary"),
    )
    for box, (title, suffix, names, note) in zip(bis_cards, bis_details):
        draw_manager_card(draw, box, "BIS " + title, "BIS." + suffix,
                          names, reached, note)
    for box, (title, suffix, names, note) in zip(brns_cards, brns_details):
        draw_manager_card(draw, box, "BRNS " + title, "BRNS." + suffix,
                          names, reached, note)

    image.save(path, "PNG")
    print(f"Created {path.relative_to(ROOT)} (grouped BIS → BRNS flow)")


def create_static_graphs():
    functions, edges = build_graph()
    OUTPUT_DIR.mkdir(exist_ok=True)
    all_nodes = set(functions)
    draw_graph(OUTPUT_DIR / "all_functions.png",
               "BiteFinder function calls (source)", all_nodes, edges,
               grouped_by_package(all_nodes))
    flow_nodes, depth = bis_to_brns_nodes(edges)
    flow_edges = {(source, target) for source, target in edges
                  if source in flow_nodes and target in flow_nodes}
    reached, _ = reachable(ENTRY, edges)
    draw_flow_overview(OUTPUT_DIR / "bis_to_brns.png", reached, edges)
    draw_graph(OUTPUT_DIR / "bis_to_brns_functions.png",
               "BIS main() → BRNS functions (source)", flow_nodes,
               flow_edges, grouped_by_depth(flow_nodes, depth))


def create_live_trace():
    """Run BIS and draw the calls observed in this session."""
    try:
        from pycallgraph import Config, PyCallGraph
        from pycallgraph.output import Output
    except ImportError as error:
        raise RuntimeError(
            "Install requirements-dev.txt to use --trace"
        ) from error

    class Capture(Output):
        def done(self):
            self.calls = {
                (source, target)
                for source, targets in self.processor.call_dict.items()
                for target in targets
            }

    capture = Capture()
    known, _ = build_graph()
    names = {node.split(".")[-1] for node in known}
    config = Config(trace_filter=lambda name: (
        name.startswith(("BRNS.", "BRC.", "shared.", "sources.", "support."))
        or name.split(".")[-1] in names
    ))
    sys.path.insert(0, str(ROOT / "BIS"))
    sys.path.insert(1, str(ROOT))
    print("Running BIS/main.py. Complete a real session to capture its calls.")
    try:
        with PyCallGraph(output=capture, config=config):
            runpy.run_path(str(ROOT / "BIS" / "main.py"), run_name="__main__")
    finally:
        sys.path.remove(str(ROOT / "BIS"))
        sys.path.remove(str(ROOT))

    def normalize(name):
        if name == "__main__":
            return "BIS.main.session_entry"
        if name in known:
            return name
        for candidate in ("BIS." + name, "BIS.main." + name):
            if candidate in known:
                return candidate
        return name

    edges = {(normalize(source), normalize(target))
             for source, target in capture.calls}
    nodes = {node for edge in edges for node in edge}
    if nodes:
        OUTPUT_DIR.mkdir(exist_ok=True)
        draw_graph(OUTPUT_DIR / "bis_live_trace.png",
                   "Observed BIS session calls", nodes, edges,
                   grouped_by_package(nodes))
    else:
        print("No calls were captured in this session.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", action="store_true",
                        help="also run BIS/main.py and graph its calls")
    args = parser.parse_args()
    create_static_graphs()
    if args.trace:
        create_live_trace()


if __name__ == "__main__":
    main()
