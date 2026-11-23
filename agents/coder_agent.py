import re
from typing import Dict, Optional, List
from agents.base_agent import BaseAgent
from state import HarnessState
from tools.ast_validator import ASTMerger


class CoderAgent(BaseAgent):
    def _get_system_prompt(self, archetype: str) -> str:
        if archetype == "WIDGET_GRID":
            return (
                "You are an Expert Python Tkinter Developer implementing modular methods for `class WidgetGridApp`.\n"
                "GENERAL TKINTER ENGINEERING RULES:\n"
                "1. Output ONLY the requested `def <method_name>(...):` method(s) inside ```python ... ```. Do NOT output `class` or `__init__`.\n"
                "2. Write clean, complete, and modular code for the assigned sub-task using as many lines as genuinely needed to implement the logic properly.\n"
                "3. READ-ONLY SCAFFOLD ATTRIBUTES IN `__init__`: `self.root`, `self.display_var` (`tk.StringVar`), "
                "`self.display_label` (`tk.Label`), `self.grid_frame` (`tk.Frame`), `self.current_input`, and `self.game_over` ALREADY exist in `__init__`. "
                "NEVER overwrite or destroy `self.display_label`, `self.grid_frame`, or `self.root`!\n"
                "4. WIDGET CREATION & CALLBACK SIGNATURES: Create interactive `tk.Button` widgets inside `self.grid_frame` using `.grid(row=r, column=c, sticky='nsew', padx=2, pady=2)`. "
                "If button labels/states change dynamically during gameplay (such as board cells), store the button references in a 2D list or dict on `self` (e.g. `self.buttons[r][c] = btn`) so other methods can update `self.buttons[r][c].config(text=...)`. "
                "Always capture loop variables with default arguments in lambdas (e.g., `command=lambda v=val: self.on_button_click(v)`) and ensure the argument count passed in `command` matches the parameter signature of `on_button_click`.\n"
                "5. DISPLAY UPDATES: Update the top status/display banner via `self.display_var.set(...)`."
            )
        else:
            return (
                "You are an Expert Python 2D Game Developer implementing modular methods for `class ArcadeGame`.\n"
                "GENERAL TKINTER CANVAS ENGINEERING RULES:\n"
                "1. Output ONLY the requested `def <method_name>(...):` method(s) inside ```python ... ```. Do NOT output `class` or `__init__`.\n"
                "2. Write clean, complete, and modular code for the assigned sub-task using as many lines as genuinely needed to implement the gameplay properly.\n"
                "3. NEVER OVERWRITE SCAFFOLD WIDGET ATTRIBUTES: In `__init__`, `self.score_label = tk.Label(...)`, "
                "`self.canvas = tk.Canvas(...)` (`CANVAS_WIDTH = 600`, `CANVAS_HEIGHT = 400`), `self.pressed_keys = set()`, `self.game_over = False`, and `self.root` are ALREADY created and packed! "
                "NEVER overwrite `self.score_label`, `self.canvas`, or `self.root` with `self.canvas.create_*()` item IDs! "
                "To update the scoreboard text, always call `self.score_label.config(text=f'...')`.\n"
                "4. CANVAS ITEM CREATION & IDS: `self.canvas.create_rectangle(x1, y1, x2, y2, fill=...)` and `self.canvas.create_oval(x1, y1, x2, y2, fill=...)` "
                "require 4 positional coordinate arguments `(x1, y1, x2, y2)` (never `width=`/`height=` with 2 coordinates!) and return integer item IDs. "
                "NEVER call `.move()` or `.config()` on an item ID — always use `self.canvas.move(item_id, dx, dy)` and `self.canvas.itemconfig(item_id, ...)`! "
                "Keep data types consistent across methods: do not unpack a Canvas item ID directly as `(x, y)` coordinates, and always check `if my_list:` before calling `.pop(0)`.\n"
                "5. 4-COORDINATE `canvas.coords()` RULES FOR SHAPES:\n"
                "   - Reading shape coordinates: unpack all 4 variables in order `x1, y1, x2, y2 = self.canvas.coords(item_id)` (left, top, right, bottom).\n"
                "   - Setting shape coordinates: pass all 4 coordinate arguments `self.canvas.coords(item_id, x1, y1, x2, y2)`.\n"
                "   - Collisions: use `self.check_collision(id1, id2)` which is pre-defined on `self`."
            )

    @staticmethod
    def _extract_failing_line_info(code: str, error_report: str) -> str:
        if not code or not error_report:
            return ""
        matches = re.findall(r"line (\d+)", error_report)
        if not matches:
            return ""
        lines = code.splitlines()
        snippets = []
        for m in matches[-3:]:
            lineno = int(m)
            if 1 <= lineno <= len(lines):
                snippets.append(f"Line {lineno}: {lines[lineno - 1].strip()}")
        return "\n".join(snippets)

    def _build_prior_methods_context(self, state: HarnessState, current_idx: int) -> str:
        init_src = ASTMerger.extract_method_source(state.current_code, "__init__")
        parts = [init_src]
        for task in state.subtasks[: current_idx - 1]:
            m_name = task.get("target_method", "")
            if m_name:
                m_src = ASTMerger.extract_method_source(state.current_code, m_name)
                if m_src:
                    parts.append(m_src)
        return "\n\n".join(p for p in parts if p)

    def generate_microtask_candidate(
        self,
        state: HarnessState,
        idx: int,
        subtask: Dict[str, str],
        retry_error: Optional[str] = None,
        failed_candidate: Optional[str] = None
    ) -> str:
        target_method = subtask["target_method"]
        args_sig = subtask.get("args", "self")
        if retry_error is None:
            self.log(state, f"Executing {subtask['title']}...")

        sys_prompt = self._get_system_prompt(state.app_archetype)
        existing_attrs = ASTMerger.extract_self_attributes(state.current_code)
        prior_context = self._build_prior_methods_context(state, idx)
        planned_signatures = [
            f"def {t['target_method']}({t.get('args', 'self')}):  # {t['focus']}"
            for t in state.subtasks
        ]
        planned_overview = "\n".join(planned_signatures)

        if state.app_archetype == "WIDGET_GRID":
            reminders = (
                "ENGINEERING GUIDELINES:\n"
                "- Use consistent `self.*` attribute names across all methods.\n"
                "- Ensure every button `command` lambda passes the exact number of arguments expected by the callback signature.\n"
                f"- Output the complete `def {target_method}({args_sig}):` implementation inside ```python ... ```."
            )
        else:
            reminders = (
                "ENGINEERING GUIDELINES:\n"
                "- Use consistent `self.*` attribute names across all methods.\n"
                "- Never overwrite `self.score_label` with `self.canvas.create_text(...)`; update `self.score_label.config(text=...)`.\n"
                "- When calling `self.canvas.coords(item_id)` on a canvas item ID, unpack 4 coordinates `x1, y1, x2, y2 = self.canvas.coords(item_id)`. "
                "When iterating over a list of 2-element `(x, y)` point tuples, unpack 2 variables `for x, y in ...` and pass 4 bounding-box coordinates `(x, y, x + 10, y + 10)` to `create_rectangle`/`create_oval`.\n"
                "- Always move canvas items via `self.canvas.move(item_id, dx, dy)`.\n"
                f"- Output the complete `def {target_method}({args_sig}):` implementation inside ```python ... ```."
            )

        retry_section = ""
        if retry_error:
            failed_method_src = ASTMerger.extract_method_source(failed_candidate or state.current_code, target_method)
            retry_section = (
                f"\n=== PREVIOUS ATTEMPT FAILED INCREMENTAL VALIDATION ===\n"
                f"Broken `{target_method}`:\n```python\n{failed_method_src}\n```\n"
                f"Error to Fix:\n{retry_error}\n"
                f"Fix this exact error and output the corrected `def {target_method}({args_sig}):` now!\n"
            )

        user_prompt = (
            f"Target: {state.game_name} ({state.app_archetype})\n"
            f"User Request: {state.user_prompt}\n"
            f"Specification:\n{state.summarized_rules}\n\n"
            f"Planned Class Methods:\n```python\n{planned_overview}\n```\n\n"
            f"Read-Only Scaffold `__init__` & Completed Sub-Tasks:\n"
            f"```python\n{prior_context}\n```\n"
            f"Available `self` attributes so far: {existing_attrs}\n\n"
            f"=== YOUR ASSIGNED SUB-TASK ===\n"
            f"{subtask['title']}\n"
            f"Responsibility: {subtask['focus']}\n"
            f"{retry_section}\n"
            f"{reminders}"
        )

        raw_resp = self.llm.chat(sys_prompt, user_prompt, temperature=0.2, max_tokens=550)
        extracted = self.llm.extract_code_block(raw_resp)
        base_for_merge = failed_candidate if (retry_error and failed_candidate) else state.current_code
        return ASTMerger.merge(
            base_for_merge,
            extracted,
            preserve_init_ui=True,
            target_method=target_method
        )

    def run_subtask(self, state: HarnessState, idx: int, subtask: Dict[str, str]):
        state.current_code = self.generate_microtask_candidate(state, idx, subtask)
        self.log(
            state,
            f"Merged {subtask['title']} into class (Total code: {len(state.current_code.splitlines())} lines).",
            "SUCCESS"
        )

    def run_repair(self, state: HarnessState):
        error_report = state.syntax_error if not state.syntax_valid else state.runtime_error
        self.log(state, f"Repair Iteration {state.iteration}: Fixing reported issue...", "WARNING")

        sys_prompt = self._get_system_prompt(state.app_archetype)
        existing_attrs = ASTMerger.extract_self_attributes(state.current_code)
        failing_line_info = self._extract_failing_line_info(state.current_code, error_report or "")
        enclosing_methods = ASTMerger.find_enclosing_methods(state.current_code, error_report or "")

        planned_methods = [t["target_method"] for t in state.subtasks] or (
            ["setup_ui", "on_button_click"] if state.app_archetype == "WIDGET_GRID" else ["setup_game", "update_game"]
        )
        default_target = enclosing_methods[0] if enclosing_methods else planned_methods[-1]
        target_methods_to_show: List[str] = []
        setup_m = "setup_ui" if state.app_archetype == "WIDGET_GRID" else "setup_game"
        if setup_m not in target_methods_to_show:
            target_methods_to_show.append(setup_m)
        for m in (enclosing_methods or planned_methods):
            if m not in target_methods_to_show:
                target_methods_to_show.append(m)

        method_snippets = []
        for m in target_methods_to_show:
            src = ASTMerger.extract_method_source(state.current_code, m)
            if src:
                method_snippets.append(src)
        methods_context = "\n\n".join(method_snippets) or state.current_code
        affected_desc = ", ".join(f"`{m}`" for m in (enclosing_methods or [default_target]))

        extra_diagnostic_hint = ""
        if error_report:
            if "IndexError" in error_report:
                extra_diagnostic_hint += (
                    "\nINDEXERROR FIX REQUIRED:\n"
                    "- A list attribute became empty across frames! Look carefully at every `.pop(0)` or `.pop()` in the method: "
                    "whenever a branch removes an old element with `.pop(0)`, it MUST also `.append(...)` (or `.insert(...)`) the new element into that same list so the list length never drops to 0!\n"
                    "- Also add a safety guard at the top of the method before indexing `[-1]` or `[0]` (e.g. `if not self.<list_name>: return`).\n"
                )
            if "values to unpack" in error_report:
                extra_diagnostic_hint += (
                    "\nVALUEERROR UNPACK FIX REQUIRED:\n"
                    "- Look at the failing unpacking line: if a list stores 2-element `(x, y)` tuples, you MUST unpack 2 variables (`for x, y in ...` or `x, y = ...`), NOT 4 variables (`x1, y1, x2, y2`)!\n"
                    "- To draw a rectangle of size 10 from a 2-tuple `(x, y)`, unpack 2 variables and pass 4 coordinates: "
                    "`[self.canvas.create_rectangle(x, y, x + 10, y + 10, fill='green') for x, y in self.points]`.\n"
                )

        repair_prompt = (
            f"The code for '{state.game_name}' ({state.app_archetype}) failed verification.\n"
            f"Existing `self` attributes: {existing_attrs}\n"
            f"Method(s) where the error originated: {affected_desc}\n\n"
            f"--- CURRENT RELEVANT METHODS (DO NOT OUTPUT `class` OR `__init__`) ---\n```python\n{methods_context}\n```\n\n"
            f"--- EXACT FAILING LINE(S) ---\n{failing_line_info or 'See diagnostic below.'}\n\n"
            f"--- ERROR DIAGNOSTIC & TRACEBACK ---\n{error_report}\n"
            f"{extra_diagnostic_hint}\n"
            "REPAIR INSTRUCTIONS:\n"
            f"1. Fix the bug in {affected_desc}. Output ONLY the repaired `def <method_name>(self, ...):` method(s) inside ```python ... ```.\n"
            "2. Do NOT output `import` statements, `class` headers, `__init__`, or unchanged scaffold methods!\n"
            "3. Ensure all `self.*` attributes read in any method are initialized in `setup_game` / `setup_ui`, and all method call argument counts match their definitions.\n"
            "4. For `canvas.coords`: unpack 4 variables `x1, y1, x2, y2 = self.canvas.coords(item_id)` in order, and pass 4 coordinate arguments when setting `self.canvas.coords(item_id, x1, y1, x2, y2)`.\n"
            "5. Never overwrite `self.score_label` with `self.canvas.create_text(...)` — update `self.score_label.config(text=...)`."
        )

        repair_temp = min(0.6, 0.2 + 0.08 * state.iteration)
        raw_resp = self.llm.chat(sys_prompt, repair_prompt, temperature=repair_temp, max_tokens=550)
        extracted = self.llm.extract_code_block(raw_resp)

        state.current_code = ASTMerger.merge(
            state.current_code,
            extracted,
            preserve_init_ui=True,
            target_method=default_target
        )
        self.log(
            state,
            f"Merged targeted method repair (Total code: {len(state.current_code.splitlines())} lines).",
            "SUCCESS"
        )

    def run(self, state: HarnessState):
        if state.iteration == 0:
            for idx, subtask in enumerate(state.subtasks, start=1):
                self.run_subtask(state, idx, subtask)
        else:
            self.run_repair(state)
