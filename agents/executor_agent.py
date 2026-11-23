from agents.base_agent import BaseAgent
from state import HarnessState
from tools.sandbox import SandboxRunner

class ExecutorAgent(BaseAgent):
    def run(self, state: HarnessState):
        self.log(state, "Booting code inside isolated Sandbox subprocess...")
        success, output = SandboxRunner.verify_execution(state.current_code)
        state.execution_success = success
        state.runtime_error = None if success else output

        if success:
            self.log(state, f"Sandbox Verification passed: {output}", "SUCCESS")
        else:
            self.log(state, f"Sandbox Runtime Crash detected:\n{output}", "ERROR")
