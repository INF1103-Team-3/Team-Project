"""Analyze BiteFinder source, verify inference, and generate UML PNG/SVG files.

Run: python project_overview/test_uml.py
Uses Pillow; optionally uses Graphviz `dot` for automatic layout.
No application imports, execution, external APIs, or credentials are needed.
Outputs are local artifacts under project_overview/uml/ (ignored by Git).
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from uml_analysis import SourceAnalysis, SUBSYSTEMS
from uml_rendering import graph_layout, render

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).resolve().parent / 'uml'


def discover_classes(root=ROOT):
    analysis = SourceAnalysis(root).analyze()
    return analysis.classes, sorted(analysis.edges)


def generate(root=ROOT, output=OUTPUT_DIR):
    analysis = SourceAnalysis(root).analyze()
    if not analysis.converged:
        raise RuntimeError('Type inference did not converge; inspect source before diagramming.')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'analysis.json').write_text(json.dumps(analysis.report(), indent=2), encoding='utf-8')
    for name in ('bitefinder', *SUBSYSTEMS):
        classes = {key: record for key, record in analysis.classes.items()
                   if name == 'bitefinder' or record['subsystem'] == name}
        edges = [e for e in sorted(analysis.edges) if e[0] in classes and e[1] in classes]
        render(classes, edges, output / (name + '.png'))
    render(analysis.classes, sorted(analysis.edges), output / 'bitefinder_flow.png', compact=True)
    return analysis


class UMLGeneratorTests(unittest.TestCase):
    def fixture(self, files):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, source in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding='utf-8')
        return SourceAnalysis(root).analyze()

    def test_duplicate_names_and_scoped_calls(self):
        analysis = self.fixture({
            'BIS/manager.py': 'class Manager: pass\n',
            'BRNS/manager.py': 'class Manager: pass\n',
            'BIS/workflow.py': 'from BRNS.manager import Manager as Target\n'
                               'class Caller:\n    def run(self): return Target()\n'
                               'class Unrelated: pass\n',
        })
        creates = {(s, t) for s, t, k, *_ in analysis.edges if k == 'creates'}
        self.assertEqual(creates, {('BIS.workflow.Caller', 'BRNS.manager.Manager')})

    def test_factories_injection_ownership_collections_and_calls(self):
        analysis = self.fixture({
            'BIS/parts.py': 'class Part:\n    def run(self): pass\n'
                            'def manager():\n    return Part()\n',
            'BIS/app.py': 'from .parts import Part, manager\n'
                          'class Owner:\n'
                          '    def __init__(self, part, parts):\n'
                          '        self._part = part\n'
                          '        self._parts = [p for p in parts]\n'
                          '        self._owned = Part()\n'
                          '    def run(self): self._part.run()\n'
                          'application = Owner(manager(), [Part()])\n',
        })
        kinds = {k for s, t, k, *_ in analysis.edges
                 if s == 'BIS.app.Owner' and t == 'BIS.parts.Part'}
        self.assertTrue({'association', 'aggregation', 'composition', 'calls'} <= kinds)
        self.assertTrue(analysis.converged)
        self.assertEqual(analysis.classes['BIS.app.Owner']['attributes']['_part'], 'Part')

    def test_reexports_and_tuple_factory_positions(self):
        analysis = self.fixture({
            'BIS/parts.py': 'class First: pass\nclass Second: pass\n',
            'BIS/facade.py': 'from BIS.parts import First as Public\n',
            'BIS/app.py': 'from .facade import Public\nfrom .parts import Second\n'
                          'def managers(): return Public(), Second()\n'
                          'class App:\n'
                          '    def __init__(self, a, b): self.a=a; self.b=b\n'
                          'def create():\n    a,b=managers()\n    return App(a,b)\n'
                          'app=create()\n',
        })
        links = {(t, label) for s, t, kind, label, _ in analysis.edges
                 if s == 'BIS.app.App' and kind == 'association'}
        self.assertEqual(links, {('BIS.parts.First', 'a'), ('BIS.parts.Second', 'b')})

    def test_package_relative_reexport(self):
        analysis = self.fixture({
            'BIS/domain/__init__.py': 'from .part import Part\n',
            'BIS/domain/part.py': 'class Part: pass\n',
            'BIS/app.py': 'from .domain import Part\n'
                          'class App:\n    def run(self): return Part()\n',
        })
        self.assertIn(('BIS.app.App', 'BIS.domain.part.Part', 'creates'),
                      {(s, t, k) for s, t, k, *_ in analysis.edges})

    def test_unknown_dynamic_collaborators_are_not_invented(self):
        analysis = self.fixture({
            'BIS/app.py': 'class App:\n'
                          '    def __init__(self, service): self._service=service\n'
                          '    def run(self): self._service.send()\n',
        })
        self.assertFalse(analysis.edges)
        self.assertTrue(analysis.unresolved)

    def test_lazy_global_imports_are_resolved_without_running_initializers(self):
        analysis = self.fixture({
            'BIS/parts.py': 'class Service: pass\n',
            'BIS/app.py': 'service=None\n'
                          'def initialize():\n'
                          '    global service, Service\n'
                          '    from .parts import Service\n'
                          '    service=Service()\n'
                          'def current():\n    initialize()\n    return service\n'
                          'class App:\n    def __init__(self): self.service=current()\n',
        })
        self.assertIn(('BIS.app.App', 'BIS.parts.Service', 'association'),
                      {(s, t, k) for s, t, k, *_ in analysis.edges})

    def test_registered_lambda_factory_and_forwarding_facade(self):
        analysis = self.fixture({
            'BIS/parts.py': 'class Service:\n    def run(self): pass\n'
                            'class Registry:\n'
                            '    def register(self, factory): self.factory=factory\n'
                            '    def create(self): return self.factory()\n',
            'BIS/facade.py': 'from .parts import Registry, Service\n'
                             'registry=Registry()\n'
                             'registry.register(lambda: Service())\n'
                             'service=registry.create()\n'
                             'def run(): return service.run()\n',
            'BIS/app.py': 'from . import facade\n'
                          'class App:\n    def run(self): facade.run()\n',
        })
        links = {(s, t, k) for s, t, k, *_ in analysis.edges}
        self.assertIn(('BIS.app.App', 'BIS.parts.Service', 'calls'), links)

    def test_annotations_and_default_ownership_are_distinguished(self):
        analysis = self.fixture({
            'BIS/app.py': 'class Helper: pass\n'
                          'class App:\n'
                          '    def __init__(self, supplied: Helper, optional=None):\n'
                          '        self.supplied=supplied\n'
                          '        self.owned=optional or Helper()\n',
        })
        links = {(k, label) for _, _, k, label, _ in analysis.edges}
        self.assertIn(('association', 'supplied'), links)
        self.assertIn(('composition', 'owned (default)'), links)

    def test_http_edge_requires_matching_source_routes(self):
        analysis = self.fixture({
            'BRC/service.py': 'from http.server import BaseHTTPRequestHandler\n'
                              'class Handler(BaseHTTPRequestHandler):\n'
                              '    def do_POST(self):\n'
                              '        if self.path == "/check": pass\n'
                              'class Client:\n'
                              '    def __init__(self): self.url="BRC_SERVICE_URL"\n'
                              '    def verify(self): return self._request("/check")\n'
                              'class Unrelated:\n'
                              '    def __init__(self): self.url="BRC_SERVICE_URL"\n'
                              '    def verify(self): return self._request("/unknown")\n',
        })
        links = {(s, t) for s, t, k, *_ in analysis.edges if k == 'http'}
        self.assertEqual(links, {('BRC.service.Client', 'BRC.service.Handler')})

    def test_layout_spreads_a_subsystem_across_rows_and_columns(self):
        source = '\n'.join(f'class Class{i}: pass' for i in range(12))
        analysis = self.fixture({'BIS/models.py': source})
        boxes, _, _ = graph_layout(analysis.classes, [])
        # Disconnected classes should also be packed; see renderer's component packing.
        self.assertGreater(len({b[0] for b in boxes.values()}), 1)
        self.assertGreater(len({b[1] for b in boxes.values()}), 1)

    def test_generate_current_repository(self):
        analysis = generate()
        self.assertEqual(set(SUBSYSTEMS), {r['subsystem'] for r in analysis.classes.values()})
        for source, target, _, _, evidence in analysis.edges:
            self.assertIn(source, analysis.classes)
            self.assertIn(target, analysis.classes)
            self.assertTrue(evidence)
        links = {(s, t, k) for s, t, k, *_ in analysis.edges}
        self.assertIn(('BIS.classes.bis_search_workflow.BISSearchWorkflow',
                       'BIS.classes.io_manager.IOManager', 'association'), links)
        self.assertIn(('BRNS.classes.result_sorter_registry.ResultSorterRegistry',
                       'BRNS.classes.rating_result_sorter.RatingResultSorter', 'aggregation'), links)
        print(f'\nGenerated {len(analysis.classes)} classes and {len(analysis.edges)} '
              f'source-evidenced relationships in {OUTPUT_DIR}.\n'
              f'{len(analysis.unresolved)} dynamic call sites remain unresolved; see analysis.json.')


if __name__ == '__main__':
    unittest.main()
