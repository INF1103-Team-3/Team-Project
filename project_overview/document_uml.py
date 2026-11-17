"""Generate complete member detail sheets and compact Word overview figures.

Source analysis suggests collaborators, never exclusive ownership. Only the
reviewed ownership cases below receive diamonds; uncertain links are ordinary
associations. Outputs are local and never require application imports.
"""

import ast
from collections import defaultdict
import json
import os
from pathlib import Path
import re

from uml_members import members, signature
from uml_types import TypeReconstruction, arguments, fields
from uml_document_rendering import Sheet, HEIGHT, LINE

ROOT = Path(__file__).resolve().parents[1]
WORKFILES = Path(
    os.getenv("BITEFINDER_WORKFILES", ROOT.parent / "bitefinder-workfiles")
)
OUTPUT = WORKFILES / "uml" / "document"


def artifact_relative_path(name):
    """Use the same report categories for every generated file format."""
    suffix = Path(name).suffix[1:]
    category = {"A": "Appendix", "F": "Functions", "M": "Managers"}.get(
        name.split("_", 1)[0]
    )
    return Path(suffix) / category / name if category else Path(suffix) / name


def png_relative_path(name):
    """Resolve a PNG sheet ID for index links and class-sheet checks."""
    return artifact_relative_path(
        name if name.endswith(".png") else name + ".png"
    )


def organize_artifacts(output, replace=False):
    """Keep rendered/source formats separate within one portable bundle."""
    output = Path(output)
    for suffix in ("png", "svg", "mmd", "json"):
        folder = output / suffix
        folder.mkdir(parents=True, exist_ok=True)
        for category in ("Appendix", "Functions", "Managers"):
            (folder / category).mkdir(exist_ok=True)
        for source in sorted(output.rglob("*." + suffix)):
            target = output / artifact_relative_path(source.name)
            if source == target:
                continue
            if target.exists() and not replace:
                if source.read_bytes() != target.read_bytes():
                    raise ValueError(f"Conflicting UML artifacts: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)


MANAGERS = {
    "BIS": [
        "BIS.classes.io.cli.io_manager.IOManager",
        "BIS.classes.ai.ai_manager.AIManager",
        "BIS.classes.logic.logic_manager.LogicManager",
        "BIS.classes.data.data_manager.DataManager",
    ],
    "BRNS": [
        "BRNS.classes.io.adapters.io_manager.IOManager",
        "BRNS.classes.ai.ai_manager.AIManager",
        "BRNS.classes.logic.logic_manager.LogicManager",
        "BRNS.classes.data.data_manager.DataManager",
    ],
    "BRC": [
        "BRC.classes.io.console.io_manager.IOManager",
        "BRC.classes.ai.ai_manager.AIManager",
        "BRC.classes.logic.logic_manager.LogicManager",
        "BRC.classes.data.data_manager.DataManager",
    ],
}
OVERVIEW = [
    "BIS.classes.io.web.web_io_manager.WebIOManager",
    "BIS.classes.services.web.bis_application_service.BISApplicationService",
    (
        "BIS.classes.services.cli.search_results_controller.SearchResu"
        "ltsController"
    ),
    "BRNS.classes.services.gateway.brns_service.BRNSService",
    (
        "BRNS.classes.services.workflows.brns_recommendation_workflow."
        "BRNSRecommendationWorkflow"
    ),
    (
        "BRNS.classes.services.workflows.halal_verification_coordinato"
        "r.HalalVerificationCoordinator"
    ),
    (
        "BRNS.classes.io.gateways.verification.brc_restaurant_checker_"
        "adapter.BRCRestaurantCheckerAdapter"
    ),
    "BRC.classes.io.http.client.brc_http_client.BRCHTTPClient",
    "BRC.classes.io.http.server.brc_http_handler.BRCRequestHandler",
    "BRC.classes.services.brc_application.BRCApplication",
]
COORDINATORS = {
    "BIS": "BIS.classes.services.cli.bis_search_workflow.BISSearchWorkflow",
    "BRNS": (
        "BRNS.classes.services.workflows.brns_recommendation_workflow."
        "BRNSRecommendationWorkflow"
    ),
    "BRC": "BRC.classes.services.brc_application.BRCApplication",
}
# Reviewed constructor-owned helpers, not simply any ``self.x = NewThing()``.
OWNED = {
    ("BIS.classes.io.cli.io_manager.IOManager", "_wish_collector"),
    ("BIS.classes.logic.logic_manager.LogicManager", "_profile_access"),
    (
        "BIS.classes.services.web.bis_chatbot_service.BISChatbotService",
        "_presenter",
    ),
    (
        "BIS.classes.services.web.bis_chatbot_service.BISChatbotService",
        "_parser",
    ),
    (
        (
            "BRC.classes.ai.providers.fallback.fallback_ai_client.Fall"
            "backAIClient"
        ),
        "_router",
    ),
}
KINDS = {
    "inherits": "generalisation",
    "implements": "realisation",
    "creates": "dependency",
    "calls": "dependency",
    "http": "dependency",
}


def reviewed_relations(analysis):
    groups = {}
    for source, target, raw, label, evidence in sorted(analysis.edges):
        kind = KINDS.get(raw, raw)
        multiplicity = {}
        field = label.removesuffix(" (default)")
        note = "Source-evidenced dependency; no lifecycle claim."
        if raw == "composition":
            if (source, field) in OWNED or (
                source == MANAGERS["BRC"][3] and target.endswith(".JsonFile")
            ):
                kind = "composition"
                multiplicity = {
                    "from_multiplicity": "1",
                    "to_multiplicity": "1",
                }
                note = (
                    "Reviewed: constructed by this owner and managed a"
                    "s its helper."
                )
            else:
                kind = "association"
                note = (
                    "Construction is observed; exclusive ownership is "
                    "not proven (injection may replace defaults)."
                )
        elif raw == "aggregation":
            if source.endswith((".AIProviderRouter", ".ResultSorterRegistry")):
                multiplicity = {
                    "from_multiplicity": "0..*",
                    "to_multiplicity": "0..*",
                }
                note = (
                    "Caller-supplied collection; empty membership and "
                    "shared independent parts are permitted."
                )
            else:
                kind = "association"
                note = (
                    "Collection inference alone does not establish UML"
                    " aggregation."
                )
        if raw == "http":
            label = "HTTP /check and /status (when BRC_SERVICE_URL is set)"
        if source == OVERVIEW[6] and target == OVERVIEW[9] and raw == "calls":
            label = "CLI/in-process fallback when BRC_SERVICE_URL is absent"
        key = source, target, kind
        relation = groups.setdefault(
            key,
            {
                "from": source,
                "to": target,
                "kind": kind,
                "labels": [],
                "evidence": [],
                "review": note,
                **multiplicity,
            },
        )
        if label not in relation["labels"] and label:
            relation["labels"].append(label)
        relation["evidence"].append(evidence)
    # Tuple assignments are not followed by the legacy inference pass. This
    # declared collaborator and the handler bootstrap are manually traced.
    extra = [
        (
            OVERVIEW[0],
            OVERVIEW[1],
            "association",
            "_application",
            "BIS/classes/io/web/web_io_manager.py",
            "self._auth, self._application",
        ),
        (
            OVERVIEW[8],
            OVERVIEW[9],
            "dependency",
            "application_run -> brc_main.run -> run_once",
            "BRC/classes/io/http/server/brc_http_handler.py",
            "application_run =",
        ),
        (
            COORDINATORS["BRC"],
            MANAGERS["BRC"][1],
            "association",
            "_ai / default_ai()",
            "BRC/classes/services/brc_application.py",
            "self._ai =",
        ),
    ]
    for source, target, kind, label, path, anchor in extra:
        if source not in analysis.classes or target not in analysis.classes:
            continue
        lines = (analysis.root / path).read_text().splitlines()
        line = next(i for i, value in enumerate(lines, 1) if anchor in value)
        groups[source, target, kind] = {
            "from": source,
            "to": target,
            "kind": kind,
            "labels": [label],
            "evidence": [f"{path}:{line}"],
            "review": (
                "Manually traced current constructor/bootstrap and its"
                " callers."
            ),
        }
    for relation in groups.values():
        if (relation["from"], relation["to"]) in {
            (OVERVIEW[1], OVERVIEW[3]),
            (OVERVIEW[3], OVERVIEW[4]),
            (OVERVIEW[5], OVERVIEW[6]),
        } and relation["kind"] == "association":
            relation["directed"] = True
            relation["review"] += (
                " Stored field establishes source-to-target navigability."
            )
        if (
            relation["kind"] == "composition"
            and relation["from"] == MANAGERS["BRC"][3]
        ):
            relation["to_multiplicity"] = str(len(relation["labels"]))
        if (
            relation["kind"] == "association"
            and relation["from"] in COORDINATORS.values()
            and relation["to"] in sum(MANAGERS.values(), [])
        ):
            relation.update(from_multiplicity="0..*", to_multiplicity="1")
            relation["review"] += (
                " Cardinality describes configured working manager"
                "s; injected managers can be shared."
            )
    # A stored reference already explains the collaboration. Do not overlay a
    # second dashed call arrow on the same pair unless it is HTTP.
    result = [
        r
        for r in groups.values()
        if not (
            r["kind"] == "dependency"
            and not any("HTTP" in x for x in r["labels"])
            and any(
                k[0] == r["from"] and k[1] == r["to"] and k[2] != "dependency"
                for k in groups
            )
        )
    ]
    # A same-class method call or factory return is not a reflexive object
    # association. Require a stored, explicitly self-typed instance reference.
    for owner, record in analysis.classes.items():
        for method in record["node"].body:
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            typed = {}
            for arg in arguments(method):
                annotation = arg.annotation
                if isinstance(annotation, ast.Constant) and isinstance(
                    annotation.value, str
                ):
                    annotation = ast.parse(annotation.value, mode="eval").body
                if annotation is None:
                    continue
                if any(
                    isinstance(n, ast.Name) and n.id in ("Callable", "type")
                    for n in ast.walk(annotation)
                ):
                    continue
                if any(
                    isinstance(n, ast.Name) and n.id == record["name"]
                    for n in ast.walk(annotation)
                ):
                    typed[arg.arg] = annotation
            for node in analysis.scoped_nodes(method):
                target_list = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else [node.target]
                    if isinstance(node, ast.AnnAssign)
                    else []
                )
                for target in target_list:
                    for field, value in fields(
                        target, getattr(node, "value", None)
                    ):
                        if (
                            isinstance(field, ast.Attribute)
                            and isinstance(field.value, ast.Name)
                            and field.value.id == "self"
                            and isinstance(value, ast.Name)
                            and value.id in typed
                        ):
                            result.append(
                                {
                                    "from": owner,
                                    "to": owner,
                                    "kind": "association",
                                    "directed": True,
                                    "reflexive": True,
                                    "labels": [field.attr],
                                    "evidence": [
                                        record["path"] + ":" + str(node.lineno)
                                    ],
                                    "review": (
                                        "Stores an explicitly self-typed "
                                        "instance reference; not recursion."
                                    ),
                                }
                            )
    return result


def slug(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value)


def group_name(key):
    parts = key.split(".")
    if ".support.email_verification." in key:
        return "BIS_email_verification"
    if ".classes." in key:
        index = parts.index("classes")
        # Use real architectural packages, not alphabetical class columns.
        tail = parts[index + 1: -2]
        return "_".join(parts[:1] + tail[:2])
    return parts[0] + "_models_and_support"


def inventory(analysis):
    reconstruction = TypeReconstruction(analysis)
    analysis.uml_types = reconstruction
    result = {}
    for key, record in sorted(analysis.classes.items()):
        result[key] = {
            "name": record["name"],
            "module": record["module"],
            "subsystem": record["subsystem"],
            "path": record["path"],
            "line": record["line"],
            "abstract": record["abstract"],
            **members(record, reconstruction),
        }
        for category in ("attributes", "methods"):
            for entry in result[key][category]:
                entry["diagram_text"] = expanded_types(
                    entry["text"], reconstruction.aliases
                )
    return result


def expanded_types(value, aliases):
    """Make displayed signatures readable without an external type glossary."""
    for _ in range(4):
        updated = re.sub(
            r"(?<![\w.])[A-Za-z_]\w*\b",
            lambda match: aliases.get(match.group(), match.group()),
            value,
        )
        if updated == value:
            break
        value = updated
    return value


def diagram_text(entry):
    return entry.get("diagram_text", entry["text"])


def summary_member(entry, operation=False):
    """Explicit overview projection; full signatures stay on class sheets."""
    value = diagram_text(entry)
    if operation:
        start, depth, finish = value.find("("), 0, None
        for position in range(start, len(value)):
            depth += value[position] == "("
            depth -= value[position] == ")"
            if not depth:
                finish = position
                break
        if finish is not None:
            value = (
                value[: start + 1]
                + ("..." if finish > start + 1 else "")
                + value[finish:]
            )
    # Overview types retain the actual container kind, omitting generic detail.
    result, depth = [], 0
    for char in value:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif not depth:
            result.append(char)
    value = "".join(result)
    value = value.replace("DynamicValue", "object")
    value = re.sub(r"\{[^}]+\}", "", value).strip()
    prefix, separator, dtype = value.rpartition(": ")
    if separator:
        value = (
            prefix
            + separator
            + " | ".join(
                dict.fromkeys(part.strip() for part in dtype.split("|"))
            )
        )
    return value


def class_title(record):
    role = (
        "interface"
        if record["name"].endswith("Interface")
        else "abstract"
        if record["abstract"]
        else "class"
    )
    title = [record["name"], "<<" + role + ">>"]
    if record["bases"]:
        title.append("bases: " + ", ".join(record["bases"]))
    return title


def related(key, relations, limit=3):
    priority = {
        "generalisation": 0,
        "realisation": 1,
        "composition": 2,
        "aggregation": 3,
        "association": 4,
        "dependency": 5,
    }
    candidates = sorted(
        (r for r in relations if key in (r["from"], r["to"])),
        key=lambda r: (
            priority[r["kind"]],
            r["from"] != key,
            r["to"],
            r["from"],
        ),
    )
    chosen, neighbors = [], set()
    for relation in candidates:
        other = relation["to"] if relation["from"] == key else relation["from"]
        if other == key or other in neighbors:
            continue
        neighbors.add(other)
        chosen.append(relation)
        if len(chosen) == limit:
            break
    return chosen


def selected_members(record):
    preferences = {
        "WebIOManager": ("_application", "search"),
        "BISApplicationService": ("_brns", "search"),
        "SearchResultsController": ("_brns", "run"),
        "BRNSService": ("_workflow", "search"),
        "BRNSRecommendationWorkflow": ("_ai", "search"),
        "HalalVerificationCoordinator": ("_verifier", "verify"),
        "BRCRestaurantCheckerAdapter": ("_checker", "verify_batch"),
        "BRCHTTPClient": ("_base_url", "verify_batch"),
        "BRCRequestHandler": ("_check_lock", "do_POST"),
        "BRCApplication": ("_data", "run"),
        "BISSearchWorkflow": ("_ai", "run"),
    }
    attribute, method = preferences.get(record["name"], (None, None))
    manager_methods = {
        ("BIS", "IOManager"): "collect_search",
        ("BIS", "AIManager"): "process",
        ("BIS", "LogicManager"): "validate_search_request",
        ("BIS", "DataManager"): "save_preferences",
        ("BRNS", "IOManager"): "accept_bis_json",
        ("BRNS", "AIManager"): "recommend_prepared",
        ("BRNS", "LogicManager"): "rank_restaurants",
        ("BRNS", "DataManager"): "save_search_results",
        ("BRC", "AIManager"): "tag_batch",
        ("BRC", "IOManager"): "read_json_input",
        ("BRC", "LogicManager"): "check_restaurants",
        ("BRC", "DataManager"): "load_clean_database",
    }
    method = manager_methods.get((record["subsystem"], record["name"]), method)
    attributes = sorted(
        record["attributes"],
        key=lambda a: (a["name"] != attribute, len(summary_member(a))),
    )[:1]
    candidates = [m for m in record["methods"]
                  if not m["name"].startswith("_")]
    if not candidates:
        candidates = [m for m in record["methods"]
                      if m["name"] != "__init__"]
    methods = sorted(
        candidates,
        key=lambda m: (m["name"] != method, len(summary_member(m, True))),
    )[:1]
    return attributes, methods


def context_box(sheet, key, records, index, x, y, width=900):
    record = records[key]
    attributes, methods = selected_members(record)
    title = [record["subsystem"] + "::" + record["name"]]
    if record["name"].endswith("Interface"):
        title.append("<<interface>>")
    elif record["abstract"]:
        title.append("<<abstract>>")
    sheet.box(
        key,
        title,
        [
            [summary_member(a) for a in attributes] or ["(no attributes)"],
            [summary_member(m, True) for m in methods] or ["(no operations)"],
        ],
        (x, y, width),
        record["subsystem"],
        context=True,
    )


def member_chunks(record, measure):
    """Continue a class across sheets without suppressing any member."""
    chunks, current, lines = [], [], 0
    entries = [("attributes", entry) for entry in record["attributes"]] + [
        ("methods", entry) for entry in record["methods"]
    ]
    for category, entry in entries:
        count = len(measure.wrapped(diagram_text(entry), 1920))
        if current and lines + count > 26:
            chunks.append(current)
            current, lines = [], 0
        current.append((category, entry))
        lines += count
    if current or not entries:
        chunks.append(current)
    return chunks


def detail_sheet(
    key,
    entries,
    part,
    total,
    sheet_id,
    records,
    relations,
    index,
    output,
    font,
):
    record = records[key]
    title = (
        f"{sheet_id} | {record['subsystem']} {record['name']} ({part}/{total})"
    )
    sheet = Sheet(
        title,
        (
            "Complete declared members across this class's numbered co"
            "ntinuation sheets; neighboring classes show selected members."
        ),
        font,
    )
    attributes = [
        diagram_text(entry)
        for category, entry in entries
        if category == "attributes"
    ]
    methods = [
        diagram_text(entry)
        for category, entry in entries
        if category == "methods"
    ]
    sheet.box(
        key,
        class_title(record),
        [
            attributes or ["(no attributes on this sheet)"],
            methods or ["(no operations on this sheet)"],
        ],
        (75, 225, 1920),
        record["subsystem"],
    )
    links = related(key, relations)
    for number, relation in enumerate(links, 1):
        other = relation["to"] if relation["from"] == key else relation["from"]
        context_box(
            sheet, other, records, index, 2220, 250 + (number - 1) * 555, 890
        )
        sheet.relation(relation)
    sheet.footer(
        [
            "+ public; # protected; - private. Any: unconstrained value; "
            "object: unresolved dynamic contract.",
            (
                "Attributes and operations occupy separate compartments. "
                "Neighbors show selected members; (...) omits parameters."
            ),
            "Solid hollow triangle: base; dashed hollow triangle: interface. "
            "Hollow/filled diamond at whole: aggregation/composition; "
            "dotted: association; dashed open arrow: dependency.",
        ]
    )
    sheet.save(output / sheet_id)
    # Keep raw names and unwrapped signatures, plus all relationships, for
    # exact checking even when only three important links fit the image.
    data = {
        "id": sheet_id,
        "focus": key,
        "part": part,
        "total_parts": total,
        "members": [
            {"category": category, **entry} for category, entry in entries
        ],
        "displayed_relations": links,
    }
    (output / (sheet_id + ".json")).write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    return data


def small_height(key, records, measure):
    record = records[key]
    entries = record["attributes"] + record["methods"]
    count = sum(
        len(measure.wrapped(diagram_text(entry), 1450)) for entry in entries
    )
    # The renderer wraps all three compartments independently.
    title = sum(
        len(measure.wrapped(line, 1450)) for line in class_title(record)
    )
    attributes = (
        sum(
            len(measure.wrapped(diagram_text(e), 1450))
            for e in record["attributes"]
        )
        or 1
    )
    methods = (
        sum(
            len(measure.wrapped(diagram_text(e), 1450))
            for e in record["methods"]
        )
        or 1
    )
    return (title + attributes + methods) * LINE + 84, count


def grouped_plans(keys, records, measure):
    """Pack related small focal classes; long classes retain detail sheets."""
    plans, page, cursors = [], [], [225, 225]
    for key in keys:
        height, _ = small_height(key, records, measure)
        column = min(range(2), key=lambda c: cursors[c])
        if cursors[column] + height > HEIGHT - 230:
            plans.append(page)
            page, cursors, column = [], [225, 225], 0
        page.append((key, 75 + column * 1600, cursors[column]))
        cursors[column] += height + 80
    if page:
        plans.append(page)
    return plans


def grouped_sheet(
    identifier, positions, records, relations, index, output, font
):
    sheet = Sheet(
        identifier.replace("_", " "),
        (
            "Full locally declared attributes and operations, "
            "grouped by source package; inherited members belong to their "
            "bases."
        ),
        font,
    )
    page_members = []
    keys = [key for key, _, _ in positions]
    for key, x, y in positions:
        record = records[key]
        sheet.box(
            key,
            class_title(record),
            [
                [diagram_text(e) for e in record["attributes"]]
                or ["(no declared attributes)"],
                [diagram_text(e) for e in record["methods"]]
                or ["(no declared operations)"],
            ],
            (x, y, 1450),
            record["subsystem"],
        )
        for category in ("attributes", "methods"):
            page_members += [
                {"class": key, "category": category, **entry}
                for entry in record[category]
            ]
    chosen = []
    for relation in relations:
        if relation["from"] not in keys or relation["to"] not in keys:
            continue
        # In-page structural links only; crowded call graphs stay in the model.
        if relation["kind"] not in (
            "generalisation",
            "realisation",
            "aggregation",
            "composition",
        ):
            continue
        chosen.append(relation)
        sheet.relation(relation)
    sheet.footer(
        [
            "+ public; # protected; - private. Any: unconstrained value; "
            "object: unresolved dynamic contract.",
            (
                "All locally declared members are shown. "
                "{abstract}, {static}, {class} and {property} describe Python "
                "declarations."
            ),
            (
                "Solid hollow triangle = parent; dashed hollow triangl"
                "e = interface; diamond is at the whole end."
            ),
        ]
    )
    sheet.save(output / identifier)
    data = {
        "id": identifier,
        "focus": keys,
        "members": page_members,
        "displayed_relations": chosen,
    }
    (output / (identifier + ".json")).write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    return data


def overview_sheet(records, relations, index, output, font):
    sheet = Sheet(
        "01 | BiteFinder interaction overview",
        (
            "User <-> web page <-> BIS /api; CLI also enters BIS. "
            "Selected attributes and operations show subsystem collaboration."
        ),
        font,
    )
    for subsystem, x in (("BIS", 80), ("BRNS", 1120), ("BRC", 2160)):
        for row, key in enumerate(
            k for k in OVERVIEW if records[k]["subsystem"] == subsystem
        ):
            context_box(sheet, key, records, index, x, 205 + row * 440, 920)
    chosen = [
        r for r in relations if r["from"] in OVERVIEW and r["to"] in OVERVIEW
    ]
    for number, relation in enumerate(chosen, 1):
        sheet.relation(relation)
    sheet.footer(
        [
            (
                "Dotted association; open arrow = navigability; "
                "dashed arrow = "
                "use/HTTP. "
                "Package labels show code ownership; the HTTP client runs in "
                "BRNS."
            ),
            (
                "HTTP client -> handler: /check and /status. "
                "Adapter -> BRCApplication: in-process fallback when no "
                "service URL is set."
            ),
            (
                "+ public; # protected; - private. (...) omits parameters; "
                "generic container arguments and other members are omitted in "
                "this overview. "
                "object = unresolved dynamic type."
            ),
        ]
    )
    sheet.save(output / "01_overview")
    return chosen


def notation_sheet(output, font):
    """Use the supplied UML reference's actual geometric endpoint symbols."""
    sheet = Sheet(
        "UML relationship notation",
        "Symbol key with real BiteFinder examples; "
        "this is not an additional class diagram.",
        font,
    )
    examples = [
        ("Inheritance", "RatingResultSorter", "BaseResultSorter", "triangle"),
        ("Realisation", "AIManager (BIS)", "ChatAIInterface", "realisation"),
        ("Association", "BRNSService", "BRNSRecommendationWorkflow", None),
        (
            "Directed assoc.",
            "BISApplicationService",
            "BRNSService",
            "directed",
        ),
        ("Composition", "IOManager (BIS)", "SearchWishCollector", "filled"),
        (
            "Aggregation",
            "ResultSorterRegistry",
            "RatingResultSorter",
            "hollow",
        ),
    ]
    for row, (label, source, target, marker) in enumerate(examples):
        y = 330 + row * 280
        sheet.text((75, y - 20), label)
        sheet.text((800, y - 90), source)
        sheet.text((2180, y - 20), target)
        sheet.line(
            [(1260, y), (2110, y)],
            dotted=label in ("Association", "Directed assoc."),
            dashed=marker == "realisation",
        )
        if marker in ("triangle", "realisation"):
            sheet.marker((2110, y), (1260, y), "triangle")
        elif marker == "directed":
            sheet.marker((2110, y), (1260, y), "arrow")
        elif marker:
            sheet.marker((1260, y), (2110, y), marker)
    sheet.footer(
        [
            "Hollow triangle points to the parent. "
            "Filled/hollow diamonds sit at the whole/owner end.",
            "Association is dotted, following the requested coursework "
            "convention, with no arrowhead or diamond.",
            "Interface realisation: dashed hollow triangle. "
            "Temporary use/HTTP: dashed open arrow.",
        ]
    )
    sheet.save(output / "00_relationship_notation")


def core_sheet(subsystem, number, records, relations, index, output, font):
    sheet = Sheet(
        f"0{number} | {subsystem} four-manager architecture",
        (
            "Selected manager and workflow members. "
            "Input -> IO -> AI -> Logic -> Data; connectors show actual "
            "collaborations."
        ),
        font,
    )
    coordinator = COORDINATORS[subsystem]
    context_box(sheet, coordinator, records, index, 1120, 240, 920)
    keys = [coordinator] + MANAGERS[subsystem]
    roles = ["IO", "AI", "Logic", "Data"]
    for col, (role, key) in enumerate(zip(roles, MANAGERS[subsystem])):
        context_box(sheet, key, records, index, 75 + col * 780, 1250, 705)
    if subsystem == "BIS":
        extra = [OVERVIEW[0], OVERVIEW[1]]
    elif subsystem == "BRNS":
        extra = [OVERVIEW[3], OVERVIEW[5]]
    else:
        extra = [
            (
                "BRC.classes.services.workflows.contracts.base_brc_wor"
                "kflow.BaseBRCWorkflow"
            )
        ]
    for row, key in enumerate(extra):
        context_box(sheet, key, records, index, 80 + row * 2080, 700, 920)
        keys.append(key)
    chosen = [r for r in relations if r["from"] in keys and r["to"] in keys]
    for edge, relation in enumerate(chosen, 1):
        sheet.relation(relation)
    sheet.footer(
        [
            (
                "IO -> AI -> Logic -> Data describes orchestration ord"
                "er; these connectors show actual object relationships"
                "."
            ),
            (
                "Dotted association; dashed use/dependency; hollow triangle "
                "points to a base"
                "(solid) or interface (dashed). Diamonds at the whole: hollow "
                "aggregation, filled composition."
            ),
            "+ public; # protected; - private. (...) omits parameters; "
            "container type arguments and other members are omitted in "
            "this overview. "
            "object = unresolved dynamic type.",
        ]
    )
    name = f"0{number}_{subsystem}_core"
    sheet.save(output / name)
    return name, chosen


def function_sheets(analysis, output, font):
    """Standalone functions remain module boxes, never imaginary classes."""
    created = []
    for module, (tree, path) in sorted(analysis.modules.items()):
        operations = [
            expanded_types(
                signature(node, analysis.uml_types, module + "." + node.name),
                analysis.uml_types.aliases,
            )
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if not operations:
            continue
        probe = Sheet("probe", "probe", font)
        pages, current, lines = [], [], 0
        for operation in operations:
            size = len(probe.wrapped(operation, 3000))
            if current and lines + size > 27:
                pages.append(current)
                current, lines = [], 0
            current.append(operation)
            lines += size
        if current:
            pages.append(current)
        for part, lines in enumerate(pages, 1):
            name = "F_" + slug(module) + f"_{part:02}"
            sheet = Sheet(
                name.replace("_", " "),
                (
                    "Module/function appendix: these boxes represent m"
                    "odules, not production classes."
                ),
                font,
            )
            sheet.box(
                module,
                ["<<module>> " + module],
                [["Source: " + path], lines],
                (75, 225, 3000),
            )
            sheet.footer(
                [
                    (
                        "Complete top-level function signatures across"
                        " numbered continuation sheets; implementation"
                        " bodies are excluded."
                    ),
                    (
                        "These are module capability inventories, not "
                        "class inheritance or runtime execution-order "
                        "diagrams."
                    ),
                    (
                        "Any: unconstrained value; object: unresolved dynamic "
                        "contract."
                        "+ public; # protected; - private."
                    ),
                ]
            )
            sheet.save(output / name)
            created.append(name)
    dependencies = [
        {
            "module": module,
            "source": path,
            "imports": sorted(
                {
                    ast.unparse(node)
                    for node in tree.body
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                }
            ),
        }
        for module, (tree, path) in sorted(analysis.modules.items())
    ]
    (output / "module_dependencies.json").write_text(
        json.dumps(dependencies, indent=2), encoding="utf-8"
    )
    created += module_dependency_sheets(analysis, output, font)
    return created


def module_dependency_sheets(analysis, output, font):
    """Draw static imports between actual function-bearing modules."""
    modules = {
        module
        for module, (tree, _) in analysis.modules.items()
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in tree.body
        )
    }
    links = set()
    for module in modules:
        for target in analysis.aliases[module].values():
            matches = [
                key
                for key in modules
                if target == key or target.startswith(key + ".")
            ]
            if matches:
                other = max(matches, key=len)
                if other != module:
                    links.add((module, other))
    created = []
    for subsystem in ("BIS", "BRNS", "BRC", "common"):
        anchors = sorted(
            module for module in modules if module.split(".")[0] == subsystem
        )
        for start in range(0, len(anchors), 5):
            selected = anchors[start: start + 5]
            neighbors = sorted(
                {target for source, target in links if source in selected}
                - set(selected)
            )
            selected += neighbors[: 10 - len(selected)]
            if not any(s in selected and t in selected for s, t in links):
                continue
            identifier = f"F_{subsystem}_module_imports_{start // 5 + 1:02}"
            sheet = Sheet(
                identifier.replace("_", " "),
                "Module dependency view: dashed arrows are static imports; "
                "these are not class relationships.",
                font,
            )
            for position, module in enumerate(selected):
                x, y = 75 + (position % 2) * 1600, 225 + (position // 2) * 340
                sheet.box(
                    module,
                    [module],
                    [["<<module>>"], ["Imports shown with dashed arrows"]],
                    (x, y, 1450),
                    module.split(".")[0],
                    context=True,
                )
            chosen = [
                {
                    "from": s,
                    "to": t,
                    "kind": "dependency",
                    "labels": ["imports"],
                    "evidence": [analysis.modules[s][1]],
                }
                for s, t in sorted(links)
                if s in selected and t in selected
            ]
            for number, relation in enumerate(chosen, 1):
                sheet.relation(relation)
            sheet.footer(
                [
                    "Boxes represent Python modules; arrows point from "
                    "the importing module to its dependency.",
                    "Only dependencies between the displayed modules "
                    "are shown.",
                    "An import is a static dependency, not runtime "
                    "execution order or HTTP access control.",
                ]
            )
            sheet.save(output / identifier)
            (output / (identifier + ".json")).write_text(
                json.dumps(chosen, indent=2), encoding="utf-8"
            )
            created.append(identifier)
    return created


def generate_document_set(analysis, output=OUTPUT, font=None):
    output = Path(output)
    default_font = WORKFILES / "tools" / "fonts" / "RobotoMono.ttf"
    font = font or (str(default_font) if default_font.is_file() else None)
    output.mkdir(parents=True, exist_ok=True)
    records = inventory(analysis)
    relations = reviewed_relations(analysis)
    missing = (
        set(
            OVERVIEW + sum(MANAGERS.values(), []) + list(COORDINATORS.values())
        )
        - records.keys()
    )
    if missing:
        raise ValueError(
            f"Reviewed class selection is stale: {sorted(missing)}"
        )
    probe = Sheet("probe", "probe", font)
    index, plan = {}, []
    grouped = defaultdict(list)
    old_model = output / "json" / "class_model.json"
    if not old_model.is_file():
        old_model = output / "class_model.json"
    old_model = (
        json.loads(old_model.read_text()) if old_model.is_file() else {}
    )
    core = set(sum(MANAGERS.values(), []))
    for key, record in records.items():
        height, count = small_height(key, records, probe)
        if key not in core and count <= 18 and height <= 1500:
            grouped[group_name(key)].append(key)
            continue
        category = (
            "M_" + record["subsystem"]
            if key in core
            else "A_" + group_name(key)
        )
        fragments = member_chunks(record, probe)
        ids = [
            category + "_" + slug(record["name"]) + f"_{n:02}"
            for n in range(1, len(fragments) + 1)
        ]
        # Module suffix prevents collisions between identically named classes.
        if any(identifier in {p[4] for p in plan} for identifier in ids):
            ids = [
                category + "_" + slug(record["module"]) + f"_{n:02}"
                for n in range(1, len(fragments) + 1)
            ]
        index[key] = ids
        for part, (entries, identifier) in enumerate(zip(fragments, ids), 1):
            plan.append((key, entries, part, len(fragments), identifier))
    grouped_pages = []
    for group, keys in sorted(grouped.items()):
        for number, positions in enumerate(
            grouped_plans(keys, records, probe), 1
        ):
            identifier = "A_" + group + f"_sheet_{number:02}"
            for key, _, _ in positions:
                index[key] = [identifier]
            grouped_pages.append((identifier, positions))
    pages = [
        detail_sheet(
            key,
            entries,
            part,
            total,
            identifier,
            records,
            relations,
            index,
            output,
            font,
        )
        for key, entries, part, total, identifier in plan
    ]
    pages += [
        grouped_sheet(
            identifier, positions, records, relations, index, output, font
        )
        for identifier, positions in grouped_pages
    ]
    overview = overview_sheet(records, relations, index, output, font)
    (output / "01_overview.relations.json").write_text(
        json.dumps(overview, indent=2), encoding="utf-8"
    )
    for number, subsystem in enumerate(MANAGERS, 2):
        name, chosen = core_sheet(
            subsystem, number, records, relations, index, output, font
        )
        (output / (name + ".relations.json")).write_text(
            json.dumps(chosen, indent=2), encoding="utf-8"
        )
    notation_sheet(output, font)
    functions = function_sheets(analysis, output, font)
    model = {
        "association_line_style": "dotted (user-requested convention)",
        "classes": records,
        "type_aliases": analysis.uml_types.aliases,
        "relations": relations,
        "index": index,
        "pages": pages,
        "function_sheets": functions,
        "limitations": [
            (
                "Source inference is not runtime execution or exclusiv"
                "e ownership proof."
            ),
            (
                "Only reviewed ownership cases use diamonds; uncertain"
                " lifetimes are associations."
            ),
            (
                "Only three important relationships fit a detail sheet"
                "; the complete source-evidenced relation model is inc"
                "luded."
            ),
            (
                "External Python/framework parents have no locally dec"
                "lared members to reproduce."
            ),
        ],
    }
    (output / "class_model.json").write_text(
        json.dumps(model, indent=2), encoding="utf-8"
    )
    (output / "type_evidence.json").write_text(
        json.dumps(analysis.uml_types.report(), indent=2), encoding="utf-8"
    )
    old_ids = {p["id"] for p in old_model.get("pages", [])} | set(
        old_model.get("function_sheets", [])
    )
    new_ids = {p["id"] for p in pages} | set(functions)
    for stale in old_ids - new_ids:
        if Path(stale).name != stale:
            raise ValueError("Unexpected generated manifest path")
        for suffix in (".png", ".svg", ".json"):
            (output / (stale + suffix)).unlink(missing_ok=True)
            (output / suffix[1:] / (stale + suffix)).unlink(missing_ok=True)
            (output / artifact_relative_path(stale + suffix)).unlink(
                missing_ok=True
            )
    (output / "analysis.json").write_text(
        json.dumps(analysis.report(), indent=2), encoding="utf-8"
    )
    text_boxes = []
    for key, record in records.items():
        groups = [
            [key],
            [diagram_text(e) for e in record["attributes"]],
            [diagram_text(e) for e in record["methods"]],
        ]
        width = max(len(line) for group in groups for line in group) + 2
        border = "+" + "-" * width + "+"
        lines = [border]
        for group in groups:
            lines.extend("| " + line.ljust(width - 2) + " |" for line in group)
            lines.append(border)
        text_boxes.append("\n".join(lines))
    (output / "class_boxes.txt").write_text(
        "\n\n".join(text_boxes) + "\n", encoding="utf-8"
    )
    overview_model = {
        "title": "BiteFinder interaction overview - context class references",
        "classes": [
            {
                "name": records[key]["name"],
                "attributes": [
                    summary_member(a)
                    for a in selected_members(records[key])[0]
                ],
                "methods": [
                    summary_member(m, True)
                    for m in selected_members(records[key])[1]
                ],
            }
            for key in OVERVIEW
        ],
        "relations": [
            {
                "from": records[r["from"]]["name"],
                "to": records[r["to"]]["name"],
                "kind": r["kind"],
                "label": " / ".join(r["labels"]).replace("->", "calls"),
                **{
                    name: r[name]
                    for name in ("from_multiplicity", "to_multiplicity")
                    if name in r
                },
            }
            for r in overview
        ],
        "notes": [
            (
                "Selected class members. (...) omits parameters; "
                "generic container arguments and other members are omitted."
            ),
            (
                "HTTP is conditional communication, not ownership or a"
                "uthentication."
            ),
        ],
    }
    (output / "overview.model.json").write_text(
        json.dumps(overview_model, indent=2), encoding="utf-8"
    )
    guide = [
        "# BiteFinder UML for Word",
        "",
        (
            "Insert the four numbered overview images in the main repo"
            "rt. Images are standalone: selected class members appear in "
            "overviews and complete declarations appear on the class sheets. "
            "The index is a local navigation aid and is never referenced "
            "inside images."
        ),
        "",
        (
            "All PNGs are 3200 x 2200 pixels at 300 DPI. Use a landsca"
            "pe section at approximately 10.5 inches wide; do not shri"
            "nk a detail page to portrait width. Matching images are in "
            "png/ and svg/; Mermaid sources are in mmd/, models in json/."
        ),
        "",
        "## Main figures",
        "",
    ]
    guide += [
        f"- [{name}.png](png/{name}.png)"
        for name in (
            "01_overview",
            "02_BIS_core",
            "03_BRNS_core",
            "04_BRC_core",
        )
    ]
    guide += [
        "",
        "[Relationship symbol key](png/00_relationship_notation.png)",
        "",
    ]
    guide += [
        "",
        "## Complete class index",
        "",
        (
            "Every focal class includes all locally declared members a"
            "cross its numbered sheets. Properties appear once in the "
            "attributes compartment, including read-only status. Const"
            "ructors and protocol methods are included. Inherited memb"
            "ers belong to the linked parent sheets; third-party paren"
            "t names are recorded in json/class_model.json. Types are "
            "reconstructed "
            "from evidence; DynamicValue marks unresolved contracts."
        ),
        "",
        "| ID | Class | Source | Full declarations | Inherits / implements |",
        "| --- | --- | --- | --- | --- |",
    ]
    for code, (key, record) in enumerate(records.items(), 1):
        links = ", ".join(
            f"[{identifier}]({png_relative_path(identifier).as_posix()})"
            for identifier in index[key]
        )
        parents = [
            r["to"]
            for r in relations
            if r["from"] == key
            and r["kind"] in ("generalisation", "realisation")
        ]
        parent_links = [
            f"[{parent}]({png_relative_path(index[parent][0]).as_posix()})"
            for parent in parents
        ]
        known_names = {records[parent]["name"] for parent in parents}
        parent_links += [
            base + " (external reference)"
            for base in record["bases"]
            if base not in known_names
        ]
        guide.append(
            f"| C{code:03} | {key} | "
            f"{record['path']}:{record['line']} | {links} | "
            f"{', '.join(parent_links)} |"
        )
    guide += [
        "",
        "## Module/function appendix",
        "",
        (
            "These supplementary images contain standalone function in"
            "ventories; they are not fictional classes."
        ),
        "",
    ]
    guide += [
        f"- [{name}]({png_relative_path(name).as_posix()})"
        for name in functions
    ]
    guide += [
        "",
        "## Relationship interpretation",
        "",
        (
            "Solid hollow triangle: generalisation. Dashed hollow tria"
            "ngle: interface realisation. Dotted line: association. Hol"
            "low diamond at the whole: aggregation. Filled diamond at "
            "the whole: composition. Dashed open arrow: use or HTTP de"
            "pendency. Cardinalities appear only where the implementat"
            "ion supports them, never on inheritance/dependencies."
        ),
        "Association uses the user's dotted-line convention; "
        "standard UML normally uses a solid association line.",
        "",
        (
            "Detail images display up to three important source-eviden"
            "ced links to avoid unreadable crossings. The complete rel"
            "ation labels, source lines and ownership review notes are"
            " in json/class_model.json and per-figure relation sidecars "
            "for local "
            "review; the submitted images do not depend on these files."
        ),
        "",
        (
            "Python member visibility is not HTTP authorization. The H"
            "TTP edge is conditional on BRC_SERVICE_URL; in-process op"
            "erator/CLI wiring can still exist. No network isolation o"
            "r authenticated-only caller claim is made."
        ),
    ]
    guide += [
        "",
        "## Type contracts and aliases",
        "",
        "Types are declared or reconstructed from constructor wiring, "
        "callers, returns and validated schemas. AppConfig, FilterData "
        "and similar names are diagram aliases for the existing "
        "dictionaries, not additional production classes.",
        "",
        "DynamicValue means object when no narrower contract is "
        "established. It is explicitly listed in the review queue, never "
        "silently presented as a verified domain type. Any is retained "
        "for heterogeneous JSON values and variadic payloads. See "
        "json/type_evidence.json for per-slot evidence and the "
        "unresolved/partial review queue.",
        "",
        "| Alias | Actual Python type |",
        "| --- | --- |",
    ]
    guide += [
        f"| {name} | `{meaning}` |"
        for name, meaning in sorted(analysis.uml_types.aliases.items())
    ]
    guide += [
        "",
        "### Reviewed AI boundary details",
        "",
        "- `AppConfig` is the dictionary returned by "
        "`BIS/support/config.py:load_config`; it is not a config class.",
        "- `ChatHistory` follows `ChatRequestModel.history`. Profile wishes "
        "are lists of strings in the callers; the interpreter strips and "
        "validates each item and returns `list[str]`.",
        "- `ChatDecision` contains `intent: str`, `reply: str`, "
        "`updates: dict` and `quick_replies: list`. The interpreter checks "
        "the list container but not every element's type; the diagram "
        "does not claim a stronger `list[str]` response guarantee.",
        "- `Recommendations` contains dictionaries with `id: int` and "
        "`reason_codes: list[str]`, checked by "
        "`BRNS.ai_manager._validate_recommendation_output`; the manager "
        "can return `None` after provider failure.",
        "- BRC cuisine replies become `dict[int, list[str]]`; outlet "
        "matching returns a permitted certificate number (`str`) or "
        "`None`. The general JSON parser promises only a list or dict.",
        "",
        "Relationship reference: [Creately class diagram "
        "relationships]"
        "(https://creately.com/guides/class-diagram-relationships/). "
        "It distinguishes association, navigability, same-class links, "
        "multiplicity, aggregation, composition, generalisation and "
        "realisation. Only relationships supported by source evidence are "
        "drawn; recursive methods alone do not establish reflexive "
        "association.",
    ]
    (output / "INDEX.md").write_text("\n".join(guide) + "\n", encoding="utf-8")
    organize_artifacts(output, replace=True)
    return model
