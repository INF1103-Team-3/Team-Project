"""Complete declared-member inventory for presentation UML (no imports)."""

import ast

from uml_analysis import text, visibility
from uml_types import fields as assigned_fields


def display_name(name):
    """Keep protocol names; use UML signs for Python non-public prefixes."""
    return (
        name
        if name.startswith("__") and name.endswith("__")
        else name.lstrip("_")
    )


def targets(node):
    if isinstance(node, ast.Assign):
        return node.targets
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return [node.target]
    return []


def literal_type(value):
    if isinstance(value, ast.Constant) and value.value is not None:
        return type(value.value).__name__
    for kind, name in (
        (ast.Dict, "dict"),
        (ast.List, "list"),
        (ast.Tuple, "tuple"),
        (ast.Set, "set"),
        (ast.DictComp, "dict"),
        (ast.ListComp, "list"),
        (ast.SetComp, "set"),
    ):
        if isinstance(value, kind):
            return name
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        if value.func.id in (
            "dict",
            "list",
            "tuple",
            "set",
            "str",
            "int",
            "float",
            "bool",
        ):
            return value.func.id
    return "?"


def signature(node, reconstruction=None, scope=None):
    """Preserve defaults, positional-only, keyword-only and variadic args."""
    args = node.args

    def dtype(arg):
        if reconstruction is not None and scope:
            return reconstruction.get(scope + "." + arg.arg)["type"]
        return text(arg.annotation)

    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + args.defaults
    parts = []
    for index, (arg, default) in enumerate(zip(positional, defaults)):
        if arg.arg not in ("self", "cls"):
            item = arg.arg + ": " + dtype(arg)
            if default is not None:
                item += " = " + text(default)
            parts.append(item)
        if args.posonlyargs and index + 1 == len(args.posonlyargs):
            parts.append("/")
    if args.vararg:
        parts.append("*" + args.vararg.arg + ": " + dtype(args.vararg))
    elif args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        item = arg.arg + ": " + dtype(arg)
        if default is not None:
            item += " = " + text(default)
        parts.append(item)
    if args.kwarg:
        parts.append("**" + args.kwarg.arg + ": " + dtype(args.kwarg))
    result = text(node.returns)
    if reconstruction is not None and scope:
        result = reconstruction.get(scope + ".return")["type"]
    if node.name == "__init__" and node.returns is None:
        result = "None"
    decorators = [text(d) for d in node.decorator_list]
    flags = [
        label
        for decorator, label in (
            ("staticmethod", "static"),
            ("classmethod", "class"),
            ("abstractmethod", "abstract"),
        )
        if decorator in decorators
    ]
    if isinstance(node, ast.AsyncFunctionDef):
        flags.append("async")
    suffix = " {" + ", ".join(flags) + "}" if flags else ""
    return (
        visibility(node.name)
        + " "
        + display_name(node.name)
        + "("
        + ", ".join(parts)
        + "): "
        + result
        + suffix
    )


def members(record, reconstruction=None):
    "Include tuple targets, class fields, properties and dynamic allowlists."
    node = record["node"]
    owner = record["module"] + "." + record["name"]
    attributes, methods, declarations = {}, [], []
    properties = {}
    for member in node.body:
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = owner + "." + member.name
            decorators = [text(d) for d in member.decorator_list]
            is_property = "property" in decorators
            setter = next(
                (d for d in decorators if d.endswith(".setter")), None
            )
            if is_property or setter:
                name = member.name
                prop = properties.setdefault(
                    name, {"type": "?", "readonly": True}
                )
                if member.returns:
                    prop["type"] = text(member.returns)
                if setter:
                    prop["readonly"] = False
            else:
                methods.append(
                    {
                        "name": member.name,
                        "text": signature(member, reconstruction, scope),
                        "line": member.lineno,
                    }
                )
            declarations.append(
                {
                    "name": member.name,
                    "line": member.lineno,
                    "decorators": decorators,
                    "signature": signature(member, reconstruction, scope),
                }
            )
            for assignment in ast.walk(member):
                for target in targets(assignment):
                    for field, value in assigned_fields(
                        target, getattr(assignment, "value", None)
                    ):
                        if (
                            isinstance(field, ast.Attribute)
                            and isinstance(field.value, ast.Name)
                            and field.value.id in ("self", "cls")
                        ):
                            dtype = (
                                text(assignment.annotation)
                                if isinstance(assignment, ast.AnnAssign)
                                else literal_type(value)
                            )
                            entry = attributes.setdefault(
                                field.attr,
                                {
                                    "type": dtype,
                                    "line": assignment.lineno,
                                    "flags": [],
                                },
                            )
                            if entry["type"] == "?" and dtype != "?":
                                entry["type"] = dtype
            # MuisListing exposes precisely these dynamic read-only attributes.
            if member.name == "__getattr__":
                for item in ast.walk(member):
                    if (
                        isinstance(item, ast.Compare)
                        and isinstance(item.left, ast.Name)
                        and item.left.id == "name"
                        and len(item.ops) == 1
                        and isinstance(item.ops[0], ast.In)
                    ):
                        values = item.comparators[0]
                        if isinstance(values, (ast.Set, ast.Tuple, ast.List)):
                            for field in values.elts:
                                if isinstance(
                                    field, ast.Constant
                                ) and isinstance(field.value, str):
                                    attributes.setdefault(
                                        field.value,
                                        {
                                            "type": "?",
                                            "line": field.lineno,
                                            "flags": ["dynamic", "readOnly"],
                                        },
                                    )
        else:
            for target in targets(member):
                for field in ast.walk(target):
                    if isinstance(field, ast.Name):
                        attributes[field.id] = {
                            "type": text(member.annotation)
                            if isinstance(member, ast.AnnAssign)
                            else literal_type(getattr(member, "value", None)),
                            "line": member.lineno,
                            "flags": ["class"],
                        }
    for name, prop in properties.items():
        flags = ["property"] + (["readOnly"] if prop["readonly"] else [])
        attributes[name] = {
            "type": prop["type"],
            "line": next(
                m.lineno
                for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                and m.name == name
            ),
            "flags": flags,
        }
    fields = []
    for name, value in sorted(attributes.items()):
        typing = None
        if reconstruction is not None:
            slot = (
                owner + "." + name + (".return" if name in properties else "")
            )
            typing = reconstruction.get(slot)
            if typing["type"] == "DynamicValue" and value["type"] != "?":
                typing = {
                    "type": value["type"],
                    "status": "declared or literal",
                    "evidence": [record["path"] + ":" + str(value["line"])],
                }
            value["type"] = typing["type"]
        flags = (
            " {" + ", ".join(value["flags"]) + "}" if value["flags"] else ""
        )
        fields.append(
            {
                "name": name,
                "text": visibility(name)
                + " "
                + display_name(name)
                + ": "
                + value["type"]
                + flags,
                **value,
                **({"typing": typing} if typing else {}),
            }
        )
    return {
        "attributes": fields,
        "methods": methods,
        "declarations": declarations,
        "bases": [text(base) for base in node.bases],
    }
