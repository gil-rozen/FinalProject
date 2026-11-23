from agents.base_agent import BaseAgent
from state import HarnessState
from tools.wiki_tool import WikipediaTool

class ResearchAgent(BaseAgent):
    def _extract_title(self, prompt: str) -> str:
        extract_sys = (
            "Extract ONLY the concise 1-to-3 word canonical name of the game or application requested by the user. "
            "Output nothing else."
        )
        name = self.llm.chat(extract_sys, prompt, temperature=0.1, max_tokens=20)
        return name.strip("\"' \n.") or "Desktop Application"

    def _detect_archetype(self, text: str) -> str:
        classify_sys = (
            "Choose the Tkinter UI paradigm for this project:\n"
            "- Output 'CANVAS_ARCADE' if the project has continuous real-time movement or animation on a 2D Canvas "
            "(such as moving snakes, balls, paddles, ships, falling blocks, or projectiles driven by a timer loop).\n"
            "- Output 'WIDGET_GRID' if the project is click-driven or turn-based using Tkinter Buttons and Labels "
            "(such as board games, grid puzzles, word/card games, or desktop utilities).\n"
            "Output ONLY the single word 'CANVAS_ARCADE' or 'WIDGET_GRID'."
        )
        ans = self.llm.chat(classify_sys, text, temperature=0.1, max_tokens=15).strip().upper()
        last_line = ans.splitlines()[-1] if ans else ""
        if "CANVAS" in last_line or "ARCADE" in last_line:
            return "CANVAS_ARCADE"
        if "WIDGET" in last_line or "GRID" in last_line:
            return "WIDGET_GRID"
        return "CANVAS_ARCADE" if "CANVAS" in ans else "WIDGET_GRID"

    def run(self, state: HarnessState):
        self.log(state, f"Analyzing request: '{state.user_prompt}'...")

        state.game_name = self._extract_title(state.user_prompt)
        combined_text = f"{state.game_name} {state.user_prompt}"
        state.app_archetype = self._detect_archetype(combined_text)
        self.log(state, f"Identified target: '{state.game_name}' (Archetype: {state.app_archetype}).")

        raw_wiki = WikipediaTool.fetch_game_context(state.game_name)
        state.raw_wiki_content = raw_wiki[:1200]

        if state.app_archetype == "WIDGET_GRID":
            self.log(state, "Formulating functional specification for event-driven Widget/Grid application...")
            sum_sys = (
                "You are a Senior Python GUI Designer. Write a concise, structured functional specification (under 140 words) "
                "for implementing the user's request as an event-driven Tkinter application using `self.grid_frame` (for interactive `tk.Button` widgets) "
                "and `self.display_var` (for the top status/display label).\n"
                "Specify:\n"
                "1. State variables (`self.*`) required to represent the board, data, or application state.\n"
                "2. Exact 2D grid of `tk.Button` widgets to build inside `self.grid_frame` in `setup_ui(self)`.\n"
                "3. Input processing rules when a button or key is pressed in `on_button_click(self, value)`.\n"
                "4. Win, loss, evaluation, or completion conditions and reset behavior."
            )
            state.summarized_rules = self.llm.chat(
                sum_sys,
                f"Target: {state.game_name}\nUser Request: {state.user_prompt}\nContext:\n{state.raw_wiki_content}",
                temperature=0.2,
                max_tokens=240
            )
        else:
            self.log(state, "Formulating functional specification for 2D Canvas game...")
            sum_sys = (
                "You are a Senior 2D Game Designer. Write a concise, structured functional specification (under 140 words) "
                "for implementing this game on a 600x400 Tkinter `self.canvas` with top scoreboard `self.score_label`.\n"
                "Specify:\n"
                "1. State variables and canvas entities (`create_rectangle`, `create_oval`) to initialize in `setup_game(self)`.\n"
                "2. Player controls (via continuous `self.pressed_keys` or discrete `handle_key(self, key)`).\n"
                "3. Per-frame movement, boundary behavior, collision rules, and scoring updates.\n"
                "4. Game-over or goal-reset conditions and full game reset behavior."
            )
            state.summarized_rules = self.llm.chat(
                sum_sys,
                f"Game: {state.game_name}\nUser Request: {state.user_prompt}\nContext:\n{state.raw_wiki_content}",
                temperature=0.2,
                max_tokens=240
            )

        self.log(state, "Specification completed.", "SUCCESS")
