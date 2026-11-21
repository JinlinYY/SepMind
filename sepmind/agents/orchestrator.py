# Derived from Google Health PHA, Apache-2.0; see LICENSE.txt and docs/engineering/UPSTREAM_BASE.md.
# Only shared behavior used by the separation-design extension remains active.
import copy
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional
ORCHESTRATOR_PREAMBLE="Coordinate registered engineering tools and expert evidence."
AGENT_NAME_DATA_SCIENCE="data_science_agent"
AGENT_NAME_DOMAIN_EXPERT="domain_expert_agent"
AGENT_NAME_HEALTH_COACH="health_coach_agent"

class MultiAgentOrchestrator:
    def __init__(
            self,
            name: str = "Expert-guided Separation Team",
            system_prompt: Optional[str] = None,
            debug_verbose: bool = False,
        ):
            """Initialize the orchestrator.

            Args:
                name: Name for the orchestrator.
                system_prompt: Custom system prompt (uses default if None).
                debug_verbose: If True, print debug information.
            """
            self.name = name
            self.system_prompt = system_prompt or ORCHESTRATOR_PREAMBLE
            self.debug_verbose = debug_verbose

            # Agent references
            self.data_science_agent = None
            self.domain_expert_agent = None
            self.health_coach_agent = None
            self.multi_agent_team: Dict[str, Any] = {}
            self.agent_name_list: List[str] = []

            # Team structure state
            self.main_agent = ""
            self.supporting_agents = ""
            self.supporting_agents_complete = ""
            self.collaboration_workflow = ""

            # Conversation state
            self.conv_context = ""
            self.conv_utterances = ""
            self.question_last = ""

            # Memory states
            self.memory = {
                "topic": "",
                "goal": "",
                "finish_desc": "",
                "data_science_agent_insights": "",
                "domain_expert_agent_insights": "",
                "health_coach_agent_insights": "",
            }

            # Reflection state
            self.flag_reflection_mode = False
            self.reflection_round_counter = 0
            self.reflection_round_upper_bound = 1
            self.rephrase_prompt_record: Dict[str, List[str]] = {}

            # Stats
            self.log_number_of_turns = 0

            # LLM configuration
            self._client = None
            self._model_name = "deepseek-flash"
            self._temperature = 0.7

    def configure(self, api_key=None, provider=None, model_name=None, temperature=0.7, gemini_api_key=None):
        """Reuse PHA configuration/factory while enforcing DeepSeek-only execution."""
        if gemini_api_key:
            raise ValueError("Engineering LLM provider must be DeepSeek")
        from ..llm.config import get_config, configure_global
        from ..llm.backend_multimodel import get_llm_backend
        provider=provider or get_config().provider
        if provider not in ('deepseek','qwen'):raise ValueError("Engineering LLM provider must be DeepSeek or Qwen")
        configure_global(provider=provider,api_key=api_key,model_name=model_name,temperature=temperature)
        self._backend=get_llm_backend(backend_type=provider,api_key=api_key,model_name=model_name,temperature=temperature)
        return self

    def set_agents(
            self,
            data_science_agent=None,
            domain_expert_agent=None,
            health_coach_agent=None,
        ) -> "MultiAgentOrchestrator":
            """Set the agent team.

            Args:
                data_science_agent: DataScienceAgent instance.
                domain_expert_agent: DomainExpertAgent instance.
                health_coach_agent: HealthCoachAgent instance.

            Returns:
                Self for chaining.
            """
            self.multi_agent_team = {}

            if data_science_agent is not None:
                self.data_science_agent = data_science_agent
                self.multi_agent_team[AGENT_NAME_DATA_SCIENCE] = data_science_agent

            if domain_expert_agent is not None:
                self.domain_expert_agent = domain_expert_agent
                self.multi_agent_team[AGENT_NAME_DOMAIN_EXPERT] = domain_expert_agent

            if health_coach_agent is not None:
                self.health_coach_agent = health_coach_agent
                self.multi_agent_team[AGENT_NAME_HEALTH_COACH] = health_coach_agent
                # Save initial system prompt for coach
                self._health_coach_initial_prompt = copy.deepcopy(
                    health_coach_agent.system_prompt
                )

            self.agent_name_list = list(self.multi_agent_team.keys())

            # Always log which agents are registered
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"\n{'═' * 60}")
            print(f"🤖 [{timestamp}] ORCHESTRATOR AGENTS REGISTERED")
            print(f"   Available agents: {self.agent_name_list}")
            print(f"   data_science_agent: {'✓' if data_science_agent else '✗'}")
            print(f"   domain_expert_agent: {'✓' if domain_expert_agent else '✗'}")
            print(f"   health_coach_agent: {'✓' if health_coach_agent else '✗'}")
            print(f"{'═' * 60}\n")

            return self

    def _call_llm(self, prompt: str, max_retries: int = 3) -> str:
            """Call the orchestrator's LLM.

            Args:
                prompt: The prompt to send.
                max_retries: Maximum number of retries.

            Returns:
                Model response text.
            """
            for attempt in range(max_retries):
                try:
                    if self._backend:
                        return self._backend.generate(prompt)
                    else:
                        return "Error: LLM not configured. Call configure() first."
                except Exception as e:
                    if self.debug_verbose:
                        print(f"LLM call attempt {attempt + 1} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                    else:
                        traceback.print_exc()
                        return f"Error: {e}"

            return "Error: All retry attempts failed."

    def _clear_json_format(self, text: str) -> str:
            """Clean JSON response from LLM.

            Args:
                text: Raw LLM response.

            Returns:
                Cleaned JSON string.
            """
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            return text.strip()

    def get_conversation_history(self) -> str:
            """Get the full conversation history."""
            return self.conv_context + "\n" + self.conv_utterances

    def add_user_message(self, message: str) -> None:
            """Add a user message to the conversation."""
            self.conv_utterances += f"\nUser: {message}"
            self.question_last = message

    def add_response(self, response: str) -> None:
            """Add an orchestrator response to the conversation."""
            self.conv_utterances += f"\nAssistant: {response}"

    def reset_conversation(self) -> None:
            """Reset the conversation state."""
            self.conv_context = ""
            self.conv_utterances = ""
            self.question_last = ""
            self.memory = {k: "" for k in self.memory}
            self.main_agent = ""
            self.supporting_agents = ""
            self.supporting_agents_complete = ""
            self.collaboration_workflow = ""
            self.log_number_of_turns = 0
            self.rephrase_prompt_record = {}

            # Reset health coach conversation if present
            if self.health_coach_agent:
                self.health_coach_agent.reset_conversation()
