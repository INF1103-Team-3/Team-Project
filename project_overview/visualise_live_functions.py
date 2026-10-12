r"""Trace one interactive BIS session and draw the calls it actually makes.

From the project root, run
``.venv/bin/python project_overview/visualise_live_functions.py``.
On Windows use
``.\.venv\Scripts\python.exe project_overview\visualise_live_functions.py``.
Use BiteFinder normally, then choose /quit to finish the trace. Each run saves
an overview, one detailed PNG per program used, and exact call counts in JSON
under ``project_overview/function_graphs/live_sessions/``. BRC is shown as
inactive unless the BIS session really calls it. This script does not launch
BRC separately.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import sys
from uuid import uuid4

from visualise_functions import draw_graph


OVERVIEW_DIR = Path(__file__).resolve().parent
ROOT = OVERVIEW_DIR.parent
ENTRY = "BIS.main.session_entry"
PROGRAMS = ("BIS", "BRNS", "BRC", "shared")
MANAGERS = ("io_manager", "ai_manager", "logic_manager", "data_manager")
OUTPUT_ROOT = OVERVIEW_DIR / "function_graphs" / "live_sessions"


class SessionTrace:
    """Count project function calls and their nearest project callers."""

    def __init__(self):
        self.calls = Counter({ENTRY: 1})
        self.edges = Counter()
        self.modules = {ENTRY: "BIS.main"}
        self.files = {ENTRY: "BIS/main.py"}
        self._code_cache = {}

    def identify(self, code):
        if code in self._code_cache:
            return self._code_cache[code]
        filename = code.co_filename
        if not filename.endswith(".py") or code.co_name.startswith("<"):
            self._code_cache[code] = None
            return None
        try:
            relative = Path(filename).resolve().relative_to(ROOT)
        except ValueError:
            self._code_cache[code] = None
            return None
        if len(relative.parts) < 2 or relative.parts[0] not in PROGRAMS:
            self._code_cache[code] = None
            return None
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join(parts)
        qualname = code.co_qualname.replace(".<locals>.", ".")
        name = f"{module}.{qualname}"
        self.modules[name] = module
        self.files[name] = relative.as_posix()
        self._code_cache[code] = name
        return name

    def record(self, frame, event, _argument):
        if event != "call":
            return
        called = self.identify(frame.f_code)
        if called is None:
            return
        self.calls[called] += 1
        parent = frame.f_back
        caller = None
        while parent is not None:
            caller = self.identify(parent.f_code)
            if caller is not None:
                break
            parent = parent.f_back
        self.edges[(caller or ENTRY, called)] += 1


def stage(module):
    """Group each manager under its owning program."""
    package, _, rest = module.partition(".")
    filename = rest.rsplit(".", 1)[-1]
    if filename in {"main", "restaurant_finder"}:
        return "Main"
    if filename in MANAGERS:
        return filename.removesuffix("_manager").upper()
    if package == "shared":
        return filename + ".py"
    return rest.replace(".", "/") + ".py"


def stage_order(name):
    order = {"Main": 0, "IO": 1, "AI": 2, "LOGIC": 3, "DATA": 4}
    return order.get(name, 5), name


def save_trace(trace, directory):
    data = {
        "entry": "BIS/main.py",
        "functions": [
            {"name": name, "file": trace.files[name], "calls": count}
            for name, count in sorted(trace.calls.items())
        ],
        "calls": [
            {"caller": source, "called": target, "count": count}
            for (source, target), count in sorted(trace.edges.items())
        ],
    }
    path = directory / "calls.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Created {path.relative_to(ROOT)}")


def draw_overview(trace, directory):
    """Show the observed links among each program's main and managers."""
    stage_nodes = {}
    groups = defaultdict(list)
    labels = {}
    for program in PROGRAMS:
        modules = {trace.modules[name] for name in trace.calls
                   if name.startswith(program + ".")}
        if not modules:
            node = f"{program}.not_called"
            groups[f"{PROGRAMS.index(program) + 1:02d} {program}"].append(node)
            labels[node] = f"{program}: not called in this session"
            continue
        for group_name in sorted({stage(module) for module in modules},
                                 key=stage_order):
            node = f"{program}.{group_name}"
            count = sum(stage(trace.modules[name]) == group_name
                        for name in trace.calls
                        if name.startswith(program + "."))
            labels[node] = f"{program} {group_name} · {count} functions"
            for module in modules:
                if stage(module) == group_name:
                    stage_nodes[module] = node
            groups[f"{PROGRAMS.index(program) + 1:02d} {program}"].append(node)
    edges = set()
    for source, target in trace.edges:
        first = stage_nodes[trace.modules[source]]
        second = stage_nodes[trace.modules[target]]
        if first != second:
            edges.add((first, second))
    nodes = {node for items in groups.values() for node in items}
    draw_graph(directory / "overview.png",
               "BiteFinder | observed program and manager calls",
               nodes, edges, groups, node_kind="program stages",
               sort_nodes=False, labels=labels, route_cross_package=True)


def draw_program_details(trace, directory, program):
    """Show actual functions in columns for main, managers, and other files."""
    nodes = {name for name in trace.calls
             if name.startswith(program + ".")}
    if not nodes:
        print(f"{program}: no functions called during this BIS session.")
        return
    modules = sorted({trace.modules[name] for name in nodes},
                     key=lambda module: (stage_order(stage(module)), module))
    module_files = {trace.modules[name]: trace.files[name] for name in nodes}
    observed_order = {name: index for index, name in enumerate(trace.calls)}
    groups = defaultdict(list)
    labels = {}
    for index, module in enumerate(modules, 1):
        label = f"{index:02d} {stage(module)} · {module_files[module]}"
        groups[label].extend(sorted(
            (name for name in nodes if trace.modules[name] == module),
            key=observed_order.__getitem__))
    for name in nodes:
        function = name.removeprefix(trace.modules[name] + ".")
        labels[name] = f"{function}() · {trace.calls[name]} calls"
    edges = {(source, target) for source, target in trace.edges
             if source in nodes and target in nodes and source != target}
    draw_graph(directory / f"{program.lower()}_functions.png",
               f"{program} | functions called in this BIS session",
               nodes, edges, groups, sort_nodes=False, labels=labels)


def run_session():
    trace = SessionTrace()
    bis_path = str(ROOT / "BIS")
    root_path = str(ROOT)
    sys.path.insert(0, bis_path)
    sys.path.insert(1, root_path)
    print("Tracing BIS/main.py. Use BiteFinder normally; quit to save graphs.",
          flush=True)
    try:
        sys.setprofile(trace.record)
        runpy.run_path(str(ROOT / "BIS" / "main.py"), run_name="__main__")
    except KeyboardInterrupt:
        print("\nBIS session interrupted; saving calls captured so far.")
    finally:
        sys.setprofile(None)
        sys.path.remove(bis_path)
        sys.path.remove(root_path)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        directory = OUTPUT_ROOT / f"{timestamp}_{uuid4().hex[:6]}"
        directory.mkdir(parents=True, exist_ok=True)
        save_trace(trace, directory)
        draw_overview(trace, directory)
        for program in PROGRAMS:
            draw_program_details(trace, directory, program)
        print(f"Session graphs: {directory.relative_to(ROOT)}")


if __name__ == "__main__":
    run_session()
