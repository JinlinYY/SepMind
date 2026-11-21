# Derived from Google Health PHA, Apache-2.0; see LICENSE.txt and docs/engineering/UPSTREAM_BASE.md.
# Only shared behavior used by the separation-design extension remains active.
from typing import Any, Dict

class HealthCoachAgent:
    """PHA conversation-memory base; historical name retained for inheritance."""
    def __init__(self, name="Process Advisor", system_prompt=None, simple_mode=True):
        self.name=name
        self.system_prompt=system_prompt or "Explain only source-backed engineering results."
        self.simple_mode=simple_mode
        self.conv_context=""
        self.conv_utterances=""
        self.prompts={key:"" for key in ("goal","constraints","considered","profile","rec","finish")}
        self.memory={key:"" for key in self.prompts}
        self.num_turns=0
        self.avg_user_words_per_turn=0.0
        self.avg_coach_words_per_turn=0.0
        self.finish_flag=False
        self.rec_flag=False

    def add_user_message(self, message: str) -> None:
            """Add a user message to the conversation history.

            Args:
                message: The user's message.
            """
            self._update_conv_state("User", message)

    def add_coach_message(self, message: str) -> None:
            """Add a coach message to the conversation history.

            Args:
                message: The coach's message.
            """
            self._update_conv_state("Coach", message)

    def _update_conv_state(self, agent_name: str, utterance: str) -> None:
            """Update conversation state with a new utterance.

            Args:
                agent_name: "User" or "Coach"
                utterance: The message text.
            """
            word_count = len(utterance.split())

            if agent_name == "User":
                self.avg_user_words_per_turn = (
                    self.avg_user_words_per_turn * self.num_turns + word_count
                ) / (self.num_turns + 1) if self.num_turns > 0 else word_count
                self.conv_utterances += f"\nUser: {utterance}"
            elif agent_name == "Coach":
                self.avg_coach_words_per_turn = (
                    self.avg_coach_words_per_turn * self.num_turns + word_count
                ) / (self.num_turns + 1) if self.num_turns > 0 else word_count
                self.conv_utterances += f"\nCoach: {utterance}"
                self.num_turns += 1

    def reset_conversation(self) -> None:
            """Reset the conversation state."""
            self.conv_context = ""
            self.conv_utterances = ""
            self.memory = {key: "" for key in self.prompts.keys()}
            self.num_turns = 0
            self.avg_user_words_per_turn = 0.0
            self.avg_coach_words_per_turn = 0.0
            self.finish_flag = False
            self.rec_flag = False

    def get_stats(self) -> Dict[str, Any]:
            """Get conversation statistics.

            Returns:
                Dictionary of conversation stats.
            """
            return {
                "num_turns": self.num_turns,
                "avg_user_words_per_turn": self.avg_user_words_per_turn,
                "avg_coach_words_per_turn": self.avg_coach_words_per_turn,
                "memory_states": {k: len(v) for k, v in self.memory.items()},
            }
