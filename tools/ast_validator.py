import ast
import re
import textwrap
from typing import Tuple, Optional, Set, List, Dict
from config import FORBIDDEN_IMPORTS

STANDARD_TK_ATTRS: Set[str] = {
    "pack", "grid", "place", "bind", "unbind", "after", "after_cancel", "destroy",
    "title", "geometry", "configure", "config", "update", "update_idletasks",
    "mainloop", "quit", "winfo_width", "winfo_height", "winfo_children",
    "winfo_reqwidth", "winfo_reqheight", "delete", "create_rectangle",
    "create_oval", "create_text", "create_line", "create_polygon", "move",
    "coords", "itemconfig", "itemconfigure", "find_all", "find_overlapping",
    "find_withtag", "focus_set", "focus_force", "rowconfigure", "columnconfigure",
    "grid_rowconfigure", "grid_columnconfigure", "withdraw", "deiconify",
    "attributes", "resizable", "minsize", "maxsize", "cget", "tk", "master"
}

DISALLOWED_EXTERNAL_LIBS: Set[str] = {
    "pygame", "turtle", "curses", "PIL", "numpy", "scipy", "matplotlib", "wx", "PyQt5", "PySide6"
}

PROTECTED_SCAFFOLD_WIDGETS: Set[str] = {
    "score_label", "canvas", "root", "master", "display_label", "display_var", "grid_frame"
}

CANVAS_CREATE_METHODS: Set[str] = {
    "create_rectangle", "create_oval", "create_text", "create_line",
    "create_polygon", "create_arc", "create_bitmap", "create_image", "create_window"
}


class ASTMerger:
    """
    Deterministically merges dynamically planned sub-tasks (methods, imports, constants)
    into the base class AST, synchronizing class names, planned method stubs, and entry points.
    """

    @staticmethod
    def is_stub(func_node: ast.FunctionDef) -> bool:
        body = list(func_node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        if not body:
            return True
        if len(body) == 1:
            stmt = body[0]
            if isinstance(stmt, ast.Pass):
                return True
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
                return True
        return False

    @staticmethod
    def parse_with_salvage(code_str: str) -> Optional[ast.Module]:
        """Parses Python code; if trailing lines were truncated, trims trailing lines until valid AST is recovered."""
        for candidate_raw in (textwrap.dedent(code_str).strip(), code_str.strip()):
            if not candidate_raw:
                continue
            try:
                return ast.parse(candidate_raw)
            except SyntaxError:
                lines = candidate_raw.splitlines()
                for cut in range(1, len(lines)):
                    trimmed = "\n".join(lines[:-cut]).strip()
                    if not trimmed:
                        break
                    try:
                        return ast.parse(trimmed)
                    except SyntaxError:
                        continue
        return None

    @classmethod
    def register_planned_stubs(cls, base_code: str, subtasks: List[Dict[str, str]]) -> str:
        """
        Pre-registers empty method stubs on the primary class for all dynamically planned
        sub-tasks so earlier methods can reference later planned methods without error.
        """
        tree = cls.parse_with_salvage(base_code)
        if tree is None:
            return base_code
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        if not classes:
            return base_code

        main_cls = classes[0]
        existing_methods = {n.name: n for n in main_cls.body if isinstance(n, ast.FunctionDef)}

        for task in subtasks:
            m_name = task.get("target_method", "").strip()
            if not m_name or not m_name.isidentifier():
                continue
            args_sig = task.get("args", "self").strip()
            if not args_sig.startswith("self"):
                args_sig = f"self, {args_sig}" if args_sig else "self"
            try:
                stub_node = ast.parse(f"def {m_name}({args_sig}):\n    pass\n").body[0]
            except SyntaxError:
                stub_node = ast.parse(f"def {m_name}(self):\n    pass\n").body[0]

            if not isinstance(stub_node, ast.FunctionDef):
                continue

            if m_name in existing_methods:
                # If the existing scaffold method is just a pass stub, update its signature to match the plan
                if cls.is_stub(existing_methods[m_name]):
                    existing_methods[m_name].args = stub_node.args
            else:
                main_cls.body.append(stub_node)
                existing_methods[m_name] = stub_node

        return ast.unparse(tree)

    @staticmethod
    def extract_self_attributes(code: str) -> List[str]:
        """Returns sorted list of all `self.<attr>` names assigned anywhere in the primary class."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []
        attrs: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
                if isinstance(node.value, ast.Name) and node.value.id == "self":
                    attrs.add(f"self.{node.attr}")
        return sorted(attrs)

    @staticmethod
    def extract_method_source(code: str, method_name: str) -> str:
        """Extracts the unparsed source code of a single method from the primary class."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return ""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == method_name:
                return ast.unparse(node)
        return ""

    @staticmethod
    def find_enclosing_methods(code: str, error_report: str) -> List[str]:
        """
        Determines which method(s) in `code` enclose the line numbers mentioned in `error_report`
        or are explicitly named in `error_report`.
        """
        if not code or not error_report:
            return []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []

        line_nums = [int(m) for m in re.findall(r"line (\d+)", error_report)]
        found: List[str] = []
        scaffold_internals = {
            "__init__", "setup_controls", "on_key_press", "on_key_release",
            "game_loop", "check_collision", "_configure_grid_weights"
        }

        method_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        # Walk line numbers in reverse order so the deepest traceback frame comes first
        for ln in reversed(line_nums):
            for node in method_nodes:
                start = getattr(node, "lineno", 0)
                end = getattr(node, "end_lineno", start)
                if start <= ln <= end and node.name not in found:
                    found.append(node.name)

        for node in method_nodes:
            if node.name in error_report and node.name not in found:
                found.append(node.name)

        non_scaffold = [m for m in found if m not in scaffold_internals]
        return non_scaffold if non_scaffold else found

    @classmethod
    def _sanitize_method(cls, fn_node: ast.FunctionDef, init_has_canvas: bool) -> ast.FunctionDef:
        """Ensures `self` is first arg and removes accidental duplicate tk.Tk() or container destruction inside non-init methods."""
        if not fn_node.args.args or fn_node.args.args[0].arg != "self":
            fn_node.args.args.insert(0, ast.arg(arg="self"))

        if fn_node.name == "__init__":
            return fn_node

        cleaned_body = []
        for stmt in fn_node.body:
            unp = ast.unparse(stmt)
            if "tk.Tk(" in unp or unp.strip() in ("self.setup_controls()", "self.game_loop()"):
                continue
            # Prevent destroying protected scaffold containers (e.g. self.grid_frame.destroy())
            if any(f"self.{w}.destroy(" in unp for w in PROTECTED_SCAFFOLD_WIDGETS if w not in ("root", "master")):
                if "self.grid_frame.destroy(" in unp:
                    cleaned_body.extend(ast.parse("for _w in self.grid_frame.winfo_children():\n    _w.destroy()").body)
                continue
            # Prevent re-creating or re-packing scaffold widgets that already exist in __init__
            if any(
                dup in unp
                for dup in (
                    "self.canvas = tk.Canvas(",
                    "self.canvas.pack(",
                    "self.canvas.grid(",
                    "self.score_label = tk.Label(",
                    "self.score_label.pack(",
                    "self.score_label.grid(",
                    "self.display_var = tk.StringVar(",
                    "self.display_label = tk.Label(",
                    "self.display_label.pack(",
                    "self.display_label.grid(",
                    "self.grid_frame = tk.Frame(",
                    "self.grid_frame.pack(",
                    "self.grid_frame.grid(",
                )
            ):
                continue
            cleaned_body.append(stmt)

        fn_node.body = cleaned_body if cleaned_body else [ast.Pass()]
        return fn_node

    @classmethod
    def ensure_structure(cls, code: str) -> str:
        if not code or not code.strip():
            return code
        tree = cls.parse_with_salvage(code)
        if tree is None:
            return code
        cls._wire_lifecycle_and_entrypoint(tree)
        return ast.unparse(tree)

    @classmethod
    def _wire_lifecycle_and_entrypoint(cls, tree: ast.Module):
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        if not classes:
            return

        main_cls = classes[0]
        method_map = {n.name: n for n in main_cls.body if isinstance(n, ast.FunctionDef)}

        if "__init__" in method_map:
            init_fn = method_map["__init__"]
            if len(init_fn.args.args) >= 2:
                arg_name = init_fn.args.args[1].arg
                init_src = ast.unparse(init_fn)
                if "self.root =" not in init_src:
                    init_fn.body.insert(0, ast.parse(f"self.root = {arg_name}").body[0])
                if "self.master =" not in init_src:
                    init_fn.body.insert(1, ast.parse(f"self.master = {arg_name}").body[0])

            alias_bridges = [
                ("setup_game", ["init_game", "create_objects", "init_game_state"], ""),
                ("on_button_click", ["on_click", "button_click", "handle_click", "press"], "value"),
            ]
            for target_hook, aliases, arg_str in alias_bridges:
                if target_hook in method_map and cls.is_stub(method_map[target_hook]):
                    for alias in aliases:
                        if alias in method_map and not cls.is_stub(method_map[alias]):
                            method_map[target_hook].body = [ast.parse(f"self.{alias}({arg_str})").body[0]]
                            break

            # If on_button_click takes 2+ arguments (e.g. (self, r, c) for a 2D board grid),
            # adapt scaffold's on_key_press so it doesn't call self.on_button_click('=') with 1 argument
            if "on_button_click" in method_map and "on_key_press" in method_map:
                obc = method_map["on_button_click"]
                if len(obc.args.args) > 2:
                    okp_src = (
                        "def on_key_press(self, event):\n"
                        "    if event.keysym in ('r', 'R', 'Escape'):\n"
                        "        self.reset_game()\n"
                    )
                    method_map["on_key_press"].body = ast.parse(okp_src).body[0].body

            # Ensure simple self.<attr> initializations placed in reset_game also exist on startup in setup_ui/setup_game
            startup_methods = [
                method_map[m] for m in ("__init__", "setup_ui", "setup_game", "init_game_state") if m in method_map
            ]
            startup_attrs = {
                sub.attr
                for fn in startup_methods
                for sub in ast.walk(fn)
                if isinstance(sub, ast.Attribute)
                and isinstance(sub.ctx, ast.Store)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == "self"
            }
            if "reset_game" in method_map:
                target_setup = method_map.get("setup_ui") or method_map.get("setup_game")
                if target_setup and not cls.is_stub(target_setup):
                    for stmt in method_map["reset_game"].body:
                        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                            tgt = stmt.targets[0]
                            if (
                                isinstance(tgt, ast.Attribute)
                                and isinstance(tgt.value, ast.Name)
                                and tgt.value.id == "self"
                                and tgt.attr not in startup_attrs
                                and isinstance(stmt.value, (ast.Constant, ast.List, ast.Dict, ast.Set, ast.Tuple))
                            ):
                                target_setup.body.insert(0, stmt)
                                startup_attrs.add(tgt.attr)

            # If a custom 0-arg state initializer (like init_game_state) was dynamically planned,
            # ensure it is called before setup_ui / setup_game if not already called
            all_called_in_class = {
                node.func.attr
                for fn in method_map.values()
                for node in ast.walk(fn)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            }
            for init_helper in ("init_game_state", "init_state", "setup_state"):
                if (
                    init_helper in method_map
                    and not cls.is_stub(method_map[init_helper])
                    and init_helper not in all_called_in_class
                ):
                    # Insert call inside setup_ui or setup_game at index 0
                    for target_setup in ("setup_ui", "setup_game"):
                        if target_setup in method_map and not cls.is_stub(method_map[target_setup]):
                            method_map[target_setup].body.insert(0, ast.parse(f"self.{init_helper}()").body[0])
                            break

        cleaned_module_body = []
        for node in tree.body:
            if isinstance(node, ast.If):
                test_src = ast.unparse(node.test)
                if "__name__" in test_src and "__main__" in test_src:
                    continue
            unp = ast.unparse(node)
            if ".mainloop(" in unp and not isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                continue
            cleaned_module_body.append(node)
        tree.body = cleaned_module_body

        init_fn = method_map.get("__init__")
        takes_root = True
        if init_fn and len(init_fn.args.args) == 1:
            takes_root = False

        if takes_root:
            entry_src = (
                f"if __name__ == '__main__':\n"
                f"    root = tk.Tk()\n"
                f"    app = {main_cls.name}(root)\n"
                f"    root.mainloop()\n"
            )
        else:
            entry_src = (
                f"if __name__ == '__main__':\n"
                f"    app = {main_cls.name}()\n"
                f"    if hasattr(app, 'root'):\n"
                f"        app.root.mainloop()\n"
                f"    elif hasattr(app, 'mainloop'):\n"
                f"        app.mainloop()\n"
            )
        tree.body.extend(ast.parse(entry_src).body)

    @classmethod
    def _merge_init_methods(
        cls,
        old_init: ast.FunctionDef,
        new_init: ast.FunctionDef,
        main_cls: ast.ClassDef
    ) -> ast.FunctionDef:
        old_unparsed = {ast.unparse(s) for s in old_init.body}
        old_assigned_attrs = {
            sub.attr
            for s in old_init.body
            for sub in ast.walk(s)
            if isinstance(sub, ast.Attribute)
            and isinstance(sub.ctx, ast.Store)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == "self"
        }

        insert_idx = len(old_init.body)
        for i, s in enumerate(old_init.body):
            unp = ast.unparse(s)
            if any(h in unp for h in ("self.setup_game(", "self.init_game_state(", "self.setup_ui(", "self.setup_controls(")):
                insert_idx = i
                break

        for stmt in new_init.body:
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                continue
            unp = ast.unparse(stmt)
            if unp in old_unparsed or "tk.Tk(" in unp:
                continue
            if any(
                dup in unp
                for dup in (
                    "self.canvas = tk.Canvas(",
                    "self.canvas.pack(",
                    "self.score_label = tk.Label(",
                    "self.score_label.pack(",
                    "self.display_label = tk.Label(",
                    "self.display_label.pack(",
                    "self.grid_frame = tk.Frame(",
                    "self.grid_frame.pack(",
                    "self.setup_game()",
                    "self.setup_ui()",
                    "self.setup_controls()",
                )
            ):
                continue

            new_attrs = {
                sub.attr
                for sub in ast.walk(stmt)
                if isinstance(sub, ast.Attribute)
                and isinstance(sub.ctx, ast.Store)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == "self"
            }
            if new_attrs & PROTECTED_SCAFFOLD_WIDGETS:
                continue

            if new_attrs and not new_attrs.issubset(old_assigned_attrs):
                old_init.body.insert(insert_idx, stmt)
                insert_idx += 1
                old_assigned_attrs.update(new_attrs)
                old_unparsed.add(unp)

        return old_init

    @classmethod
    def merge(
        cls,
        base_code: str,
        new_code: str,
        preserve_init_ui: bool = True,
        target_method: Optional[str] = None
    ) -> str:
        if not base_code or not base_code.strip():
            return cls.ensure_structure(new_code)
        if not new_code or not new_code.strip():
            return cls.ensure_structure(base_code)

        base_tree = cls.parse_with_salvage(base_code)
        if base_tree is None:
            return cls.ensure_structure(new_code)

        new_tree = cls.parse_with_salvage(new_code)
        if new_tree is None:
            return cls.ensure_structure(base_code)

        base_classes = [n for n in base_tree.body if isinstance(n, ast.ClassDef)]
        if not base_classes:
            return cls.ensure_structure(new_code)

        main_cls = base_classes[0]
        existing_method_names = {n.name for n in main_cls.body if isinstance(n, ast.FunctionDef)}

        init_has_canvas = False
        for n in main_cls.body:
            if isinstance(n, ast.FunctionDef) and n.name == "__init__":
                init_src = ast.unparse(n)
                if "self.canvas =" in init_src and "Canvas(" in init_src:
                    init_has_canvas = True

        incoming_methods = []
        top_helpers = []
        loose_self_stmts = []

        for item in new_tree.body:
            if isinstance(item, ast.ClassDef):
                for sub in item.body:
                    if isinstance(sub, ast.FunctionDef):
                        incoming_methods.append(cls._sanitize_method(sub, init_has_canvas))
            elif isinstance(item, ast.FunctionDef):
                item_src = ast.unparse(item)
                is_class_method = (
                    (item.args.args and item.args.args[0].arg == "self")
                    or "self." in item_src
                    or item.name in existing_method_names
                    or item.name == target_method
                )
                if is_class_method:
                    incoming_methods.append(cls._sanitize_method(item, init_has_canvas))
                else:
                    top_helpers.append(item)
            elif not isinstance(item, (ast.Import, ast.ImportFrom)):
                item_src = ast.unparse(item)
                if "self." in item_src:
                    loose_self_stmts.append(item)

        if not incoming_methods and loose_self_stmts and target_method:
            args_list = [ast.arg(arg="self")]
            # Match parameter list of existing stub on main_cls if present
            for existing_fn in main_cls.body:
                if isinstance(existing_fn, ast.FunctionDef) and existing_fn.name == target_method:
                    args_list = list(existing_fn.args.args) or [ast.arg(arg="self")]
                    break
            wrapped_fn = ast.FunctionDef(
                name=target_method,
                args=ast.arguments(
                    posonlyargs=[],
                    args=args_list,
                    kwonlyargs=[],
                    kw_defaults=[],
                    defaults=[]
                ),
                body=loose_self_stmts,
                decorator_list=[],
                lineno=1
            )
            incoming_methods.append(cls._sanitize_method(wrapped_fn, init_has_canvas))

        if not incoming_methods and not top_helpers:
            return cls.ensure_structure(base_code)

        existing_imports = {
            ast.unparse(n) for n in base_tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
        }
        existing_assigns = {
            n.targets[0].id: i
            for i, n in enumerate(base_tree.body)
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
        }
        existing_top_funcs = {
            n.name: i for i, n in enumerate(base_tree.body) if isinstance(n, ast.FunctionDef)
        }

        insert_pos = 0
        for i, n in enumerate(base_tree.body):
            if isinstance(n, (ast.Import, ast.ImportFrom, ast.Assign)):
                insert_pos = i + 1

        for n in new_tree.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                unparsed = ast.unparse(n)
                if unparsed not in existing_imports:
                    base_tree.body.insert(insert_pos, n)
                    insert_pos += 1
                    existing_imports.add(unparsed)
            elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                var_name = n.targets[0].id
                if var_name not in existing_assigns:
                    base_tree.body.insert(insert_pos, n)
                    insert_pos += 1

        for helper in top_helpers:
            if helper.name in existing_top_funcs:
                base_tree.body[existing_top_funcs[helper.name]] = helper
            else:
                base_tree.body.insert(insert_pos, helper)
                insert_pos += 1

        existing_method_map = {
            n.name: idx for idx, n in enumerate(main_cls.body) if isinstance(n, ast.FunctionDef)
        }

        for m in incoming_methods:
            if m.name in existing_method_map:
                idx = existing_method_map[m.name]
                old_m = main_cls.body[idx]
                if not cls.is_stub(m) or cls.is_stub(old_m):
                    if m.name == "__init__" and not cls.is_stub(old_m):
                        main_cls.body[idx] = cls._merge_init_methods(old_m, m, main_cls)
                        continue
                    main_cls.body[idx] = m
            else:
                main_cls.body.append(m)
                existing_method_map[m.name] = len(main_cls.body) - 1

        cls._wire_lifecycle_and_entrypoint(base_tree)
        return ast.unparse(base_tree)


class ASTValidator:
    @staticmethod
    def _is_canvas_create_call(val_node: ast.AST) -> bool:
        return (
            isinstance(val_node, ast.Call)
            and isinstance(val_node.func, ast.Attribute)
            and val_node.func.attr in CANVAS_CREATE_METHODS
        )

    @staticmethod
    def _is_coords_call_or_slice(val_node: ast.AST) -> Tuple[bool, bool]:
        if (
            isinstance(val_node, ast.Call)
            and isinstance(val_node.func, ast.Attribute)
            and val_node.func.attr == "coords"
        ):
            return True, False
        if (
            isinstance(val_node, ast.Subscript)
            and isinstance(val_node.value, ast.Call)
            and isinstance(val_node.value.func, ast.Attribute)
            and val_node.value.func.attr == "coords"
        ):
            return True, True
        return False, False

    @staticmethod
    def _method_arity_range(fn_node: ast.FunctionDef) -> Tuple[int, Optional[int]]:
        """Returns (min_args, max_args) excluding `self`. max_args is None if `*args` is present."""
        total_pos = len(fn_node.args.args)
        if total_pos > 0 and fn_node.args.args[0].arg == "self":
            total_pos -= 1
        num_defaults = len(fn_node.args.defaults)
        min_args = max(0, total_pos - num_defaults)
        max_args = None if fn_node.args.vararg is not None else total_pos
        return min_args, max_args

    @classmethod
    def _check_ast_rules(
        cls,
        tree: ast.Module,
        code: str,
        archetype: str = "",
        only_target_method: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        canvas_item_self_attrs: Set[str] = set()
        canvas_item_local_vars: Set[str] = set()
        collection_tuple_arity: Dict[str, int] = {}

        for node in ast.walk(tree):
            # Track tuple element arity for list/tuple literals of tuples (e.g. self.points = [(x, y), ...])
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.value, (ast.List, ast.Tuple)):
                elts = node.value.elts
                if elts and all(isinstance(e, (ast.Tuple, ast.List)) for e in elts):
                    first_len = len(elts[0].elts)
                    if first_len > 0 and all(len(e.elts) == first_len for e in elts):
                        tgt = node.targets[0]
                        if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                            collection_tuple_arity[f"self.{tgt.attr}"] = first_len
                        elif isinstance(tgt, ast.Name):
                            collection_tuple_arity[tgt.id] = first_len

            if isinstance(node, ast.Assign) and cls._is_canvas_create_call(node.value):
                for tgt in node.targets:
                    if (
                        isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "self"
                    ):
                        attr_name = tgt.attr
                        if attr_name in PROTECTED_SCAFFOLD_WIDGETS:
                            return False, (
                                f"Scaffold Attribute Collision Error at line {getattr(node, 'lineno', '?')}: "
                                f"Invalid assignment `{ast.unparse(node)}`! "
                                f"`self.{attr_name}` is ALREADY initialized in `__init__` as a Tkinter widget. "
                                f"NEVER overwrite `self.{attr_name}` with `self.canvas.create_*()`! "
                                f"To update `self.score_label`, call `self.score_label.config(text=...)`."
                            )
                        canvas_item_self_attrs.add(attr_name)
                    elif isinstance(tgt, ast.Name):
                        canvas_item_local_vars.add(tgt.id)

            # Check tuple unpacking arity in for-loops, comprehensions, and indexed assignments against known collection element arity
            if isinstance(node, (ast.For, ast.comprehension)):
                if isinstance(node.target, (ast.Tuple, ast.List)):
                    iter_src = ast.unparse(node.iter).strip()
                    # Strip slice/call suffixes like self.points[:-1] -> self.points
                    base_iter = iter_src.split("[")[0].strip() if "[" in iter_src else iter_src
                    if base_iter in collection_tuple_arity:
                        expected_k = collection_tuple_arity[base_iter]
                        actual_m = len(node.target.elts)
                        if actual_m != expected_k:
                            return False, (
                                f"Tuple Unpack Arity Error at line {getattr(node, 'lineno', '?')}: "
                                f"`for {ast.unparse(node.target)} in {iter_src}` unpacks {actual_m} variables, "
                                f"but `{base_iter}` contains {expected_k}-element tuples! "
                                f"Unpack {expected_k} variables (e.g. `for x, y in {base_iter}`) and if creating a canvas shape, "
                                f"pass 4 bounding-box coordinates `(x, y, x + 10, y + 10)` to `create_rectangle`/`create_oval`."
                            )

            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, (ast.Tuple, ast.List)) and isinstance(node.value, ast.Subscript):
                    sub_base = ast.unparse(node.value.value).strip()
                    # Check single-element indexing (not slicing) on a known collection of tuples
                    if not isinstance(node.value.slice, ast.Slice) and sub_base in collection_tuple_arity:
                        expected_k = collection_tuple_arity[sub_base]
                        actual_m = len(tgt.elts)
                        if actual_m != expected_k:
                            return False, (
                                f"Tuple Unpack Arity Error at line {getattr(node, 'lineno', '?')}: "
                                f"`{ast.unparse(node)}` unpacks {actual_m} variables from `{sub_base}[...]`, "
                                f"but `{sub_base}` contains {expected_k}-element tuples! "
                                f"Unpack {expected_k} variables instead of {actual_m}."
                            )

            # Check 4-variable unpacking and coordinate order of canvas.coords(item)
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, (ast.Tuple, ast.List)):
                    is_coords, is_sliced = cls._is_coords_call_or_slice(node.value)
                    if is_coords:
                        if len(tgt.elts) != 4 or is_sliced:
                            return False, (
                                f"Tkinter Coords Unpack Error at line {getattr(node, 'lineno', '?')}: "
                                f"Invalid coordinate unpacking `{ast.unparse(node)}`! "
                                f"`self.canvas.coords(item_id)` for shapes returns 4 coordinates `[x1, y1, x2, y2]` (left, top, right, bottom). "
                                f"Do NOT unpack {len(tgt.elts)} variables or slice `[:2]`. "
                                f"Always unpack all 4 variables: `x1, y1, x2, y2 = self.canvas.coords(item_id)`."
                            )
                        var_names = [e.id.lower() if isinstance(e, ast.Name) else "" for e in tgt.elts]
                        if (
                            var_names[0].startswith("y")
                            or var_names[1].startswith("x")
                            or var_names[2].startswith("y")
                            or var_names[3].startswith("x")
                        ):
                            return False, (
                                f"Tkinter Coords Variable Order Error at line {getattr(node, 'lineno', '?')}: "
                                f"`{ast.unparse(node)}` unpacks coordinates in the wrong order! "
                                f"`self.canvas.coords(item_id)` returns `[x1, y1, x2, y2]` where index 0 is `x1` (left), "
                                f"index 1 is `y1` (top), index 2 is `x2` (right), and index 3 is `y2` (bottom). "
                                f"Unpack in exact order: `x1, y1, x2, y2 = self.canvas.coords(item_id)`!"
                            )

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    if root_mod in DISALLOWED_EXTERNAL_LIBS:
                        return False, f"Do not import '{root_mod}'. Use standard library 'tkinter' only."
                    if root_mod in FORBIDDEN_IMPORTS:
                        return False, f"Security Violation: Import of forbidden module '{root_mod}' is not allowed."

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0]
                    if root_mod in DISALLOWED_EXTERNAL_LIBS:
                        return False, f"Do not import from '{root_mod}'. Use standard library 'tkinter' only."
                    if root_mod in FORBIDDEN_IMPORTS:
                        return False, f"Security Violation: Import from forbidden module '{root_mod}' is not allowed."

            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "input":
                    return False, "Forbidden function 'input()' detected. All interaction must occur inside Tkinter GUI."

                if isinstance(node.func, ast.Attribute):
                    # Check 1: Reject .move() calls on canvas item attributes (e.g. self.ball.move(...))
                    if node.func.attr == "move":
                        receiver = node.func.value
                        is_valid_canvas_receiver = False
                        if isinstance(receiver, ast.Name) and (receiver.id == "self" or "canvas" in receiver.id.lower()):
                            is_valid_canvas_receiver = True
                        elif (
                            isinstance(receiver, ast.Attribute)
                            and isinstance(receiver.value, ast.Name)
                            and receiver.value.id == "self"
                            and "canvas" in receiver.attr.lower()
                        ):
                            is_valid_canvas_receiver = True

                        if not is_valid_canvas_receiver:
                            bad_call = ast.unparse(node)
                            target_expr = ast.unparse(receiver)
                            args_src = ", ".join(ast.unparse(a) for a in node.args)
                            replacement = (
                                f"self.canvas.move({target_expr}, {args_src})"
                                if args_src
                                else f"self.canvas.move({target_expr}, dx, dy)"
                            )
                            return False, (
                                f"Tkinter Canvas Movement Error at line {getattr(node, 'lineno', '?')}: "
                                f"Invalid call `{bad_call}`! In Tkinter, `canvas.create_rectangle()` and `canvas.create_oval()` "
                                f"return integer item IDs, not objects (`AttributeError: 'int' object has no attribute 'move'`). "
                                f"You MUST use `{replacement}` for all canvas movement!"
                            )

                    # Check 2: Reject .config() / .configure() calls on variables assigned from canvas.create_*()
                    if node.func.attr in ("config", "configure"):
                        receiver = node.func.value
                        is_canvas_item_receiver = False
                        if (
                            isinstance(receiver, ast.Attribute)
                            and isinstance(receiver.value, ast.Name)
                            and receiver.value.id == "self"
                            and receiver.attr in canvas_item_self_attrs
                        ):
                            is_canvas_item_receiver = True
                        elif isinstance(receiver, ast.Name) and receiver.id in canvas_item_local_vars:
                            is_canvas_item_receiver = True

                        if is_canvas_item_receiver:
                            bad_call = ast.unparse(node)
                            target_expr = ast.unparse(receiver)
                            return False, (
                                f"Tkinter Canvas Item Config Error at line {getattr(node, 'lineno', '?')}: "
                                f"Invalid call `{bad_call}`! `{target_expr}` was assigned from `self.canvas.create_*()`, "
                                f"which returns an integer Canvas item ID (not a widget) and has no `.config()` method. "
                                f"To update a canvas item, use `self.canvas.itemconfig({target_expr}, ...)` — or to update the score label widget, "
                                f"use `self.score_label.config(text=...)`!"
                            )

                    # Check 3: Enforce 4 coordinate arguments on canvas.coords(item, x1, y1, x2, y2) setter calls
                    if node.func.attr == "coords" and len(node.args) > 1:
                        has_starred = any(isinstance(a, ast.Starred) for a in node.args)
                        if not has_starred and len(node.args) != 5:
                            bad_call = ast.unparse(node)
                            item_expr = ast.unparse(node.args[0])
                            coord_count = len(node.args) - 1
                            return False, (
                                f"Tkinter Coords Setter Error at line {getattr(node, 'lineno', '?')}: "
                                f"Invalid call `{bad_call}` passing {coord_count} coordinate arguments! "
                                f"For rectangles and ovals, `self.canvas.coords({item_expr}, x1, y1, x2, y2)` requires 4 coordinate arguments "
                                f"(left, top, right, bottom), NOT {coord_count}!"
                            )

                    # Check 4: Enforce 4 coordinate arguments on create_rectangle / create_oval (and no height= keyword)
                    if node.func.attr in ("create_rectangle", "create_oval"):
                        has_invalid_height = any(kw.arg == "height" for kw in node.keywords)
                        has_starred = any(isinstance(a, ast.Starred) for a in node.args)
                        if has_invalid_height or (not has_starred and len(node.args) != 4):
                            bad_call = ast.unparse(node)
                            return False, (
                                f"Tkinter Canvas Shape Creation Error at line {getattr(node, 'lineno', '?')}: "
                                f"Invalid call `{bad_call}`! In Tkinter, `self.canvas.{node.func.attr}(x1, y1, x2, y2, fill=...)` "
                                f"requires 4 positional coordinate arguments `(x1, y1, x2, y2)` (left, top, right, bottom) "
                                f"and does NOT accept `height=` or 2-coordinate `(x, y)` points! "
                                f"To draw a shape of size `S` at `(x, y)`, pass 4 coordinates: `self.canvas.{node.func.attr}(x, y, x + S, y + S, fill=...)`."
                            )

        # General-purpose class completeness, method arity matching, and attribute reference verification
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        for cls_node in classes:
            defined_methods = {n.name: n for n in cls_node.body if isinstance(n, ast.FunctionDef)}
            assigned_attrs: Set[str] = set()

            for sub in ast.walk(cls_node):
                if isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ast.Store):
                    if isinstance(sub.value, ast.Name) and sub.value.id == "self":
                        assigned_attrs.add(sub.attr)

            known_self_members = set(defined_methods.keys()) | assigned_attrs | STANDARD_TK_ATTRS

            nodes_to_check = (
                [defined_methods[only_target_method]]
                if only_target_method and only_target_method in defined_methods
                else [cls_node]
            )

            for scope_node in nodes_to_check:
                for sub in ast.walk(scope_node):
                    if isinstance(sub, ast.Call):
                        if (
                            isinstance(sub.func, ast.Attribute)
                            and isinstance(sub.func.value, ast.Name)
                            and sub.func.value.id == "self"
                        ):
                            m_name = sub.func.attr
                            if m_name not in known_self_members:
                                avail_methods = sorted(defined_methods.keys())
                                return False, (
                                    f"Undefined Method Error: `{cls_node.name}` calls `self.{m_name}()` "
                                    f"(line {getattr(sub, 'lineno', '?')}), which is NOT a defined method on `{cls_node.name}`! "
                                    f"Defined methods are: {avail_methods}. "
                                    f"Either write the logic inline directly inside `def {only_target_method or 'your_method'}(self, ...):` without calling `self.{m_name}()`, "
                                    f"or also define `def {m_name}(self, ...):` in the same code block."
                                )
                            # General-purpose method signature arity check
                            # During incremental micro-task validation, skip arity check against unimplemented stubs
                            # so that earlier methods (e.g. setup_ui) can define the call signature for later stubs
                            if m_name in defined_methods and not any(isinstance(a, ast.Starred) for a in sub.args):
                                target_fn = defined_methods[m_name]
                                if not (only_target_method and ASTMerger.is_stub(target_fn)):
                                    min_a, max_a = cls._method_arity_range(target_fn)
                                    passed_a = len(sub.args) + len(sub.keywords)
                                    if passed_a < min_a or (max_a is not None and passed_a > max_a):
                                        sig_args = ", ".join(a.arg for a in target_fn.args.args)
                                        return False, (
                                            f"Method Signature Mismatch Error at line {getattr(sub, 'lineno', '?')}: "
                                            f"Call `{ast.unparse(sub)}` passes {passed_a} argument(s), "
                                            f"but `def {m_name}({sig_args}):` expects {min_a if min_a == max_a else f'{min_a}..{max_a}'} argument(s)!"
                                        )

                    elif isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ast.Load):
                        if isinstance(sub.value, ast.Name) and sub.value.id == "self":
                            attr_name = sub.attr
                            if attr_name not in known_self_members:
                                avail = sorted(f"self.{a}" for a in assigned_attrs)
                                return False, (
                                    f"Undefined Attribute Error: Code reads `self.{attr_name}` at line {getattr(sub, 'lineno', '?')}, "
                                    f"but `self.{attr_name}` is never initialized! "
                                    f"Existing attributes on `self` are: {avail}. "
                                    f"Use the exact existing attribute names or initialize `self.{attr_name}`!"
                                )

            if only_target_method:
                if only_target_method not in defined_methods or ASTMerger.is_stub(defined_methods[only_target_method]):
                    return False, (
                        f"Incomplete Sub-Task Error: Method `def {only_target_method}(self, ...):` "
                        f"was not implemented or is still an empty `pass` stub! Write the full implementation for `def {only_target_method}`."
                    )
            else:
                # Verify all lifecycle entry hooks and any methods actively called on `self` are not left as empty stubs
                called_self_methods = {
                    sub.func.attr
                    for sub in ast.walk(cls_node)
                    if isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "self"
                }
                base_hooks = {"setup_game", "update_game"} if archetype == "CANVAS_ARCADE" else {"setup_ui", "on_button_click"}
                optional_hooks = {"handle_key", "on_key_release"}
                for m_name in (called_self_methods | base_hooks) - optional_hooks:
                    if m_name in defined_methods and ASTMerger.is_stub(defined_methods[m_name]):
                        return False, (
                            f"Incomplete Implementation Error: Method `def {m_name}(self, ...):` "
                            f"is called by the application but is still an empty `pass` stub! Write the complete implementation for `def {m_name}`."
                        )

        return True, None

    @classmethod
    def validate_microtask(
        cls,
        code: str,
        target_method: str,
        game_name: str = "",
        archetype: str = ""
    ) -> Tuple[bool, Optional[str]]:
        if not code or not code.strip():
            return False, "Generated code is empty."
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}, offset {e.offset}: {e.msg}\nLine: {e.text}"
        except Exception as e:
            return False, f"AST Parse Error: {str(e)}"

        return cls._check_ast_rules(
            tree,
            code,
            archetype=archetype,
            only_target_method=target_method
        )

    @classmethod
    def validate(cls, code: str, game_name: str = "", archetype: str = "") -> Tuple[bool, Optional[str]]:
        if not code or not code.strip():
            return False, "Generated code is empty."
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}, offset {e.offset}: {e.msg}\nLine: {e.text}"
        except Exception as e:
            return False, f"AST Parse Error: {str(e)}"

        return cls._check_ast_rules(
            tree,
            code,
            archetype=archetype,
            only_target_method=None
        )
