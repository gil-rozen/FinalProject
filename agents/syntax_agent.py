from typing import Tuple, Optional
from agents.base_agent import BaseAgent
from state import HarnessState
from tools.ast_validator import ASTValidator


class SyntaxAgent(BaseAgent):
    def validate_microtask(
        self,
        state: HarnessState,
        candidate_code: str,
        target_method: str
    ) -> Tuple[bool, Optional[str]]:
        is_valid, error_msg = ASTValidator.validate_microtask(
            candidate_code,
            target_method=target_method,
            game_name=state.game_name,
            archetype=state.app_archetype
        )
        if is_valid:
            self.log(state, f"Incremental AST validation passed for micro-task `{target_method}`.", "SUCCESS")
        else:
            self.log(state, f"Incremental AST validation failed for `{target_method}`:\n{error_msg}", "WARNING")
        return is_valid, error_msg

    def run(self, state: HarnessState):
        self.log(state, "Running full static AST syntax, method completeness, and security verification...")
        is_valid, error_msg = ASTValidator.validate(
            state.current_code,
            game_name=state.game_name,
            archetype=state.app_archetype
        )
        state.syntax_valid = is_valid
        state.syntax_error = error_msg

        if is_valid:
            self.log(state, "AST Verification passed: Valid syntax, complete methods, and safe imports.", "SUCCESS")
        else:
            self.log(state, f"AST Verification failed:\n{error_msg}", "ERROR")
