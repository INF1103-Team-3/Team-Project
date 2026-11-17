"""Analyze BiteFinder source, verify inference, and generate UML PNG/SVG files.

Run: python project_overview/test_uml.py
Uses Pillow; optionally uses Graphviz `dot` for automatic layout.
No application imports, execution, external APIs, or credentials are needed.
Outputs are local artifacts under the external BiteFinder workfiles directory.
"""

from pathlib import Path
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from uml_analysis import SourceAnalysis, SUBSYSTEMS  # noqa: E402
from uml_rendering import graph_layout, render, route_edges  # noqa: E402
from uml_rendering import sources  # noqa: E402
from uml_document_rendering import Sheet  # noqa: E402
from document_uml import OUTPUT, WORKFILES, generate_document_set  # noqa: E402
from document_uml import (  # noqa: E402
    expanded_types,
    inventory,
    reviewed_relations,
    summary_member,
)
from document_uml import organize_artifacts, png_relative_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = OUTPUT


def discover_classes(root=ROOT):
    analysis = SourceAnalysis(root).analyze()
    return analysis.classes, sorted(analysis.edges)


def generate(root=ROOT, output=OUTPUT_DIR):
    analysis = SourceAnalysis(root).analyze()
    if not analysis.converged:
        raise RuntimeError(
            (
                "Type inference did not converge; inspect source before "
                "diagramming."
            )
        )
    output.mkdir(parents=True, exist_ok=True)
    (output / "analysis.json").write_text(
        json.dumps(analysis.report(), indent=2), encoding="utf-8"
    )
    generate_document_set(analysis, output)
    # Preserve the old full diagnostic view as an explicit opt-in. The default
    # report is split into readable, indexed sheets rather than giant images.
    for name in (
        ("bitefinder", *SUBSYSTEMS)
        if os.getenv("BITEFINDER_UML_FULL") == "1"
        else ()
    ):
        classes = {
            key: record
            for key, record in analysis.classes.items()
            if name == "bitefinder" or record["subsystem"] == name
        }
        edges = [
            e
            for e in sorted(analysis.edges)
            if e[0] in classes and e[1] in classes
        ]
        render(classes, edges, output / (name + ".png"))
    if os.getenv("BITEFINDER_UML_FULL") == "1":
        render(
            analysis.classes,
            sorted(analysis.edges),
            output / "bitefinder_flow.png",
            compact=True,
        )
    organize_artifacts(output, replace=True)
    return analysis


class UMLGeneratorTests(unittest.TestCase):
    def test_standalone_types_preserve_real_qualified_classes(self):
        aliases = {"RecommendationContext": "dict[str, Any]"}
        self.assertEqual(
            expanded_types("# context: BRNS.RecommendationContext", aliases),
            "# context: BRNS.RecommendationContext",
        )
        self.assertEqual(
            expanded_types("+ prepare(): RecommendationContext", aliases),
            "+ prepare(): dict[str, Any]",
        )
        self.assertEqual(
            summary_member(
                {
                    "text": (
                        "+ search(request: dict): "
                        "dict[str, str] | dict[str, int]"
                    )
                },
                True,
            ),
            "+ search(...): dict",
        )

    def test_reconstructed_chat_and_ranking_contracts(self):
        analysis = SourceAnalysis(ROOT).analyze()
        records = inventory(analysis)
        chat = records[
            "BIS.classes.ai.contracts.chat_ai_interface.ChatAIInterface"
        ]
        methods = {entry["name"]: entry["text"] for entry in chat["methods"]}
        self.assertIn(
            "wishes: list[str], config: AppConfig",
            methods["review_profile_wishes"],
        )
        self.assertIn("history: ChatHistory", methods["chat_turn"])
        self.assertIn("): ChatDecision", methods["chat_turn"])
        slot = chat["module"] + ".ChatAIInterface.chat_turn.return"
        proof = analysis.uml_types.get(slot)
        self.assertTrue(
            any("bis_interpreter.py" in e for e in proof["evidence"])
        )
        ranking = records["BRNS.classes.ai.ai_manager.AIManager"]
        public = next(
            m for m in ranking["methods"] if m["name"] == "recommend_prepared"
        )
        self.assertIn("Recommendations | None", public["text"])
        self.assertEqual(
            analysis.uml_types.aliases["AppConfig"], "dict[str, Any]"
        )
        self.assertFalse(
            any(r["name"] == "AppConfig" for r in records.values())
        )

    def test_types_follow_calls_returns_and_paired_assignments(self):
        analysis = self.fixture(
            {
                "BIS/example.py": (
                    "class Left: pass\n"
                    "class Right: pass\n"
                    "class Owner:\n"
                    "    count: int = 2\n"
                    "    def __init__(self, left, right):\n"
                    "        self._left, self._right = left, right\n"
                    "    def choose(self, flag):\n"
                    "        if flag: return 'yes'\n"
                    "    def unknown(self, value): return value\n"
                    "owner = Owner(Left(), Right())\n"
                    "owner.choose(True)\n"
                )
            }
        )
        record = inventory(analysis)["BIS.example.Owner"]
        attrs = {a["name"]: a["typing"]["type"] for a in record["attributes"]}
        self.assertEqual(attrs["_left"], "BIS.Left")
        self.assertEqual(attrs["_right"], "BIS.Right")
        self.assertEqual(attrs["count"], "int")
        declared = analysis.uml_types.get("BIS.example.Owner.count")
        self.assertEqual(declared["status"], "declared")
        self.assertEqual(
            analysis.uml_types.union({"str | None", "str"}), "str | None"
        )
        dtype = analysis.uml_types.get("BIS.example.Owner.choose.return")
        self.assertEqual(set(dtype["type"].split(" | ")), {"str", "None"})
        unknown = analysis.uml_types.get("BIS.example.Owner.unknown.value")
        self.assertEqual(unknown["type"], "DynamicValue")
        self.assertEqual(unknown["status"], "unresolved")

    def test_reflexive_association_requires_a_stored_instance(self):
        analysis = self.fixture(
            {
                "BIS/example.py": (
                    "class Node:\n"
                    "    def __init__(self, parent: 'Node | None' = None):\n"
                    "        self.parent = parent\n"
                    "    def recurse(self): return self.recurse()\n"
                    "class Recursive:\n"
                    "    def recurse(self): return self.recurse()\n"
                )
            }
        )
        loops = [r for r in reviewed_relations(analysis) if r.get("reflexive")]
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0]["from"], "BIS.example.Node")
        self.assertTrue(loops[0]["directed"])
        self.assertIn("example.py:3", loops[0]["evidence"][0])

    def fixture(self, files):
        directory = WORKFILES / "tests"
        directory.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, source in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return SourceAnalysis(root).analyze()

    def test_full_members_include_properties_tuple_fields_and_protocols(self):
        analysis = self.fixture(
            {
                "BIS/model.py": (
                    "class Example:\n"
                    "    FLAG = True\n"
                    "    def __init__(self, left, right, /, "
                    "*, count: int = 2):\n"
                    "        self._left, self.__right = left, right\n"
                    "    @property\n"
                    "    def value(self) -> int: return 1\n"
                    "    @staticmethod\n"
                    "    def __helper(*items, **options): pass\n"
                )
            }
        )
        record = inventory(analysis)["BIS.model.Example"]
        attributes = {
            item["name"]: item["text"] for item in record["attributes"]
        }
        self.assertEqual(
            set(attributes), {"FLAG", "_left", "__right", "value"}
        )
        self.assertTrue(attributes["__right"].startswith("- right:"))
        self.assertIn("readOnly", attributes["value"])
        methods = {item["name"]: item["text"] for item in record["methods"]}
        self.assertIn("+ __init__", methods["__init__"])
        self.assertIn("/, *, count: int = 2", methods["__init__"])
        self.assertIn("- helper", methods["__helper"])
        self.assertIn("{static}", methods["__helper"])
        self.assertNotIn("value", methods)

    def test_injected_defaults_are_not_unproven_composition(self):
        analysis = self.fixture(
            {
                "BIS/example.py": (
                    "class Helper: pass\n"
                    "class Owner:\n"
                    "    def __init__(self, helper=None):\n"
                    "        self.helper = helper or Helper()\n"
                )
            }
        )
        relations = reviewed_relations(analysis)
        stored = [
            r
            for r in relations
            if r["from"] == "BIS.example.Owner"
            and r["to"] == "BIS.example.Helper"
            and r["kind"] != "dependency"
        ]
        self.assertEqual([r["kind"] for r in stored], ["association"])
        self.assertNotIn("from_multiplicity", stored[0])

    def test_routing_uses_free_side_ports_when_vertical_gap_is_tight(self):
        boxes = {
            "parent": (75, 225, 1450, 292, []),
            "child": (75, 597, 1450, 864, []),
        }
        routes = route_edges(
            boxes, [("child", "parent", "inherits", "")], 3200, 1980
        )
        points = routes[0][0]
        self.assertEqual(points[0][0], 75)
        self.assertEqual(points[-1][0], 75)
        for first, last in zip(points, points[1:]):
            middle = ((first[0] + last[0]) / 2, (first[1] + last[1]) / 2)
            for x, y, width, height, _ in boxes.values():
                self.assertFalse(
                    x < middle[0] < x + width and y < middle[1] < y + height
                )

    def test_triangle_and_diamonds_are_real_hollow_and_filled_shapes(self):
        import xml.etree.ElementTree as ET

        directory = WORKFILES / "tests"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            sheet = Sheet("Notation test", "Geometric markers")
            sheet.line([(100, 300), (800, 300)])
            sheet.marker((200, 300), (100, 300), "triangle")
            sheet.marker((400, 300), (500, 300), "hollow")
            sheet.marker((600, 300), (700, 300), "filled")
            self.assertEqual(sheet.image.getpixel((180, 300)), (255, 255, 255))
            self.assertEqual(sheet.image.getpixel((440, 300)), (255, 255, 255))
            self.assertEqual(sheet.image.getpixel((640, 300)), (0, 0, 0))
            path = Path(temporary) / "markers"
            sheet.save(path)
            root = ET.parse(path.with_suffix(".svg")).getroot()
            polygons = root.findall("{http://www.w3.org/2000/svg}polygon")
            self.assertEqual(
                [len(p.attrib["points"].split()) for p in polygons], [3, 4, 4]
            )
            self.assertEqual(
                [p.attrib["fill"] for p in polygons],
                ["white", "white", "black"],
            )
            self.assertEqual(
                polygons[0].attrib["points"].split()[0], "200,300"
            )

    def test_legacy_association_export_has_no_arrowhead(self):
        analysis = self.fixture(
            {"BIS/example.py": "class First: pass\nclass Second: pass\n"}
        )
        plant, dot = sources(
            analysis.classes,
            [
                (
                    "BIS.example.First",
                    "BIS.example.Second",
                    "association",
                    "ref",
                    "example:1",
                )
            ],
        )
        self.assertIn(" .. ", plant)
        self.assertIn("arrowhead=none", dot)
        self.assertIn("style=dotted", dot)

    def test_association_is_dotted_without_an_endpoint_marker(self):
        sheet = Sheet("Association convention", "Dotted, no arrowhead")
        sheet.line([(100, 300), (400, 300)], dotted=True)
        self.assertNotEqual(sheet.image.getpixel((100, 300)), (255, 255, 255))
        self.assertEqual(sheet.image.getpixel((106, 300)), (255, 255, 255))
        self.assertIn('stroke-dasharray="1 11"', sheet.svg[-1])
        self.assertNotIn("marker-end", sheet.svg[-1])

    def test_directed_association_uses_open_arrow_not_hollow_triangle(self):
        sheet = Sheet("Directed association", "Navigability, not inheritance")
        for key, x in (("owner", 100), ("part", 1800)):
            sheet.box(
                key, [key], [["field: str"], ["run(): None"]], (x, 300, 800)
            )
        sheet.relation(
            {
                "from": "owner",
                "to": "part",
                "kind": "association",
                "directed": True,
            },
            1,
        )
        sheet.draw_relations()
        self.assertFalse(any("<polygon" in item for item in sheet.svg))
        self.assertTrue(
            any('stroke-dasharray="1 11"' in item for item in sheet.svg)
        )

    def test_duplicate_names_and_scoped_calls(self):
        analysis = self.fixture(
            {
                "BIS/manager.py": "class Manager: pass\n",
                "BRNS/manager.py": "class Manager: pass\n",
                ("BIS/workflow.py"): (
                    "from BRNS.manager import Manager as Target\nclass "
                    "Caller:\n    def run(self): return Target()\nclass "
                    "Unrelated: pass\n"
                ),
            }
        )
        creates = {(s, t) for s, t, k, *_ in analysis.edges if k == "creates"}
        self.assertEqual(
            creates, {("BIS.workflow.Caller", "BRNS.manager.Manager")}
        )

    def test_factories_injection_ownership_collections_and_calls(self):
        analysis = self.fixture(
            {
                "BIS/parts.py": "class Part:\n    def run(self): pass\n"
                "def manager():\n    return Part()\n",
                "BIS/app.py": "from .parts import Part, manager\n"
                "class Owner:\n"
                "    def __init__(self, part, parts):\n"
                "        self._part = part\n"
                "        self._parts = [p for p in parts]\n"
                "        self._owned = Part()\n"
                "    def run(self): self._part.run()\n"
                "application = Owner(manager(), [Part()])\n",
            }
        )
        kinds = {
            k
            for s, t, k, *_ in analysis.edges
            if s == "BIS.app.Owner" and t == "BIS.parts.Part"
        }
        self.assertTrue(
            {"association", "aggregation", "composition", "calls"} <= kinds
        )
        self.assertTrue(analysis.converged)
        self.assertEqual(
            analysis.classes["BIS.app.Owner"]["attributes"]["_part"], "Part"
        )

    def test_reexports_and_tuple_factory_positions(self):
        analysis = self.fixture(
            {
                "BIS/parts.py": "class First: pass\nclass Second: pass\n",
                "BIS/facade.py": "from BIS.parts import First as Public\n",
                ("BIS/app.py"): (
                    "from .facade import Public\nfrom .parts import "
                    "Second\ndef managers(): return Public(), Second()\nclass "
                    "App:\n    def __init__(self, a, b): self.a=a; "
                    "self.b=b\ndef create():\n    a,b=managers()\n    return "
                    "App(a,b)\napp=create()\n"
                ),
            }
        )
        links = {
            (t, label)
            for s, t, kind, label, _ in analysis.edges
            if s == "BIS.app.App" and kind == "association"
        }
        self.assertEqual(
            links, {("BIS.parts.First", "a"), ("BIS.parts.Second", "b")}
        )

    def test_package_relative_reexport(self):
        analysis = self.fixture(
            {
                "BIS/domain/__init__.py": "from .part import Part\n",
                "BIS/domain/part.py": "class Part: pass\n",
                "BIS/app.py": "from .domain import Part\n"
                "class App:\n    def run(self): return Part()\n",
            }
        )
        self.assertIn(
            ("BIS.app.App", "BIS.domain.part.Part", "creates"),
            {(s, t, k) for s, t, k, *_ in analysis.edges},
        )

    def test_unknown_dynamic_collaborators_are_not_invented(self):
        analysis = self.fixture(
            {
                "BIS/app.py": "class App:\n"
                "    def __init__(self, service): self._service=service\n"
                "    def run(self): self._service.send()\n",
            }
        )
        self.assertFalse(analysis.edges)
        self.assertTrue(analysis.unresolved)

    def test_lazy_global_imports_are_resolved_without_running_initializers(
        self,
    ):
        analysis = self.fixture(
            {
                "BIS/parts.py": "class Service: pass\n",
                "BIS/app.py": "service=None\n"
                "def initialize():\n"
                "    global service, Service\n"
                "    from .parts import Service\n"
                "    service=Service()\n"
                "def current():\n    initialize()\n    return service\n"
                "class App:\n    def __init__(self): self.service=current()\n",
            }
        )
        self.assertIn(
            ("BIS.app.App", "BIS.parts.Service", "association"),
            {(s, t, k) for s, t, k, *_ in analysis.edges},
        )

    def test_registered_lambda_factory_and_forwarding_facade(self):
        analysis = self.fixture(
            {
                "BIS/parts.py": "class Service:\n    def run(self): pass\n"
                "class Registry:\n"
                "    def register(self, factory): self.factory=factory\n"
                "    def create(self): return self.factory()\n",
                "BIS/facade.py": "from .parts import Registry, Service\n"
                "registry=Registry()\n"
                "registry.register(lambda: Service())\n"
                "service=registry.create()\n"
                "def run(): return service.run()\n",
                "BIS/app.py": "from . import facade\n"
                "class App:\n    def run(self): facade.run()\n",
            }
        )
        links = {(s, t, k) for s, t, k, *_ in analysis.edges}
        self.assertIn(("BIS.app.App", "BIS.parts.Service", "calls"), links)

    def test_annotations_and_default_ownership_are_distinguished(self):
        analysis = self.fixture(
            {
                "BIS/app.py": "class Helper: pass\n"
                "class App:\n"
                "    def __init__(self, supplied: Helper, optional=None):\n"
                "        self.supplied=supplied\n"
                "        self.owned=optional or Helper()\n",
            }
        )
        links = {(k, label) for _, _, k, label, _ in analysis.edges}
        self.assertIn(("association", "supplied"), links)
        self.assertIn(("composition", "owned (default)"), links)

    def test_http_edge_requires_matching_source_routes(self):
        analysis = self.fixture(
            {
                ("BRC/service.py"): (
                    "from http.server import BaseHTTPRequestHandler\nclass "
                    "Handler(BaseHTTPRequestHandler):\n    def "
                    'do_POST(self):\n        if self.path == "/check": '
                    "pass\nclass Client:\n    def __init__(self): "
                    'self.url="BRC_SERVICE_URL"\n    def verify(self): return '
                    'self._request("/check")\nclass Unrelated:\n    def '
                    '__init__(self): self.url="BRC_SERVICE_URL"\n    def '
                    'verify(self): return self._request("/unknown")\n'
                ),
            }
        )
        links = {(s, t) for s, t, k, *_ in analysis.edges if k == "http"}
        self.assertEqual(
            links, {("BRC.service.Client", "BRC.service.Handler")}
        )

    def test_layout_spreads_a_subsystem_across_rows_and_columns(self):
        source = "\n".join(f"class Class{i}: pass" for i in range(12))
        analysis = self.fixture({"BIS/models.py": source})
        boxes, _, _ = graph_layout(analysis.classes, [])
        # Disconnected classes should also be packed; see renderer's component
        # packing.
        self.assertGreater(len({b[0] for b in boxes.values()}), 1)
        self.assertGreater(len({b[1] for b in boxes.values()}), 1)

    def test_generate_current_repository(self):
        analysis = generate()
        model = json.loads(
            (OUTPUT_DIR / "json" / "class_model.json").read_text()
        )
        for suffix in ("png", "svg", "mmd", "json"):
            self.assertTrue((OUTPUT_DIR / suffix).is_dir())
            self.assertFalse(list(OUTPUT_DIR.glob("*." + suffix)))
            for prefix, category in (
                ("A_", "Appendix"), ("F_", "Functions"), ("M_", "Managers")
            ):
                self.assertTrue((OUTPUT_DIR / suffix / category).is_dir())
                self.assertFalse(list(
                    (OUTPUT_DIR / suffix).glob(prefix + "*." + suffix)
                ))
        for svg in (OUTPUT_DIR / "svg").rglob("*.svg"):
            rendered = svg.read_text()
            self.assertNotIn("INDEX.md", rendered, svg.name)
            self.assertNotIn("relations.json", rendered, svg.name)
            self.assertNotIn("module_dependencies.json", rendered, svg.name)
            self.assertNotIn("context reference", rendered, svg.name)
        overview = (OUTPUT_DIR / "svg" / "01_overview.svg").read_text()
        self.assertIn("search(...)", overview)
        self.assertIn("# brns:", overview)
        self.assertNotIn("dict | dict", overview)
        self.assertIn("omits parameters", overview)
        for record in model["classes"].values():
            for category in ("attributes", "methods"):
                for entry in record[category]:
                    self.assertIn("diagram_text", entry)
                    self.assertNotIn("AppConfig", entry["diagram_text"])
        self.assertEqual(set(model["classes"]), set(model["index"]))
        for key, record in model["classes"].items():
            expected = {
                (kind, entry["name"])
                for kind in ("attributes", "methods")
                for entry in record[kind]
            }
            actual = set()
            for page in model["pages"]:
                focus = page["focus"]
                if key == focus or isinstance(focus, list) and key in focus:
                    actual.update(
                        (entry["category"], entry["name"])
                        for entry in page["members"]
                        if entry.get("class", key) == key
                    )
                    self.assertTrue(
                        (OUTPUT_DIR / png_relative_path(page["id"])).is_file()
                    )
            self.assertEqual(expected, actual, key)
        for relation in model["relations"]:
            if relation["kind"] in (
                "generalisation",
                "realisation",
                "dependency",
            ):
                self.assertNotIn("from_multiplicity", relation)
                self.assertNotIn("to_multiplicity", relation)
        self.assertEqual(
            set(SUBSYSTEMS),
            {r["subsystem"] for r in analysis.classes.values()},
        )
        for source, target, _, _, evidence in analysis.edges:
            self.assertIn(source, analysis.classes)
            self.assertIn(target, analysis.classes)
            self.assertTrue(evidence)
        links = {(s, t, k) for s, t, k, *_ in analysis.edges}
        self.assertIn(
            (
                (
                    "BIS.classes.services.cli.bis_search_workflow.BISSearchWor"
                    "kflow"
                ),
                "BIS.classes.io.cli.io_manager.IOManager",
                "association",
            ),
            links,
        )
        self.assertIn(
            (
                (
                    "BRNS.classes.logic.sorting.result_sorter_registry.ResultS"
                    "orterRegistry"
                ),
                (
                    "BRNS.classes.logic.sorting.strategies.rating_result_sorte"
                    "r.RatingResultSorter"
                ),
                "aggregation",
            ),
            links,
        )
        print(
            (
                "\nGenerated "
                f"{len(analysis.classes)}"
                " classes and "
                f"{len(analysis.edges)}"
                " source-evidenced relationships in "
                f"{OUTPUT_DIR}"
                ".\n"
                f"{len(analysis.unresolved)}"
                " dynamic call sites remain unresolved; "
                "see json/analysis.json."
            )
        )


if __name__ == "__main__":
    unittest.main()
