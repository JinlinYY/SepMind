# Derived from Google Health PHA, Apache-2.0; see LICENSE.txt and docs/engineering/UPSTREAM_BASE.md.
# Only shared behavior used by the separation-design extension remains active.
class DataScienceAgent:
    """PHA calculation-role base, specialized by EngineeringCalculationAgent.

    Free-form code generation and clinical dataframe handling are removed; the
    engineering subclass executes registered typed tools only.
    """
    def __init__(self, llm_backend=None):
        self.llm=llm_backend
        self.python_sandbox=None
        self.num_code_retries=3
        self.total_code_retries=5
        self.max_code_update_cycles=1
