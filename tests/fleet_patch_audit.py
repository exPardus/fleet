"""AST census of fleet patch seams and implementation source readers."""
import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Site:
    path: str
    line: int
    kind: str
    name: object = None
    scope: str = ""


def moved_exports(root):
    """Use the explicit facade import, including the boundary's constants."""
    tree = ast.parse((Path(root) / "bin" / "fleet.py").read_text(encoding="utf-8"))
    return frozenset(alias.asname or alias.name
                     for node in tree.body if isinstance(node, ast.ImportFrom)
                     and node.module == "fleet_index" for alias in node.names)


def scan_source(source, path="<seed>"):
    tree = ast.parse(source)
    aliases = {alias.asname or alias.name
               for node in ast.walk(tree) if isinstance(node, ast.Import)
               for alias in node.names if alias.name == "fleet"}
    patch_aliases = {"patch"} | {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        and node.module == "unittest.mock"
        for alias in node.names if alias.name == "patch"}
    routed_aliases = {"patch_fleet"}
    string_targets = {}

    def string_target(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return (True, node.value) if node.value.startswith("fleet.") else (False, None)
        if isinstance(node, ast.Name):
            return string_targets.get(node.id, (False, None))
        if isinstance(node, (ast.JoinedStr, ast.BinOp)):
            if any(isinstance(part, ast.Constant) and isinstance(part.value, str)
                   and "fleet." in part.value for part in ast.walk(node)):
                return True, None
        return False, None
    # Include simple alias rebinding, even if the patch precedes its import.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if isinstance(node.value, ast.Name):
                        for collection in (aliases, patch_aliases, routed_aliases):
                            if node.value.id in collection and target.id not in collection:
                                collection.add(target.id)
                                changed = True
                    candidate = string_target(node.value)
                    if candidate[0] and target.id not in string_targets:
                        string_targets[target.id] = candidate
                        changed = True
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def scope(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return ""

    def fleet_receiver(node):
        return isinstance(node, ast.Name) and node.id in aliases

    def literal(node):
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    sites = []
    for node in ast.walk(tree):
        kind = name = None
        if isinstance(node, ast.Call):
            func = node.func
            callname = getattr(func, "id", None) or getattr(func, "attr", None)
            if callname in routed_aliases:
                kind, name = "routed", literal(node.args[0]) if node.args else None
            elif callname in {"setattr", "delattr", "object"} and len(node.args) >= 2 and fleet_receiver(node.args[0]):
                kind, name = "patch", literal(node.args[1])
            elif callname in patch_aliases | {"setattr", "delattr"} and node.args:
                is_fleet, target = string_target(node.args[0])
                if is_fleet:
                    kind, name = "string-patch", target.split(".", 2)[1] if target else None
            if kind is None and callname in {"parse", "getsource", "getsourcefile", "getsourcelines"}:
                kind = "source-reader"
        elif isinstance(node, ast.Attribute) and fleet_receiver(node.value):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                kind, name = "assignment", node.attr
            elif node.attr == "__file__":
                kind, name = "file-reader", "__file__"
        if kind:
            sites.append(Site(str(path), node.lineno, kind, name, scope(node)))
    return sorted(sites, key=lambda site: (site.path, site.line, site.kind))


def scan_tests(root):
    return [site for path in sorted((Path(root) / "tests").rglob("*.py"))
            for site in scan_source(path.read_text(encoding="utf-8"), path.relative_to(root))]


def unsafe_sites(sites, moved):
    """Dynamic patch receivers are forbidden; only the fixture routes them."""
    return [site for site in sites
            if (site.kind == "routed" and site.name is None)
            or (site.kind in {"patch", "string-patch", "assignment"}
                and (site.name is None or site.name in moved or site.name == "FleetCliError"))]
