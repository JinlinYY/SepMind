"""PHA specialist adapters with deterministic engineering tools and sourced prompts."""

from pha.agents import DataScienceAgent, DomainExpertAgent, HealthCoachAgent
from pha.prompts.engineering_prompts import load_engineering_prompt
from pha.streaming import emit_step
from ..tools import EngineeringToolRegistry
from ..skills import ExpertSkillRegistry


class EngineeringCalculationAgent(DataScienceAgent):
    def __init__(self, registry=None):
        super().__init__()
        self.registry = registry or EngineeringToolRegistry()

    def execute(self, state, gate, tool_name):
        emit_step("EngineeringCalc", f"{gate}: {tool_name}")
        from pha.utils.request_stats import request_stats
        request_stats.record_tool(tool_name)
        args = {"basis": state.basis.model_dump()} if self.registry.TOOLS[tool_name][1].model_fields else {}
        return self.registry.execute(tool_name,state,gate,args)

    def execute_code(self, code):
        raise PermissionError("Arbitrary Python execution is disabled in engineering workflows; use typed tools")

    def query(self, query):
        return "Registered engineering calculations: " + ", ".join(self.registry.TOOLS)


class ThermodynamicsExpertAgent(DomainExpertAgent):
    def __init__(self):
        super().__init__(preamble=load_engineering_prompt("MODEL_SELECTOR"))
        self.skills = ExpertSkillRegistry()

    def skill_context(self,state,gate,tool_name):
        return self.skills.context(state,gate,tool_name,'thermodynamics')

    def execute(self, state, gate, tool_name, calculation_agent):
        emit_step("Thermodynamics", f"{gate}: verify model and source evidence")
        return calculation_agent.execute(state,gate,tool_name)

    def call_agent(self, prompt):
        # Deterministic knowledge cards are evidence, not numerical calculations.
        return self.knowledge_answer(prompt)

    @staticmethod
    def knowledge_answer(question):
        if "wilson" in question.lower():
            return ("普通 Wilson 模型不能表示稳定液液分相，不能用于本流程的 LLE 设计。"
                    "应核验适用的 NRTL/UNIQUAC 模型及来源参数。当前仅对常压乙醇／水的 NRTL 做了来源及实验筛查，不能推广到其他物系或 LLE；未执行数值计算。\n"
                    "依据：engineering/prompts/MODEL_SELECTOR.md（工程规则卡，非外部实验数据）。")
        return ("模型选择需核验组分、相态、压力、参数来源和适用范围。当前支持常压乙醇／水的条件性 NRTL 自主方案合成，以及显式理想性假设下的"
                "正庚烷/正壬烷二元 VLE 与 McCabe–Thiele；其他物系和模型需另行验证。未执行工艺计算。\n"
                "依据：engineering/prompts/MODEL_SELECTOR.md 与已注册计算工具。")


class ProcessDesignAdvisorAgent(HealthCoachAgent):
    def __init__(self, skills=None):
        super().__init__(name="Process Design Advisor",system_prompt=load_engineering_prompt("REPORT_WRITER"),simple_mode=True)
        self.skills = skills or ExpertSkillRegistry()

    def skill_context(self,state,gate,tool_name):
        return self.skills.context(state,gate,tool_name,'process_advisor')

    def explain(self, state):
        from ..reporting import render_report
        self.add_user_message(state.original_message)
        text = render_report(state)
        self.add_coach_message(text)
        return text

    def respond(self, user_message):
        return "Design advice requires a frozen engineering run; numerical values come only from its artifacts."
