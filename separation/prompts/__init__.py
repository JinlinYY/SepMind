"""Role-specific prompt templates, mirroring pha/prompts."""
from .common import COMMON
from .separation_design_prompts import DESIGN
from .process_simulation_prompts import SIMULATION
from .engineering_review_prompts import REVIEW

__all__ = ["COMMON", "DESIGN", "SIMULATION", "REVIEW"]
