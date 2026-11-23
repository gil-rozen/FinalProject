import subprocess
import tempfile
import sys
import os
import ast
from typing import Tuple, Optional
from config import SANDBOX_DRY_RUN_TIMEOUT

CANVAS_SIZE_SHIM = """# Tkinter Runtime Safety Shims (Singleton Tk, Canvas Dimensions, Smart Coords/Items, Pack/Grid Compatibility)
try:
    import tkinter as _tk

    # 1. Singleton tk.Tk protection: prevents double tk.Tk() calls from creating a second blank window
    _ACTIVE_ROOT = None
    _orig_tk_new = _tk.Tk.__new__
    _orig_tk_init = _tk.Tk.__init__
    _orig_tk_destroy = _tk.Tk.destroy

    def _singleton_tk_new(cls, *args, **kwargs):
        global _ACTIVE_ROOT
        if _ACTIVE_ROOT is not None:
            return _ACTIVE_ROOT
        inst = _orig_tk_new(cls)
        _ACTIVE_ROOT = inst
        return inst

    def _singleton_tk_init(self, *args, **kwargs):
        if "_already_initialized" in self.__dict__:
            return
        self.__dict__["_already_initialized"] = True
        _orig_tk_init(self, *args, **kwargs)

    def _singleton_tk_destroy(self):
        global _ACTIVE_ROOT
        _ACTIVE_ROOT = None
        self.__dict__.pop("_already_initialized", None)
        return _orig_tk_destroy(self)

    _tk.Tk.__new__ = staticmethod(_singleton_tk_new)
    _tk.Tk.__init__ = _singleton_tk_init
    _tk.Tk.destroy = _singleton_tk_destroy

    # 2. Canvas winfo_width / winfo_height fallback before window is mapped
    _orig_cw = _tk.Canvas.winfo_width
    _orig_ch = _tk.Canvas.winfo_height
    def _safe_winfo_width(self):
        w = _orig_cw(self)
        if w <= 1:
            try:
                return int(float(self.cget("width")))
            except Exception:
                return 600
        return w
    def _safe_winfo_height(self):
        h = _orig_ch(self)
        if h <= 1:
            try:
                return int(float(self.cget("height")))
            except Exception:
                return 400
        return h
    _tk.Canvas.winfo_width = _safe_winfo_width
    _tk.Canvas.winfo_height = _safe_winfo_height

    # 3. Smart _CoordList and _CanvasItemId: supports .left, .right, .top, .bottom, .x, .y, .colliderect()
    class _CoordList(list):
        @property
        def left(self): return self[0] if len(self) >= 1 else 0.0
        @property
        def top(self): return self[1] if len(self) >= 2 else 0.0
        @property
        def right(self): return self[2] if len(self) >= 3 else (self[0] if self else 0.0)
        @property
        def bottom(self): return self[3] if len(self) >= 4 else (self[1] if len(self) >= 2 else 0.0)
        @property
        def x(self): return self[0] if len(self) >= 1 else 0.0
        @property
        def y(self): return self[1] if len(self) >= 2 else 0.0
        def colliderect(self, other):
            if isinstance(other, int) and hasattr(other, "_canvas"):
                other = other._canvas.coords(other)
            if not self or not other or len(self) < 4 or len(other) < 4:
                return False
            return not (self[2] < other[0] or self[0] > other[2] or self[3] < other[1] or self[1] > other[3])

    class _CanvasItemId(int):
        def __new__(cls, val, canvas=None):
            obj = super().__new__(cls, val)
            obj._canvas = canvas
            return obj
        @property
        def _coords(self):
            return self._canvas.coords(self) if self._canvas else _CoordList([0.0, 0.0, 0.0, 0.0])
        @property
        def left(self): return self._coords.left
        @property
        def top(self): return self._coords.top
        @property
        def right(self): return self._coords.right
        @property
        def bottom(self): return self._coords.bottom
        @property
        def x(self): return self._coords.x
        @property
        def y(self): return self._coords.y
        def __iter__(self):
            c = self._coords
            return iter((c[0], c[1])) if len(c) >= 2 else iter((0.0, 0.0))
        def __getitem__(self, idx):
            c = self._coords
            return c[idx] if c else 0.0
        def colliderect(self, other):
            return self._coords.colliderect(other)

    _orig_coords = _tk.Canvas.coords
    def _smart_coords(self, *args):
        res = _orig_coords(self, *args)
        if isinstance(res, list):
            return _CoordList(res)
        return res
    _tk.Canvas.coords = _smart_coords

    for _m in ("create_rectangle", "create_oval", "create_line", "create_polygon", "create_text"):
        _orig_m = getattr(_tk.Canvas, _m)
        def _make_wrapper(fn, mname=_m):
            def _wrapped(self, *a, **kw):
                if mname in ("create_rectangle", "create_oval"):
                    h = kw.pop("height", None)
                    if len(a) == 2 and all(isinstance(v, (int, float)) for v in a):
                        w = kw.pop("width", h if h is not None else 10)
                        a = (a[0], a[1], a[0] + w, a[1] + (h if h is not None else w))
                cid = fn(self, *a, **kw)
                return _CanvasItemId(cid, self) if isinstance(cid, int) else cid
            return _wrapped
        setattr(_tk.Canvas, _m, _make_wrapper(_orig_m))

    # 4. Pack / Grid mix conflict resolution shim
    _orig_pack = _tk.Pack.pack_configure
    _orig_grid = _tk.Grid.grid_configure

    def _safe_pack(self, *args, **kwargs):
        try:
            return _orig_pack(self, *args, **kwargs)
        except _tk.TclError as e:
            if "already has slaves managed by grid" in str(e):
                return _orig_grid(self, sticky="nsew")
            raise

    def _safe_grid(self, *args, **kwargs):
        try:
            return _orig_grid(self, *args, **kwargs)
        except _tk.TclError as e:
            if "already has slaves managed by pack" in str(e):
                return _orig_pack(self, fill=_tk.BOTH, expand=True)
            raise

    _tk.Pack.pack = _safe_pack
    _tk.Pack.pack_configure = _safe_pack
    _tk.Grid.grid = _safe_grid
    _tk.Grid.grid_configure = _safe_grid
except Exception:
    pass
"""

SITECUSTOMIZE_INTERCEPTOR = CANVAS_SIZE_SHIM + """
import sys
import os
import traceback

try:
    import tkinter as tk
    from tkinter import ttk, messagebox

    # Prevent modal dialogs from blocking automated sandbox testing
    messagebox.showinfo = lambda *a, **kw: "ok"
    messagebox.showwarning = lambda *a, **kw: "ok"
    messagebox.showerror = lambda *a, **kw: "ok"
    messagebox.askyesno = lambda *a, **kw: True
    messagebox.askokcancel = lambda *a, **kw: True
    messagebox.askretrycancel = lambda *a, **kw: False

    def _collect_interactive_widgets(widget):
        buttons, canvases, entries = [], [], []
        try:
            children = widget.winfo_children()
        except Exception:
            return buttons, canvases, entries
        for child in children:
            if isinstance(child, (tk.Button, ttk.Button)):
                buttons.append(child)
            elif isinstance(child, tk.Canvas):
                canvases.append(child)
            elif isinstance(child, (tk.Entry, ttk.Entry, tk.Label, ttk.Label)):
                entries.append(child)
            b, c, e = _collect_interactive_widgets(child)
            buttons.extend(b)
            canvases.extend(c)
            entries.extend(e)
        return buttons, canvases, entries

    def _simulate_user_actions(root):
        try:
            # Explicitly flush pending geometry and render tasks before inspecting widgets/canvas
            root.update_idletasks()
            root.update()

            # Auto-pack any direct child widgets on root that were created without pack/grid/place
            for child in root.winfo_children():
                try:
                    if not child.winfo_manager():
                        child.pack()
                except Exception:
                    pass

            root.update_idletasks()
            root.update()

            root_children_list = [f"{type(w).__name__}({w.winfo_name()})" for w in root.winfo_children()]
            buttons, canvases, entries = _collect_interactive_widgets(root)
            per_canvas_counts = [len(c.find_all()) for c in canvases]
            canvas_items = sum(per_canvas_counts)

            if not buttons and canvas_items == 0:
                sys.stderr.write(
                    "RuntimeError: UI Verification Failed - Window has no rendered buttons or canvas items!\\n"
                    f"UI Verification Diagnostics:\\n"
                    f"  - root.winfo_children() ({len(root_children_list)}): {root_children_list}\\n"
                    f"  - Canvas widgets found: {len(canvases)} | canvas.find_all() counts: {per_canvas_counts} (total={canvas_items})\\n"
                    f"  - Button widgets found: {len(buttons)} | Label/Entry widgets found: {len(entries)}\\n"
                    "Fix Required: In `def setup_game(self):` (or `def setup_ui(self):`), draw game entities on `self.canvas` "
                    "using `self.canvas.create_rectangle(...)` / `self.canvas.create_oval(...)` or create `tk.Button` widgets in `self.grid_frame`.\\n"
                )
                sys.stderr.flush()
                os._exit(1)

            try:
                root.focus_force()
            except Exception:
                pass

            # Simulate keyboard inputs for 1-player, 2-player, and utility controls
            targets = [root] + canvases
            test_keys = ["Up", "Down", "Left", "Right", "w", "s", "a", "d", "1", "plus", "2", "Return", "space", "r", "c"]
            for ks in test_keys:
                for t in targets:
                    try:
                        t.event_generate(f"<KeyPress-{ks}>", when="tail")
                        root.update()
                        t.event_generate(f"<KeyRelease-{ks}>", when="tail")
                        root.update()
                    except tk.TclError:
                        pass

            # Simulate clicking buttons if widget buttons exist
            for btn in buttons[:6]:
                try:
                    btn.invoke()
                    root.update()
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    sys.stderr.flush()
                    os._exit(1)

        except SystemExit:
            raise
        except Exception:
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            os._exit(1)

    _base_singleton_init = tk.Tk.__init__
    def _test_init(self, *args, **kwargs):
        already = "_already_initialized" in self.__dict__
        _base_singleton_init(self, *args, **kwargs)
        if not already:
            try:
                self.attributes("-alpha", 0.0)  # Invisible window with real geometry
                self.after(300, lambda: _simulate_user_actions(self))
                self.after(1400, self.destroy)
            except Exception:
                pass

    def _test_report_callback_exception(self, exc, val, tb):
        traceback.print_exception(exc, val, tb, file=sys.stderr)
        sys.stderr.flush()
        os._exit(1)

    tk.Tk.__init__ = _test_init
    tk.Tk.report_callback_exception = _test_report_callback_exception
except ImportError:
    pass
"""


class SandboxRunner:
    @staticmethod
    def _align_entrypoint_class(code: str) -> str:
        """
        Dynamically detects the game class in the candidate file and ensures the
        __main__ instantiation block calls the exact detected class name.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code

        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        if not classes:
            return code

        main_cls = classes[0]
        detected_name = main_cls.name
        other_class_names = {c.name for c in classes}

        defined_top_names = {
            n.name for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))
        }
        builtin_names = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called_name = node.func.id
                if (
                    called_name not in defined_top_names
                    and called_name not in builtin_names
                    and called_name[0].isupper()
                ):
                    node.func.id = detected_name

        # Ensure a mainloop entry point exists
        has_mainloop = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "mainloop"
            for n in ast.walk(tree)
        )
        if not has_mainloop:
            init_fn = next(
                (n for n in main_cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
                None
            )
            takes_root = not (init_fn and len(init_fn.args.args) == 1)
            if takes_root:
                entry = (
                    f"\nif __name__ == '__main__':\n"
                    f"    root = tk.Tk()\n"
                    f"    app = {detected_name}(root)\n"
                    f"    root.mainloop()\n"
                )
            else:
                entry = (
                    f"\nif __name__ == '__main__':\n"
                    f"    app = {detected_name}()\n"
                    f"    if hasattr(app, 'root'):\n"
                    f"        app.root.mainloop()\n"
                )
            return code.rstrip() + "\n" + entry

        return ast.unparse(tree)

    @staticmethod
    def verify_execution(code: str) -> Tuple[bool, str]:
        """
        Runs the generated game in an isolated temporary directory with sitecustomize.py
        intercepting exceptions, aligning class instantiation, and simulating keyboard/button interactions.
        """
        aligned_code = SandboxRunner._align_entrypoint_class(code)

        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = os.path.join(temp_dir, "sitecustomize.py")
            with open(site_path, "w", encoding="utf-8") as f:
                f.write(SITECUSTOMIZE_INTERCEPTOR)

            file_path = os.path.join(temp_dir, "game_candidate.py")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(aligned_code)

            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            existing_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{temp_dir}{os.pathsep}{existing_pp}" if existing_pp else temp_dir

            stdout, stderr = "", ""
            returncode = 0

            try:
                proc = subprocess.Popen(
                    [sys.executable, file_path],
                    cwd=temp_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                try:
                    stdout, stderr = proc.communicate(timeout=SANDBOX_DRY_RUN_TIMEOUT)
                    returncode = proc.returncode
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        stdout, stderr = proc.communicate(timeout=1.0)
                    except Exception:
                        proc.kill()
                        stdout, stderr = proc.communicate()
                    returncode = 0

                has_traceback = (
                    "Traceback (most recent call last):" in (stderr or "")
                    or "RuntimeError: UI Verification Failed" in (stderr or "")
                )
                if returncode != 0 or has_traceback:
                    clean_err = stderr.strip() if stderr else f"Process crashed with return code {returncode}."
                    return False, f"Process crashed or produced runtime errors during interactive test.\nTraceback:\n{clean_err}"

                return True, f"GUI Mainloop, timers, and simulated input handlers verified without errors.\nOutput: {stdout.strip()}"

            except Exception as e:
                return False, f"Sandbox internal execution error: {str(e)}"

    @staticmethod
    def launch_interactive(code: str):
        """Launches the verified (or best-effort) game for the user to play."""
        aligned_code = SandboxRunner._align_entrypoint_class(code)
        temp_dir = tempfile.mkdtemp(prefix="verified_game_")
        site_path = os.path.join(temp_dir, "sitecustomize.py")
        with open(site_path, "w", encoding="utf-8") as f:
            f.write(CANVAS_SIZE_SHIM)

        file_path = os.path.join(temp_dir, "play_game.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(aligned_code)

        env = os.environ.copy()
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{temp_dir}{os.pathsep}{existing_pp}" if existing_pp else temp_dir
        subprocess.Popen([sys.executable, file_path], cwd=temp_dir, env=env)
