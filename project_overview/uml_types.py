"""Evidence-led, import-free reconstruction of Python diagram contracts.

Facts come from annotations, literals, constructor wiring, calls, returns and
reviewed schema boundaries. Unconstrained slots remain explicit in a review
queue instead of acquiring a guessed primitive or a question mark.
"""

import ast
from collections import defaultdict
import re


ALIASES = {
    "AppConfig": "dict[str, Any]",
    "FilterData": "dict[str, Any]",
    "ProfileData": "dict[str, Any]",
    "ChatHistory": "list[dict[str, str]]",
    "ChatDecision": "dict[str, Any]",
    "SearchRequest": "dict[str, Any]",
    "SearchResults": "dict[str, Any]",
    "RestaurantData": "dict[str, Any]",
    "UserData": "dict[str, Any]",
    "OriginData": "dict[str, Any]",
    "DynamicValue": "object",
}


def fields(target, value):
    """Pair each destructured field with its own value, never the RHS tuple."""
    if isinstance(target, (ast.Tuple, ast.List)):
        if isinstance(value, (ast.Tuple, ast.List)):
            for left, right in zip(target.elts, value.elts):
                yield from fields(left, right)
        else:
            for left in target.elts:
                yield from fields(left, None)
    else:
        yield target, value


def arguments(node):
    return node.args.posonlyargs + node.args.args + node.args.kwonlyargs


def generic_parts(value):
    """Split nested generic arguments without splitting inner commas."""
    depth, start, result = 0, 0, []
    for index, char in enumerate(value):
        depth += char in "[("
        depth -= char in "])"
        if char == "," and not depth:
            result.append(value[start:index].strip())
            start = index + 1
    result.append(value[start:].strip())
    return result


def union_parts(value):
    """Split union alternatives without splitting a nested generic union."""
    depth, start, result = 0, 0, []
    for index, char in enumerate(value):
        depth += char in "[("
        depth -= char in "])"
        if char == "|" and not depth:
            result.append(value[start:index].strip())
            start = index + 1
    result.append(value[start:].strip())
    return result


def always_exits(body):
    """Recognize explicit return/raise paths; never assume a loop will run."""
    if not body:
        return False
    last = body[-1]
    if isinstance(last, (ast.Return, ast.Raise)):
        return True
    if isinstance(last, (ast.With, ast.AsyncWith)):
        return always_exits(last.body)
    if isinstance(last, ast.If):
        return (
            bool(last.orelse)
            and always_exits(last.body)
            and always_exits(last.orelse)
        )
    if isinstance(last, ast.Try):
        return (
            always_exits(last.finalbody)
            or always_exits(last.body)
            and all(always_exits(handler.body) for handler in last.handlers)
        )
    return False


class TypeReconstruction:
    """Propagate bounded static type facts with a per-slot evidence ledger."""

    def __init__(self, analysis):
        self.analysis = analysis
        self.facts = defaultdict(set)
        self.evidence = defaultdict(set)
        self.review = []
        self.nodes = {}
        self.locations = {}
        self.return_gaps = {}
        self.overrides = {}
        self.aliases = dict(ALIASES)
        self.record_fields = defaultdict(lambda: defaultdict(set))
        self.functions = dict(analysis.functions)
        self._index_closures()
        self._seed()
        self._reviewed_chat_contracts()
        self._reviewed_ranking_contracts()
        self._reviewed_brc_contracts()
        for iteration in range(24):
            before = sum(len(v) for v in self.facts.values())
            for module, (tree, _) in analysis.modules.items():
                self._scan(module, module, None, tree.body)
            for scope, (module, owner, node) in list(self.functions.items()):
                if isinstance(node, ast.Lambda):
                    self.add(
                        scope + ".return",
                        self.expression(node.body, scope, module, owner),
                        "lambda return expression",
                        self.location(module, node),
                    )
                else:
                    self._scan(scope, module, owner, node.body)
            self._interfaces()
            if sum(len(v) for v in self.facts.values()) == before:
                break
        self.iterations = iteration + 1

    def _index_closures(self):
        for scope, (module, owner, node) in list(self.functions.items()):
            if isinstance(node, ast.Lambda):
                continue
            for child in ast.walk(node):
                if child is node or not isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    continue
                key = scope + ".<locals>." + child.name
                self.functions[key] = module, owner, child
                self.facts[scope + "." + child.name].add("callable:" + key)

    def location(self, module, node):
        return (
            self.analysis.modules[module][1]
            + ":"
            + str(getattr(node, "lineno", 1))
        )

    def add(self, slot, values, why, location):
        if not values:
            return
        # Bound recursively nested containers and unstable indirect factories.
        values = {v for v in values if len(v) < 260 and v.count("[") < 7}
        self.facts[slot].update(values)
        self.evidence[slot].add(location + " | " + why)
        self.locations.setdefault(slot, location)

    def _seed(self):
        for owner, record in self.analysis.classes.items():
            for node in ast.walk(record["node"]):
                if not isinstance(node, ast.AnnAssign):
                    continue
                target = node.target
                name = (target.id if isinstance(target, ast.Name)
                        and node in record["node"].body else
                        target.attr if isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self" else None)
                if name is None:
                    continue
                slot = owner + "." + name
                dtype = ast.unparse(node.annotation)
                self.overrides[slot] = dtype
                self.add(slot, {dtype}, "declared attribute annotation",
                         self.location(record["module"], node))
        for scope, (module, owner, node) in self.functions.items():
            if isinstance(node, ast.Lambda):
                continue
            for arg in arguments(node):
                slot = scope + "." + arg.arg
                self.nodes[slot] = arg
                self.locations[slot] = self.location(module, arg)
                if arg.annotation:
                    value = ast.unparse(arg.annotation)
                    self.overrides[slot] = value
                    self.add(
                        slot,
                        {value},
                        "declared annotation",
                        self.location(module, arg),
                    )
            if owner:
                self.add(
                    scope + ".self",
                    {owner},
                    "method owner",
                    self.location(module, node),
                )
                self.add(
                    scope + ".cls",
                    {owner},
                    "class receiver",
                    self.location(module, node),
                )
            defaults = [None] * (
                len(node.args.posonlyargs + node.args.args)
                - len(node.args.defaults)
            ) + node.args.defaults
            for arg, default in zip(
                node.args.posonlyargs + node.args.args, defaults
            ):
                self.add(
                    scope + "." + arg.arg,
                    self.expression(default, scope, module, owner),
                    "parameter default",
                    self.location(module, arg),
                )
            for arg, default in zip(
                node.args.kwonlyargs, node.args.kw_defaults
            ):
                self.add(
                    scope + "." + arg.arg,
                    self.expression(default, scope, module, owner),
                    "keyword default",
                    self.location(module, arg),
                )
            if node.args.vararg:
                self.add(
                    scope + "." + node.args.vararg.arg,
                    {"tuple[Any, ...]"},
                    "variadic positional tuple",
                    self.location(module, node),
                )
            if node.args.kwarg:
                self.add(
                    scope + "." + node.args.kwarg.arg,
                    {"dict[str, Any]"},
                    "variadic keyword mapping",
                    self.location(module, node),
                )
            if node.returns:
                value = ast.unparse(node.returns)
                self.overrides[scope + ".return"] = value
                self.add(
                    scope + ".return",
                    {value},
                    "declared return",
                    self.location(module, node),
                )
        # Existing wiring supplies class/module/function identities. It must
        # not be used as collection element/cardinality data.
        for (owner, name), values in self.analysis.attributes.items():
            collection = False
            for assignment in ast.walk(self.analysis.classes[owner]["node"]):
                target_list = (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                    if isinstance(assignment, ast.AnnAssign)
                    else []
                )
                for target in target_list:
                    for field, value in fields(
                        target, getattr(assignment, "value", None)
                    ):
                        if (
                            isinstance(field, ast.Attribute)
                            and field.attr == name
                        ):
                            collection |= (
                                isinstance(
                                    value,
                                    (
                                        ast.Dict,
                                        ast.List,
                                        ast.Tuple,
                                        ast.Set,
                                        ast.ListComp,
                                        ast.DictComp,
                                        ast.SetComp,
                                    ),
                                )
                                or isinstance(value, ast.Call)
                                and isinstance(value.func, ast.Name)
                                and value.func.id
                                in ("list", "tuple", "dict", "set")
                            )
            if collection:
                continue
            known = {v for v in values if v in self.analysis.classes}
            if known:
                self.add(
                    owner + "." + name,
                    known,
                    "resolved constructor/caller wiring",
                    self.analysis.classes[owner]["path"],
                )

    def _reviewed_chat_contracts(self):
        proof = (
            "BIS/classes/io/web/models/search/chat_request_model.py",
            "BIS/classes/services/web/bis_chatbot_service.py",
            "BIS/classes/ai/tasks/bis_interpreter.py",
            "BIS/support/config.py",
        )
        # Only seed when the actual reviewed methods and schema exist. Fixture
        # classes with similar names must not silently inherit these contracts.
        if not all((self.analysis.root / path).is_file() for path in proof):
            return
        schemas = {
            "process": {
                "record": "ProfileCommand", "config": "AppConfig",
                "return": "ProfileAction",
            },
            "interpret_search_request": {
                "request": "SearchRequest", "today_request": "str",
                "config": "AppConfig", "return": "SearchRequest",
            },
            "chat_turn": {
                "message": "str",
                "current_filters": "FilterData",
                "history": "ChatHistory",
                "saved_profile": "ProfileData",
                "config": "AppConfig",
                "return": "ChatDecision",
            },
            "interpret_chat_turn": {
                "message": "str",
                "current_filters": "FilterData",
                "history": "ChatHistory",
                "saved_profile": "ProfileData",
                "config": "AppConfig",
                "return": "ChatDecision",
            },
            "review_profile_wishes": {
                "wishes": "list[str]",
                "config": "AppConfig",
                "return": "list[str]",
            },
        }
        self.aliases["ProfileCommand"] = "dict[str, Any]"
        self.aliases["ProfileAction"] = "dict[str, Any]"
        for scope, (module, owner, node) in self.functions.items():
            if (
                not owner
                or not owner.startswith("BIS.")
                or node.name not in schemas
            ):
                continue
            if node.name in ("process", "interpret_search_request") and not (
                owner.endswith((".AIManager", ".BISAIManagerInterface"))
            ):
                continue
            for name, dtype in schemas[node.name].items():
                slot = scope + "." + name
                self.overrides[slot] = dtype
                for path in proof:
                    self.add(
                        slot,
                        {dtype},
                        "reviewed chat caller/schema/validator contract",
                        path,
                    )
                if node.name in ("process", "interpret_search_request"):
                    self.add(
                        slot, {dtype}, "reviewed request/profile validator",
                        "BIS/ai_manager.py:365; "
                        "BIS/classes/ai/ai_manager.py:39; "
                        "BIS/classes/services/cli/interaction_session.py:262",
                    )

    def _reviewed_ranking_contracts(self):
        path = self.analysis.root / "BRNS/ai_manager.py"
        if not path.is_file():
            return
        module = "BRNS.ai_manager"
        if module not in self.analysis.modules:
            return
        self.aliases["Recommendations"] = "list[dict[str, Any]]"
        self.aliases["RecommendationContext"] = "dict[str, Any]"
        contracts = {
            "recommend_prepared": {
                "context": "RecommendationContext",
                "candidate_count": "int",
                "return": "Recommendations | None",
            },
            "_recommend_prepared": {
                "context": "RecommendationContext",
                "candidate_count": "int",
                "return": "Recommendations | None",
            },
            "recommend_candidates": {
                "request": "SearchRequest",
                "candidates": "list[RestaurantData]",
                "previous_restaurants": "Sequence[RestaurantData]",
                "return": "Recommendations | None",
            },
            "_recommend_candidates": {
                "request": "SearchRequest",
                "candidates": "list[RestaurantData]",
                "previous_restaurants": "Sequence[RestaurantData]",
                "return": "Recommendations | None",
            },
        }
        proof = self.functions.get(module + "._recommend_prepared")
        if not proof:
            return
        location = self.location(module, proof[2])
        for scope, (source, owner, node) in self.functions.items():
            if (
                not scope.startswith("BRNS.")
                or isinstance(node, ast.Lambda)
                or node.name not in contracts
            ):
                continue
            for name, dtype in contracts[node.name].items():
                slot = scope + "." + name
                self.overrides[slot] = dtype
                self.add(
                    slot,
                    {dtype},
                    "reviewed ranking validator and explicit None failure "
                    "return",
                    location,
                )

    def _reviewed_brc_contracts(self):
        module = "BRC.classes.ai.ai_manager"
        if module not in self.analysis.modules:
            return
        contracts = {
            "tag_batch": {
                "batch": "list[tuple[int, BRC.MuisListing]]",
                "return": "dict[int, list[str]]",
            },
            "_tag_batch": {
                "batch": "list[tuple[int, BRC.MuisListing]]",
                "return": "dict[int, list[str]]",
            },
            "_read_cuisines": {
                "raw": "str",
                "expected": "set[int]",
                "return": "dict[int, list[str]]",
            },
            "propose_match": {
                "number": "int",
                "record": "BRC.RestaurantRecord",
                "candidates": "list[BRC.HalalOutlet]",
                "return": "str | None",
            },
            "_ask_for_match": {
                "number": "int",
                "record": "BRC.RestaurantRecord",
                "candidates": "list[BRC.HalalOutlet]",
                "return": "str | None",
            },
            "_read_match": {
                "raw": "str",
                "number": "int",
                "allowed": "set[str]",
                "return": "str | None",
            },
            "parse_response": {
                "raw": "str",
                "object_ok": "bool",
                "return": "dict[str, Any] | list[Any]",
            },
            "validate_response": {
                "data": "dict[str, Any] | list[Any]",
                "expected_ids": "set[int] | None",
                "object_keys": "set[str] | None",
                "return": "bool",
            },
        }
        for scope, (source, owner, node) in self.functions.items():
            if source != module or not owner or node.name not in contracts:
                continue
            for name, dtype in contracts[node.name].items():
                slot = scope + "." + name
                self.overrides[slot] = dtype
                self.add(
                    slot,
                    {dtype},
                    "reviewed BRC JSON parser, cuisine and match validators",
                    self.location(module, node),
                )
                self.add(
                    slot,
                    {dtype},
                    "indexed listing and outlet workflow caller",
                    "BRC/classes/services/workflows/"
                    + (
                        "cuisine_tagging_workflow.py:32"
                        if "batch" in node.name or "cuisines" in node.name
                        else "outlet_matching_workflow.py:28"
                    ),
                )

    def _symbol(self, node, scope, module, owner):
        if isinstance(node, ast.Name):
            if node.id == "cls" and owner:
                return {owner}
            local = self.facts.get(scope + "." + node.id, set())
            callbacks = {
                v.split(":", 1)[1]
                for v in local
                if v.startswith(("callable:", "type:"))
            }
            if callbacks:
                return callbacks
            key = self.analysis.symbol(scope, module, node.id)
            return {key}
        if isinstance(node, ast.Attribute):
            result = {
                value.split(":", 1)[1]
                for value in self.expression(node, scope, module, owner)
                if value.startswith(("callable:", "type:"))
            }
            for receiver in self.expression(node.value, scope, module, owner):
                if receiver in self.analysis.classes:
                    found = self.analysis._member(receiver, node.attr, set())
                    if found:
                        result.add(found)
                if receiver.startswith("module:"):
                    result.add(
                        self.analysis.canonical(receiver[7:] + "." + node.attr)
                    )
            if not result and isinstance(node.value, ast.Name):
                name = node.value.id
                aliases = {
                    **self.analysis.aliases.get(module, {}),
                    **self.analysis.aliases.get(scope, {}),
                }
                if name in aliases:
                    result.add(
                        self.analysis.canonical(
                            aliases[name] + "." + node.attr
                        )
                    )
            return result
        return set()

    def union(self, values):
        values = {part for value in values for part in union_parts(value)}
        # Preserve semantic aliases rather than expanding heterogeneous record
        # values to an enormous, misleading union of primitive alternatives.
        if "Any" in values:
            return "Any"
        if not values:
            return "DynamicValue"
        return " | ".join(sorted(values, key=lambda v: (v == "None", v)))

    def element(self, value, index=None):
        expanded = ALIASES.get(value, value)
        if expanded.startswith("ItemsView["):
            return {"tuple[" + expanded[10:-1] + "]"}
        if expanded.startswith(
            (
                "list[",
                "set[",
                "tuple[",
                "Sequence[",
                "Iterable[",
                "Iterator[",
                "range[",
                "KeysView[",
                "ValuesView[",
            )
        ):
            parts = generic_parts(expanded[expanded.index("[") + 1: -1])
            if (
                expanded.startswith("tuple[")
                and index is not None
                and index < len(parts)
                and parts[-1] != "..."
            ):
                return {parts[index]}
            return {parts[0]} if parts else set()
        if expanded == "str":
            return {"str"}
        if expanded.startswith("dict["):
            return {generic_parts(expanded[5:-1])[0]}
        return set()

    def expression(self, node, scope, module, owner=None):
        if node is None:
            return set()
        if isinstance(node, ast.Constant):
            return {
                "None" if node.value is None else type(node.value).__name__
            }
        if isinstance(node, ast.JoinedStr):
            return {"str"}
        if isinstance(node, ast.Lambda):
            key = self.analysis.lambdas.get(id(node))
            return {"callable:" + key} if key else set()
        if isinstance(node, ast.Name):
            if node.id in ("self", "cls") and owner:
                return {owner}
            if node.id in (
                "input",
                "print",
                "str",
                "int",
                "float",
                "bool",
                "dict",
                "list",
                "tuple",
                "set",
            ):
                return {"callable:builtins." + node.id}
            slot = scope + "." + node.id
            if slot in self.overrides:
                return {self.overrides[slot]}
            value = self.facts.get(slot)
            if value:
                return set(value)
            key = self.analysis.symbol(scope, module, node.id)
            if key in self.analysis.classes:
                return {"type:" + key}
            if key in self.functions:
                return {"callable:" + key}
            if key in self.analysis.modules:
                return {"module:" + key}
            if key in (
                "sys",
                "os",
                "json",
                "math",
                "time",
                "re",
                "datetime",
                "threading",
                "requests",
            ):
                return {"module:" + key}
            return set(self.facts.get(key, set()))
        if isinstance(node, ast.Attribute):
            result = set()
            for receiver in self.expression(node.value, scope, module, owner):
                if receiver.startswith("type:"):
                    receiver = receiver[5:]
                result.update(
                    self.facts.get(receiver + "." + node.attr, set())
                )
                if receiver.startswith("module:"):
                    symbol = self.analysis.canonical(
                        receiver[7:] + "." + node.attr
                    )
                    result.update(self.facts.get(symbol, set()))
                    if symbol in self.functions:
                        result.add("callable:" + symbol)
                    if symbol in self.analysis.classes:
                        result.add("type:" + symbol)
                    if symbol in ("sys.stdout", "sys.stderr", "sys.stdin"):
                        result.add("TextIO")
                if receiver in self.analysis.classes:
                    method = self.analysis._member(receiver, node.attr, set())
                    if method:
                        definition = self.functions.get(method)
                        if definition and any(
                            ast.unparse(d) == "property"
                            for d in definition[2].decorator_list
                        ):
                            result.update(
                                self.facts.get(method + ".return", set())
                            )
                        else:
                            result.add("callable:" + method)
                if receiver == "Path" and node.attr in ("parent",):
                    result.add("Path")
                if receiver == "Path" and node.attr in (
                    "name",
                    "stem",
                    "suffix",
                ):
                    result.add("str")
            return result
        if isinstance(node, ast.Dict):
            keys = {
                k.value
                for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            for required, alias in (
                ({"app_name", "ai_bypass", "openrouter_model"}, "AppConfig"),
                (
                    {"intent", "reply", "updates", "quick_replies"},
                    "ChatDecision",
                ),
                ({"matches", "alternatives"}, "SearchResults"),
                ({"origin", "cuisine", "mode"}, "SearchRequest"),
                ({"latitude", "longitude"}, "OriginData"),
                ({"name", "address", "lat", "lng"}, "RestaurantData"),
                ({"userID", "preferences"}, "UserData"),
            ):
                if required <= keys:
                    return {alias}
            key_types = (
                set().union(
                    *(
                        self.expression(k, scope, module, owner)
                        for k in node.keys
                    )
                )
                if node.keys
                else {"Any"}
            )
            values = (
                set().union(
                    *(
                        self.expression(v, scope, module, owner)
                        for v in node.values
                    )
                )
                if node.values
                else {"Any"}
            )
            return {
                "dict["
                + self.union(key_types)
                + ", "
                + (next(iter(values)) if len(values) == 1 else "Any")
                + "]"
            }
        if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
            types = [
                self.union(self.expression(v, scope, module, owner))
                for v in node.elts
            ]
            if isinstance(node, ast.Tuple):
                return {
                    "tuple["
                    + (", ".join(types) if types else "Any, ...")
                    + "]"
                }
            container = "list" if isinstance(node, ast.List) else "set"
            return {container + "[" + self.union(types or {"Any"}) + "]"}
        if isinstance(
            node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
        ):
            for generator in node.generators:
                values = self.expression(generator.iter, scope, module, owner)
                elements = (
                    set().union(*(self.element(v) for v in values))
                    if values
                    else set()
                )
                self._assign(
                    generator.target, elements, scope, module, owner, generator
                )
            if isinstance(node, ast.DictComp):
                key = self.union(
                    self.expression(node.key, scope, module, owner)
                )
                value = self.union(
                    self.expression(node.value, scope, module, owner)
                )
                return {"dict[" + key + ", " + value + "]"}
            value = self.union(self.expression(node.elt, scope, module, owner))
            kind = (
                "list"
                if isinstance(node, ast.ListComp)
                else "set"
                if isinstance(node, ast.SetComp)
                else "Iterator"
            )
            return {kind + "[" + value + "]"}
        if isinstance(node, ast.Subscript):
            result = set()
            for value in self.expression(node.value, scope, module, owner):
                expanded = ALIASES.get(value, value)
                if isinstance(node.slice, ast.Slice):
                    result.add(value)
                elif expanded.startswith("dict["):
                    result.add(generic_parts(expanded[5:-1])[-1])
                else:
                    index = (
                        node.slice.value
                        if isinstance(node.slice, ast.Constant)
                        and isinstance(node.slice.value, int)
                        else None
                    )
                    result.update(self.element(value, index))
            return result
        if isinstance(node, ast.BoolOp):
            result = set()
            for position, item in enumerate(node.values):
                values = self.expression(item, scope, module, owner)
                if (
                    isinstance(node.op, ast.Or)
                    and position < len(node.values) - 1
                ):
                    values -= {"None"}
                result.update(values)
            return result
        if isinstance(node, ast.IfExp):
            return self.expression(
                node.body, scope, module, owner
            ) | self.expression(node.orelse, scope, module, owner)
        if isinstance(node, (ast.Compare, ast.UnaryOp)):
            if isinstance(node, ast.Compare) or isinstance(node.op, ast.Not):
                return {"bool"}
            return self.expression(node.operand, scope, module, owner)
        if isinstance(node, ast.BinOp):
            left, right = (
                self.expression(node.left, scope, module, owner),
                self.expression(node.right, scope, module, owner),
            )
            if (
                left
                and right
                and left <= {"int", "float"}
                and right <= {"int", "float"}
            ):
                return {
                    "float"
                    if "float" in left | right or isinstance(node.op, ast.Div)
                    else "int"
                }
            if left == right == {"str"} and isinstance(
                node.op, (ast.Add, ast.Mod)
            ):
                return {"str"}
            if left == {"Path"} and isinstance(node.op, ast.Div):
                return {"Path"}
            return left & right
        if isinstance(node, ast.Call):
            return self._call(node, scope, module, owner)
        return set()

    def _call(self, node, scope, module, owner):
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in ("str", "int", "float", "bool", "bytes"):
                return {name}
            if name in ("len", "hash", "ord"):
                return {"int"}
            if name in ("min", "max", "sum"):
                values = (
                    set().union(
                        *(
                            self.expression(arg, scope, module, owner)
                            for arg in node.args
                        )
                    )
                    if node.args
                    else set()
                )
                numeric = values & {"int", "float", "bool"}
                if not numeric:
                    numeric = set().union(
                        *(self.element(v) for v in values)
                    ) & {"int", "float", "bool"}
                return (
                    {"float" if "float" in numeric else "int"}
                    if numeric
                    else set()
                )
            if name == "round":
                return {"float"} if len(node.args) > 1 else {"int"}
            if name == "range":
                return {"range[int]"}
            if name in ("zip", "enumerate"):
                parts = []
                for arg in node.args:
                    values = self.expression(arg, scope, module, owner)
                    elements = (
                        set().union(*(self.element(v) for v in values))
                        if values
                        else set()
                    )
                    parts.append(self.union(elements))
                if name == "enumerate":
                    parts = ["int"] + parts[:1]
                return {"Iterator[tuple[" + ", ".join(parts) + "]]"}
            if name in (
                "isinstance",
                "issubclass",
                "callable",
                "all",
                "any",
                "hasattr",
            ):
                return {"bool"}
            if name == "input":
                return {"str"}
            if name == "print":
                return {"None"}
            if name in ("list", "set", "tuple", "sorted"):
                source = (
                    self.expression(node.args[0], scope, module, owner)
                    if node.args
                    else set()
                )
                values = (
                    set().union(*(self.element(v) for v in source))
                    if source
                    else {"Any"}
                )
                kind = "list" if name == "sorted" else name
                return {
                    kind
                    + "["
                    + self.union(values)
                    + (", ..." if kind == "tuple" else "")
                    + "]"
                }
            if name == "dict":
                return {"dict[str, Any]"}
        symbols = self._symbol(node.func, scope, module, owner)
        result = set()
        for symbol in symbols:
            if symbol in self.analysis.classes:
                result.add(symbol)
            if symbol in self.functions:
                values = (
                    {self.overrides[symbol + ".return"]}
                    if symbol + ".return" in self.overrides
                    else self.facts.get(symbol + ".return", set())
                )
                if not (values == {"None"} and self.return_gaps.get(symbol)):
                    result.update(values)
            if symbol.startswith("builtins."):
                result.update(
                    {
                        "builtins.input": {"str"},
                        "builtins.print": {"None"},
                        "builtins.str": {"str"},
                        "builtins.int": {"int"},
                        "builtins.float": {"float"},
                        "builtins.bool": {"bool"},
                        "builtins.dict": {"dict[str, Any]"},
                        "builtins.list": {"list[DynamicValue]"},
                        "builtins.tuple": {"tuple[DynamicValue, ...]"},
                        "builtins.set": {"set[DynamicValue]"},
                    }.get(symbol, set())
                )
            if symbol in (
                "pathlib.Path",
                "pathlib.PosixPath",
                "pathlib.WindowsPath",
            ):
                result.add("Path")
            if symbol in ("json.dumps", "json.dumps"):
                result.add("str")
            if symbol == "os.getenv":
                default = (
                    self.expression(node.args[1], scope, module, owner)
                    if len(node.args) > 1
                    else {"None"}
                )
                result.update({"str"} | default)
            if symbol in ("json.dump", "time.sleep"):
                result.add("None")
            if symbol in ("copy.copy", "copy.deepcopy") and node.args:
                result.update(
                    self.expression(node.args[0], scope, module, owner)
                )
            if symbol in ("re.sub", "re.escape"):
                result.add("str")
            if symbol == "re.compile":
                result.add("Pattern[str]")
            if symbol in (
                "datetime.datetime.now",
                "datetime.datetime.utcnow",
                "datetime.datetime.fromisoformat",
            ):
                result.add("datetime")
            if symbol.startswith("time.") and symbol.rsplit(".", 1)[-1] in (
                "time",
                "monotonic",
                "perf_counter",
            ):
                result.add("float")
        if isinstance(node.func, ast.Attribute):
            operation = node.func.attr
            receivers = self.expression(node.func.value, scope, module, owner)
            for receiver in receivers:
                value = ALIASES.get(receiver, receiver)
                if receiver.startswith("callable:"):
                    result.update(
                        self.facts.get(receiver[9:] + ".return", set())
                    )
                if value == "str":
                    if operation in (
                        "strip",
                        "lstrip",
                        "rstrip",
                        "lower",
                        "upper",
                        "casefold",
                        "replace",
                        "format",
                        "join",
                        "removeprefix",
                        "removesuffix",
                    ):
                        result.add("str")
                    elif operation in ("split", "rsplit", "splitlines"):
                        result.add("list[str]")
                    elif operation in (
                        "startswith",
                        "endswith",
                        "isdigit",
                        "isalpha",
                        "isalnum",
                        "isspace",
                    ):
                        result.add("bool")
                    elif operation == "encode":
                        result.add("bytes")
                if value.startswith("dict["):
                    if operation in ("get", "setdefault", "pop"):
                        key = (
                            node.args[0].value
                            if node.args
                            and isinstance(node.args[0], ast.Constant)
                            else None
                        )
                        defined = self.record_fields[receiver].get(key, set())
                        if defined:
                            result.update(defined)
                            result.update(
                                self.expression(
                                    node.args[1], scope, module, owner
                                )
                                if len(node.args) > 1
                                else {"None"}
                            )
                        else:
                            result.add(generic_parts(value[5:-1])[-1])
                    elif operation in ("update", "clear"):
                        result.add("None")
                    elif operation == "copy":
                        result.add(receiver)
                    elif operation in ("items", "keys", "values"):
                        key_type, value_type = generic_parts(value[5:-1])
                        result.add(
                            {
                                "items": "ItemsView["
                                + key_type
                                + ", "
                                + value_type
                                + "]",
                                "keys": "KeysView[" + key_type + "]",
                                "values": "ValuesView[" + value_type + "]",
                            }[operation]
                        )
                if value.startswith(("list[", "set[")):
                    if operation in (
                        "append",
                        "extend",
                        "add",
                        "discard",
                        "clear",
                        "sort",
                        "reverse",
                        "remove",
                    ):
                        result.add("None")
                    elif operation == "copy":
                        result.add(receiver)
                    elif operation == "pop":
                        result.update(self.element(receiver))
                if receiver == "Path":
                    result.update(
                        {
                            "exists": {"bool"},
                            "is_file": {"bool"},
                            "read_text": {"str"},
                            "read_bytes": {"bytes"},
                            "write_text": {"int"},
                            "write_bytes": {"int"},
                            "mkdir": {"None"},
                            "unlink": {"None"},
                            "resolve": {"Path"},
                            "with_name": {"Path"},
                            "with_suffix": {"Path"},
                        }.get(operation, set())
                    )
                if receiver == "datetime" and operation in (
                    "isoformat",
                    "strftime",
                ):
                    result.add("str")
                if receiver == "TextIO" and operation == "write":
                    result.add("int")
                if receiver == "Pattern[str]" and operation in (
                    "match",
                    "search",
                    "fullmatch",
                ):
                    result.add("Match[str] | None")
                if (
                    operation == "model_dump"
                    and receiver in self.analysis.classes
                ):
                    result.add("dict[str, Any]")
        return result

    def _assign(self, target, values, scope, module, owner, node):
        location = self.location(module, node)
        if isinstance(target, ast.Name):
            self.add(
                scope + "." + target.id,
                values,
                "assigned expression",
                location,
            )
        elif isinstance(target, ast.Attribute):
            for receiver in self.expression(
                target.value, scope, module, owner
            ):
                self.add(
                    receiver + "." + target.attr,
                    values,
                    "stored expression",
                    location,
                )
        elif isinstance(target, (ast.Tuple, ast.List)):
            for index, part in enumerate(target.elts):
                elements = (
                    set().union(*(self.element(v, index) for v in values))
                    if values
                    else set()
                )
                self._assign(part, elements, scope, module, owner, node)

    def _scan(self, scope, module, owner, body):
        if scope in self.functions and not isinstance(
            self.functions[scope][2], ast.Lambda
        ):
            definition = self.functions[scope][2]
            positional = definition.args.posonlyargs + definition.args.args
            defaults = [None] * (
                len(positional) - len(definition.args.defaults)
            ) + definition.args.defaults
            for arg, default in zip(positional, defaults):
                self.add(
                    scope + "." + arg.arg,
                    self.expression(default, scope, module, owner),
                    "parameter default",
                    self.location(module, arg),
                )
        pending = list(reversed(body))
        returns, gaps, yielded, has_return = set(), [], set(), False
        while pending:
            node = pending.pop()
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Lambda,
                ),
            ):
                if isinstance(node, ast.ClassDef) and scope == module:
                    # Class fields are indexed separately from method bodies.
                    self._scan(
                        module + "." + node.name,
                        module,
                        module + "." + node.name,
                        [
                            n
                            for n in node.body
                            if not isinstance(
                                n, (ast.FunctionDef, ast.AsyncFunctionDef)
                            )
                        ],
                    )
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else [node.target]
                ):
                    for left, right in fields(target, node.value):
                        self._assign(
                            left,
                            self.expression(right, scope, module, owner),
                            scope,
                            module,
                            owner,
                            node,
                        )
                        if (
                            isinstance(right, ast.BoolOp)
                            and isinstance(right.op, ast.Or)
                            and isinstance(right.values[0], ast.Name)
                        ):
                            injected = right.values[0]
                            if scope + "." + injected.id in self.nodes:
                                self.add(
                                    scope + "." + injected.id,
                                    self.expression(
                                        right.values[-1], scope, module, owner
                                    ),
                                    "injected override shares the constructed "
                                    "default's contract",
                                    self.location(module, node),
                                )
                if isinstance(node.value, ast.Dict):
                    aliases = (
                        self.expression(node.value, scope, module, owner)
                        & ALIASES.keys()
                    )
                    for alias in aliases:
                        for key, value in zip(
                            node.value.keys, node.value.values
                        ):
                            if isinstance(key, ast.Constant) and isinstance(
                                key.value, str
                            ):
                                self.record_fields[alias][key.value].update(
                                    self.expression(
                                        value, scope, module, owner
                                    )
                                )
            if isinstance(node, (ast.For, ast.AsyncFor)):
                values = self.expression(node.iter, scope, module, owner)
                elements = (
                    set().union(*(self.element(v) for v in values))
                    if values
                    else set()
                )
                self._assign(node.target, elements, scope, module, owner, node)
            if (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.op, ast.Not)
                and any(isinstance(n, ast.Raise) for n in node.body)
            ):
                check = node.test.operand
                if (
                    isinstance(check, ast.Call)
                    and isinstance(check.func, ast.Name)
                    and check.func.id == "isinstance"
                    and len(check.args) == 2
                    and isinstance(check.args[0], ast.Name)
                ):
                    kinds = (
                        check.args[1].elts
                        if isinstance(check.args[1], ast.Tuple)
                        else [check.args[1]]
                    )
                    validated = {
                        v.id
                        for v in kinds
                        if isinstance(v, ast.Name)
                        and v.id
                        in (
                            "str",
                            "int",
                            "float",
                            "bool",
                            "dict",
                            "list",
                            "tuple",
                        )
                    }
                    typed = {
                        "dict[str, Any]"
                        if v == "dict"
                        else "list[DynamicValue]"
                        if v == "list"
                        else "tuple[DynamicValue, ...]"
                        if v == "tuple"
                        else v
                        for v in validated
                    }
                    self.add(
                        scope + "." + check.args[0].id,
                        typed,
                        "rejects values outside isinstance contract",
                        self.location(module, node),
                    )
            if isinstance(node, ast.Call):
                for target in self._symbol(node.func, scope, module, owner):
                    if target in self.analysis.classes:
                        target += ".__init__"
                    if target not in self.functions:
                        continue
                    definition = self.functions[target][2]
                    params = definition.args.posonlyargs + definition.args.args
                    if params and params[0].arg in ("self", "cls"):
                        params = params[1:]
                    for param, value in zip(params, node.args):
                        self.add(
                            target + "." + param.arg,
                            self.expression(value, scope, module, owner),
                            "caller " + scope,
                            self.location(module, node),
                        )
                    for keyword in node.keywords:
                        if keyword.arg:
                            self.add(
                                target + "." + keyword.arg,
                                self.expression(
                                    keyword.value, scope, module, owner
                                ),
                                "keyword caller " + scope,
                                self.location(module, node),
                            )
            if isinstance(node, ast.Return):
                has_return = True
                values = (
                    self.expression(node.value, scope, module, owner)
                    if node.value
                    else {"None"}
                )
                returns.update(values)
                if not values:
                    gaps.append(self.location(module, node))
            if isinstance(node, (ast.Yield, ast.YieldFrom)):
                value = self.expression(node.value, scope, module, owner)
                if isinstance(node, ast.YieldFrom):
                    value = (
                        set().union(*(self.element(v) for v in value))
                        if value
                        else set()
                    )
                yielded.update(value or {"DynamicValue"})
            pending.extend(reversed(list(ast.iter_child_nodes(node))))
        if scope in self.functions and not isinstance(
            self.functions[scope][2], ast.Lambda
        ):
            definition = self.functions[scope][2]
            abstract = any(
                ast.unparse(d).endswith("abstractmethod")
                for d in definition.decorator_list
            )
            if yielded:
                returns = {
                    "Generator["
                    + self.union(yielded)
                    + ", DynamicValue, "
                    + self.union(returns or {"None"})
                    + "]"
                }
            elif not has_return and not abstract:
                returns.add(
                    "Never"
                    if definition.body
                    and isinstance(definition.body[-1], ast.Raise)
                    else "None"
                )
            elif has_return and not always_exits(definition.body):
                returns.add("None")
            self.return_gaps[scope] = gaps
            self.add(
                scope + ".return",
                returns,
                "return expressions",
                self.location(module, definition),
            )

    def _interfaces(self):
        for child, record in self.analysis.classes.items():
            for base in record["node"].bases:
                parents = self.analysis.resolve(
                    base, record["module"], record["module"]
                )
                for parent in parents & self.analysis.classes.keys():
                    for method in self.analysis.classes[parent]["node"].body:
                        if not isinstance(
                            method, (ast.FunctionDef, ast.AsyncFunctionDef)
                        ):
                            continue
                        implementation = self.analysis._member(
                            child, method.name, set()
                        )
                        contract = parent + "." + method.name
                        if not implementation or implementation == contract:
                            continue
                        for name in [
                            a.arg
                            for a in arguments(method)
                            if a.arg not in ("self", "cls")
                        ] + ["return"]:
                            for left, right in (
                                (contract, implementation),
                                (implementation, contract),
                            ):
                                self.add(
                                    left + "." + name,
                                    self.facts.get(right + "." + name, set()),
                                    "inherited method contract",
                                    record["path"] + ":" + str(record["line"]),
                                )

    def display(self, value):
        if value.startswith("module:"):
            return "ModuleType"
        if value.startswith("callable:"):
            slot = value[9:] + ".return"
            returns = (
                {self.overrides[slot]}
                if slot in self.overrides
                else self.facts.get(slot, set())
            )
            if returns == {"None"} and self.return_gaps.get(value[9:]):
                returns = set()
            value = (
                "Callable[..., "
                + (self.union(returns) if returns else "DynamicValue")
                + "]"
            )
        for key, record in sorted(
            self.analysis.classes.items(), key=lambda item: -len(item[0])
        ):
            value = value.replace(
                key, record["subsystem"] + "." + record["name"]
            )
        value = re.sub(r"module:[A-Za-z_][\w.]*", "ModuleType", value)
        value = re.sub(
            r"callable:[\w.<>{}@:]+", "Callable[..., DynamicValue]", value
        )
        value = re.sub(r"type:([\w.]+)", r"type[\1]", value)
        return value

    def get(self, slot):
        value = self.overrides.get(slot)
        status = (
            "declared"
            if any("declared" in e for e in self.evidence[slot])
            else "reconstructed"
        )
        if not value:
            facts = self.facts.get(slot, set())
            value = self.union(facts)
            if not facts:
                status = "unresolved"
        if (
            value == "None"
            and slot.endswith(".return")
            and self.return_gaps.get(slot[:-7])
        ):
            value, status = "DynamicValue", "unresolved"
        elif (
            slot.endswith(".return")
            and slot not in self.overrides
            and self.return_gaps.get(slot[:-7])
        ):
            value += " | DynamicValue"
        if (
            value == "None"
            and slot in self.nodes
            and slot not in self.overrides
        ):
            value, status = "DynamicValue | None", "partially reconstructed"
        if "DynamicValue" in value and status != "declared":
            status = (
                "partially reconstructed"
                if value != "DynamicValue"
                else "unresolved"
            )
        if status in ("unresolved", "partially reconstructed"):
            item = {
                "slot": slot,
                "reason": (
                    "No narrower static contract established; DynamicValue "
                    "means object, not a verified domain type."
                ),
                "location": self.locations.get(slot),
            }
            if item not in self.review:
                self.review.append(item)
        rendered = self.display(value)
        if len(rendered) > 80:
            parts = slot.split(".")
            name = (
                (parts[-2] + "_result") if parts[-1] == "return" else parts[-1]
            )
            alias = (
                "".join(
                    word.capitalize() for word in name.strip("_").split("_")
                )
                or "ValueContract"
            )
            if alias in self.aliases and self.aliases[alias] != rendered:
                alias = (
                    "".join(word.capitalize() for word in parts[-3].split("_"))
                    + alias
                )
            self.aliases[alias] = rendered
            rendered = alias
        return {
            "type": rendered,
            "status": status,
            "evidence": sorted(self.evidence.get(slot, set())),
        }

    def report(self):
        return {
            "aliases": self.aliases,
            "iterations": self.iterations,
            "facts": {
                slot: self.get(slot)
                for slot in sorted(set(self.facts) | set(self.nodes))
                if not slot.endswith((".self", ".cls"))
            },
            "review_queue": self.review,
        }
