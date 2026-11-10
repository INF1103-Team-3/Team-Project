"""Conservative, import-free Python source analysis for diagnostic UML generation.

Types propagate through imports, factory returns, wiring calls and attributes.
Edges carry source evidence; unresolved dynamic collaborators remain unknown.
This is static analysis, not execution or a proof of runtime object lifetimes.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

SUBSYSTEMS = ('BIS', 'BRNS', 'BRC')


def text(node):
    return ast.unparse(node) if node is not None else '?'


def visibility(name):
    if name.startswith('__') and not name.endswith('__'):
        return '-'
    return '#' if name.startswith('_') and not name.startswith('__') else '+'


class SourceAnalysis:
    """Resolve the repository's object graph using bounded fixed-point inference."""

    def __init__(self, root):
        self.root = Path(root)
        self.classes, self.functions, self.modules = {}, {}, {}
        self.aliases = defaultdict(dict)
        self.values = defaultdict(set)
        self.attributes = defaultdict(set)
        self.returns = defaultdict(set)
        self.slots = defaultdict(lambda: defaultdict(set))
        self.edges, self.unresolved = set(), set()
        self.lambdas = {}
        self.packages = set()
        self._index()

    def _imports(self, node, module):
        names = {}
        for item in ast.walk(node):
            if isinstance(item, ast.ImportFrom):
                parts = module.split('.') if module in self.packages else module.split('.')[:-1]
                prefix = '.'.join(parts[:len(parts) - item.level + 1]) if item.level else ''
                prefix = '.'.join(filter(None, (prefix, item.module)))
                if prefix.startswith(('sources.', 'support.')) or prefix in ('sources', 'support'):
                    prefix = 'BIS.' + prefix
                for alias in item.names:
                    names[alias.asname or alias.name] = prefix + '.' + alias.name
            elif isinstance(item, ast.Import):
                for alias in item.names:
                    names[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
        return names

    def _index(self):
        for subsystem in (*SUBSYSTEMS, 'shared'):
            for path in sorted((self.root / subsystem).rglob('*.py')):
                if '__pycache__' in path.parts or '.venv' in path.parts:
                    continue
                parts = list(path.relative_to(self.root).with_suffix('').parts)
                if parts[-1] == '__init__':
                    parts.pop()
                    self.packages.add('.'.join(parts))
                module = '.'.join(parts)
                tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
                self.modules[module] = (tree, str(path.relative_to(self.root)))
                # Module imports only; function-local aliases have their own scope.
                for node in tree.body:
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        self.aliases[module].update(self._imports(node, module))
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._function(module + '.' + node.name, module, None, node)
                    elif isinstance(node, ast.ClassDef):
                        key = module + '.' + node.name
                        methods, attributes = [], {}
                        abstract = False
                        for member in node.body:
                            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                self._function(key + '.' + member.name, module, key, member)
                                parameters = []
                                for arg in member.args.posonlyargs + member.args.args + member.args.kwonlyargs:
                                    if arg.arg not in ('self', 'cls'):
                                        parameters.append(arg.arg + (': ' + text(arg.annotation) if arg.annotation else ''))
                                if member.args.vararg:
                                    parameters.append('*' + member.args.vararg.arg)
                                if member.args.kwarg:
                                    parameters.append('**' + member.args.kwarg.arg)
                                methods.append(visibility(member.name) + ' ' + member.name + '(' + ', '.join(parameters) + ')' + (' : ' + text(member.returns) if member.returns else ''))
                                abstract |= any(text(d).endswith('abstractmethod') for d in member.decorator_list)
                                for assignment in ast.walk(member):
                                    targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target] if isinstance(assignment, ast.AnnAssign) else []
                                    for target in targets:
                                        if isinstance(target, ast.Attribute) and text(target.value) == 'self':
                                            attributes[target.attr] = text(assignment.annotation) if isinstance(assignment, ast.AnnAssign) else '?'
                            elif isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
                                attributes[member.target.id] = text(member.annotation)
                        self.classes[key] = dict(name=node.name, module=module, subsystem=subsystem,
                                                 node=node, attributes=attributes, methods=methods,
                                                 abstract=abstract, path=str(path.relative_to(self.root)), line=node.lineno)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Lambda):
                        key = module + f'.<lambda>@{node.lineno}:{node.col_offset}'
                        self.lambdas[id(node)] = key
                        self.functions[key] = (module, None, node)

    def _function(self, key, module, owner, node):
        self.functions[key] = (module, owner, node)
        self.aliases[key].update(self._imports(node, module))
        if owner:
            self.values[key + '.self'].add(owner)
            self.values[key + '.cls'].add(owner)

    def canonical(self, value):
        seen = set()
        while value not in seen:
            seen.add(value)
            prefix, _, tail = value.rpartition('.')
            replacement = self.aliases.get(prefix, {}).get(tail)
            if not replacement:
                return value
            value = replacement
        return value

    def symbol(self, scope, module, name):
        aliases = self.aliases.get(scope, {})
        if name in aliases:
            return self.canonical(aliases[name])
        if name in self.aliases.get(module, {}):
            return self.canonical(self.aliases[module][name])
        return self.canonical(module + '.' + name)

    def resolve(self, node, scope, module):
        if node is None:
            return set()
        if isinstance(node, ast.Name):
            if node.id in ('None', 'True', 'False'):
                return set()
            symbol = self.symbol(scope, module, node.id)
            return set(self.values.get(scope + '.' + node.id) or self.values.get(symbol) or {symbol})
        if isinstance(node, ast.Attribute):
            result = set()
            for base in self.resolve(node.value, scope, module):
                symbol = self.canonical(base + '.' + node.attr)
                inherited = self._member(base, node.attr, set())
                result.update(self.attributes.get((base, node.attr)) or self.values.get(symbol) or {inherited or symbol})
            return result
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ('tuple', 'list', 'set', 'dict'):
                return self.resolve(node.args[0], scope, module) if node.args else set()
            if isinstance(node.func, ast.Attribute) and node.func.attr == 'get':
                contents = self.resolve(node.func.value, scope, module)
                if contents and all(value in self.functions for value in contents):
                    return contents
            result = set()
            for function in self.resolve(node.func, scope, module):
                if function in self.classes:
                    result.add(function)
                else:
                    result.update(self.returns.get(function, ()))
            return result
        if isinstance(node, ast.Subscript):
            if text(node.value) == 'sys.modules' and text(node.slice) == '__name__':
                return {module}
            return self.resolve(node.value, scope, module)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return set().union(*(self.resolve(e, scope, module) for e in node.elts))
        if isinstance(node, ast.BoolOp):
            return set().union(*(self.resolve(e, scope, module) for e in node.values))
        if isinstance(node, ast.IfExp):
            return self.resolve(node.body, scope, module) | self.resolve(node.orelse, scope, module)
        if isinstance(node, ast.Dict):
            return set().union(*(self.resolve(v, scope, module) for v in node.values))
        if isinstance(node, ast.Lambda):
            return {self.lambdas[id(node)]}
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for generator in node.generators:
                if isinstance(generator.target, ast.Name):
                    self.values[scope + '.' + generator.target.id].update(self.known(self.resolve(generator.iter, scope, module)))
            return self.resolve(node.value if isinstance(node, ast.DictComp) else node.elt, scope, module)
        return set()

    def known(self, values):
        """Unknown symbolic attribute chains must not recursively create types."""
        return {value for value in values
                if value in self.classes or value in self.functions or value in self.modules}

    def _member(self, owner, name, seen):
        if owner in seen or owner not in self.classes:
            return None
        seen.add(owner)
        if owner + '.' + name in self.functions:
            return owner + '.' + name
        record = self.classes[owner]
        for base in record['node'].bases:
            for parent in self.resolve(base, record['module'], record['module']):
                found = self._member(parent, name, seen)
                if found:
                    return found
        return None

    def _bind(self, function, call, scope, module):
        if function in self.classes:
            function += '.__init__'
        if function not in self.functions:
            return
        _, owner, definition = self.functions[function]
        params = definition.args.posonlyargs + definition.args.args
        if owner and params and params[0].arg in ('self', 'cls'):
            params = params[1:]
        for param, value in zip(params, call.args):
            self.values[function + '.' + param.arg].update(self.known(self.resolve(value, scope, module)))
        for keyword in call.keywords:
            if keyword.arg:
                self.values[function + '.' + keyword.arg].update(self.known(self.resolve(keyword.value, scope, module)))
        for param in definition.args.args + definition.args.kwonlyargs:
            if param.annotation:
                self.values[function + '.' + param.arg].update(
                    value for value in self.resolve(param.annotation, function, self.functions[function][0]) if value in self.classes)

    def _assign(self, target, value, scope, module):
        values = self.known(self.resolve(value, scope, module))
        if isinstance(target, ast.Name):
            self.values[scope + '.' + target.id].update(values)
        elif isinstance(target, ast.Attribute):
            for owner in self.resolve(target.value, scope, module):
                if owner in self.classes:
                    self.attributes[owner, target.attr].update(values)
        elif isinstance(target, ast.Subscript):
            self._assign(target.value, value, scope, module)
        elif isinstance(target, (ast.Tuple, ast.List)):
            if isinstance(value, (ast.Tuple, ast.List)):
                for left, right in zip(target.elts, value.elts):
                    self._assign(left, right, scope, module)
            elif isinstance(value, ast.Call):
                for function in self.resolve(value.func, scope, module):
                    for index, left in enumerate(target.elts):
                        if isinstance(left, ast.Name):
                            self.values[scope + '.' + left.id].update(self.slots[function][index])
            else:
                for left in target.elts:
                    self._assign(left, value, scope, module)

    def _scan(self, scope, module, nodes):
        for node in nodes:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    self._assign(target, node.value, scope, module)
            elif isinstance(node, ast.AnnAssign):
                self._assign(node.target, node.value or node.annotation, scope, module)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in ('append', 'extend', 'add') and node.args:
                    self._assign(node.func.value, node.args[0], scope, module)
                for function in self.resolve(node.func, scope, module):
                    self._bind(function, node, scope, module)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                self._assign(node.target, node.iter, scope, module)
            elif isinstance(node, ast.Return):
                self.returns[scope].update(self.known(self.resolve(node.value, scope, module)))
                if isinstance(node.value, (ast.Tuple, ast.List)):
                    for index, item in enumerate(node.value.elts):
                        self.slots[scope][index].update(self.known(self.resolve(item, scope, module)))

    @staticmethod
    def scoped_nodes(definition):
        """Do not attribute a nested closure's returns/calls to its parent."""
        pending = list(reversed(definition.body))
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            yield node
            pending.extend(reversed(list(ast.iter_child_nodes(node))))

    def analyze(self):
        for iteration in range(40):
            before = self._size()
            for module, (tree, _) in self.modules.items():
                nodes = []
                for statement in tree.body:
                    if not isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        nodes.extend(ast.walk(statement))
                self._scan(module, module, nodes)
            for function, (module, _, definition) in self.functions.items():
                for param in definition.args.posonlyargs + definition.args.args + definition.args.kwonlyargs:
                    if param.annotation:
                        for hint in ast.walk(param.annotation):
                            if isinstance(hint, (ast.Name, ast.Attribute)):
                                self.values[function + '.' + param.arg].update(
                                    value for value in self.resolve(hint, function, module) if value in self.classes)
                if isinstance(definition, ast.Lambda):
                    self.returns[function].update(self.known(self.resolve(definition.body, function, module)))
                    self._scan(function, module, ast.walk(definition.body))
                else:
                    self._scan(function, module, self.scoped_nodes(definition))
            if self._size() == before:
                break
        self.iterations = iteration + 1
        self.converged = self._size() == before
        self._relationships()
        self._http_boundaries()
        for (owner, name), types in self.attributes.items():
            if owner in self.classes and name in self.classes[owner]['attributes']:
                known = sorted(self.classes[t]['name'] for t in types if t in self.classes)
                if known and self.classes[owner]['attributes'][name] == '?':
                    self.classes[owner]['attributes'][name] = ' | '.join(dict.fromkeys(known))
        return self

    def _http_boundaries(self):
        """Show a conditional service dependency only with matching route evidence."""
        handlers = []
        for key, record in self.classes.items():
            if not any(text(base).endswith('BaseHTTPRequestHandler') for base in record['node'].bases):
                continue
            routes = set()
            for node in ast.walk(record['node']):
                if isinstance(node, ast.Compare) and text(node.left) == 'self.path':
                    routes.update(c.value for c in node.comparators if isinstance(c, ast.Constant) and isinstance(c.value, str))
            handlers.append((key, routes))
        for key, record in self.classes.items():
            constants = [n for n in ast.walk(record['node']) if isinstance(n, ast.Constant)]
            service = next((n for n in constants if n.value == 'BRC_SERVICE_URL'), None)
            if service is None:
                continue
            routes = {call.args[0].value for call in ast.walk(record['node'])
                      if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                      and call.func.attr == '_request' and call.args
                      and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)}
            matches = [(handler, paths) for handler, paths in handlers if routes and routes <= paths]
            if len(matches) == 1:
                target = matches[0][0]
                evidence = f'{record["path"]}:{service.lineno}; {self.classes[target]["path"]}:{self.classes[target]["line"]}'
                self.edges.add((key, target, 'http', 'BRC_SERVICE_URL configured: ' + ', '.join(sorted(routes)), evidence))

    def _size(self):
        return sum(map(len, self.values.values())) + sum(map(len, self.attributes.values())) + sum(map(len, self.returns.values())) + sum(len(v) for slots in self.slots.values() for v in slots.values())

    def edge(self, source, target, kind, label, module, node):
        if target in self.classes and source != target:
            self.edges.add((source, target, kind, label,
                            f'{self.modules[module][1]}:{node.lineno}'))

    def _relationships(self):
        for key, record in self.classes.items():
            for base in record['node'].bases:
                for target in self.resolve(base, record['module'], record['module']):
                    if target in self.classes:
                        self.edge(key, target, 'implements' if self.classes[target]['name'].endswith('Interface') else 'inherits', '', record['module'], base)
        for function, (module, owner, definition) in self.functions.items():
            if not owner:
                continue
            for node in self.scoped_nodes(definition):
                if isinstance(node, ast.Call):
                    targets = self.resolve(node.func, function, module)
                    for target in targets:
                        if target in self.classes:
                            self.edge(owner, target, 'creates', definition.name, module, node)
                        elif target in self.functions and self.functions[target][1]:
                            self.edge(owner, self.functions[target][1], 'calls', definition.name + ' -> ' + target.rsplit('.', 1)[-1], module, node)
                        elif target in self.functions:
                            for destination, operation in self._forwarded_calls(target, set(), 3):
                                self.edge(owner, destination, 'calls',
                                          definition.name + ' -> ' + operation + ' via ' + target,
                                          module, node)
                    if isinstance(node.func, ast.Attribute) and text(node.func.value).startswith('self.'):
                        receivers = self.resolve(node.func.value, function, module)
                        if not any(r in self.classes or r in self.modules for r in receivers):
                            self.unresolved.add((owner, text(node.func), f'{self.modules[module][1]}:{node.lineno}'))
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    value = node.value
                    for target in targets:
                        if not isinstance(target, ast.Attribute) or text(target.value) != 'self':
                            continue
                        types = self.resolve(value, function, module)
                        for referenced in types:
                            if referenced not in self.classes:
                                continue
                            direct = isinstance(value, ast.Call) and referenced in self.resolve(value.func, function, module)
                            fallback = isinstance(value, ast.BoolOp) and any(isinstance(v, ast.Call) and referenced in self.resolve(v.func, function, module) for v in value.values)
                            collection = (isinstance(value, (ast.ListComp, ast.DictComp, ast.SetComp))
                                          or isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                                          and value.func.id in ('tuple', 'list', 'set', 'dict'))
                            kind = 'composition' if direct or fallback else 'aggregation' if collection else 'association'
                            label = target.attr + (' (default)' if fallback else '')
                            self.edge(owner, referenced, kind, label, module, node)

    def _forwarded_calls(self, function, seen, depth):
        """Trace module delegates without labeling them as production classes."""
        if function in seen or depth == 0:
            return set()
        seen = seen | {function}
        module, _, definition = self.functions[function]
        result = set()
        nodes = ast.walk(definition.body) if isinstance(definition, ast.Lambda) else self.scoped_nodes(definition)
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            for target in self.resolve(node.func, function, module):
                if target in self.functions:
                    owner = self.functions[target][1]
                    if owner:
                        result.add((owner, target.rsplit('.', 1)[-1]))
                    else:
                        result.update(self._forwarded_calls(target, seen, depth - 1))
        return result

    def report(self):
        return dict(classes=[dict(key=key, path=r['path'], line=r['line'], abstract=r['abstract']) for key, r in sorted(self.classes.items())],
                    relationships=[dict(source=s, target=t, kind=k, label=l, evidence=e) for s, t, k, l, e in sorted(self.edges)],
                    unresolved=[dict(source=s, expression=x, evidence=e) for s, x, e in sorted(self.unresolved)],
                    iterations=self.iterations, converged=self.converged,
                    limitations=['Static may-types, not runtime execution order.',
                                 'Ownership edges reflect stored construction or injected collections; they are not a runtime lifetime proof.',
                                 'HTTP edges are conditional configuration/route matches, not proof of a running service.',
                                 'Unbound callbacks and unknown dynamic collaborators are reported, not invented.'])
