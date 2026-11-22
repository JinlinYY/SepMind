"""Read declarative Notebook exemplars without executing notebook code."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .data_schemas import Contract, DesignProposal, ExecutionPlan, ReviewRecommendation


DEFAULT_DIRECTORY = Path(__file__).resolve().parents[3] / "few_shots/separation"
SCHEMAS = {"design": DesignProposal, "simulation": ExecutionPlan, "review": ReviewRecommendation}


class FewShotExample(Contract):
    example_id: str = Field(pattern=r"^sep_[a-z0-9_]+$")
    role: Literal["design", "simulation", "review"]
    phase: str = Field(min_length=1)
    title: str = Field(min_length=1)
    provenance: Literal["synthetic_illustration"] = "synthetic_illustration"
    expert_validated: bool = False
    context: dict[str, Any]
    response: dict[str, Any]

    @model_validator(mode="after")
    def response_contract(self):
        value = SCHEMAS[self.role].model_validate(self.response)
        if not set(value.evidence_ids).issubset(self.context.get("available_evidence_ids", [])):
            raise ValueError("Exemplar response must cite its own declared illustrative evidence IDs.")
        return self


class FewShotLibrary:
    """Lazy, bounded catalog of authored instructional examples.

    Parse JSON from cells marked separation_example. Markdown cells display the
    JSON in a fenced block. Existing raw cells remain supported. Hashes identify
    the exact example files used for each prompt. A library instance freezes its catalog.
    """

    def __init__(self, directory=None, max_examples_per_call=2):
        self.directory = Path(directory).resolve() if directory else DEFAULT_DIRECTORY
        if not 0 <= max_examples_per_call <= 3:
            raise ValueError("Use at most three role-specific examples per call.")
        self.max_examples_per_call = max_examples_per_call
        self._catalog = None

    def catalog(self):
        if self._catalog is not None:
            return deepcopy(self._catalog)
        if not self.directory.is_dir():
            raise FileNotFoundError(f"Few-shot notebook directory not found: {self.directory}")
        records, seen = [], set()
        files = sorted(self.directory.glob("*.ipynb"))
        if not files:
            raise ValueError("No chemical few-shot notebooks found.")
        if len(files) > 64:
            raise ValueError("Few-shot catalog exceeds 64 notebooks.")
        for path in files:
            raw = path.read_bytes()
            if len(raw) > 256000:
                raise ValueError(f"Few-shot notebook is too large: {path.name}")
            notebook = json.loads(raw.decode("utf-8"))
            found = 0
            for cell in notebook.get("cells", []):
                if not cell.get("metadata", {}).get("separation_example"):
                    continue
                cell_type = cell.get("cell_type")
                if cell_type not in {"raw", "markdown"}:
                    raise ValueError("Few-shot data must be in a raw JSON or fenced Markdown cell.")
                source = cell.get("source", [])
                source = source if isinstance(source, str) else "".join(source)
                if cell_type == "markdown":
                    lines = source.strip().splitlines()
                    if len(lines) < 3 or lines[0] != "```json" or lines[-1] != "```":
                        raise ValueError("Marked Markdown cells must contain a single JSON fence.")
                    source = "\n".join(lines[1:-1])
                if len(source) > 12000:
                    raise ValueError("Few-shot example exceeds the prompt size limit.")
                example = FewShotExample.model_validate_json(source)
                if example.example_id in seen:
                    raise ValueError(f"Duplicate few-shot ID: {example.example_id}")
                seen.add(example.example_id)
                records.append({"example": example.model_dump(), "file": path.name,
                                "sha256": hashlib.sha256(raw).hexdigest()})
                found += 1
            if found != 1:
                raise ValueError(f"Expected one marked JSON example per notebook: {path.name}")
        self._catalog = records
        return deepcopy(records)

    def select(self, role, phase):
        return [entry for entry in self.catalog()
                if entry["example"]["role"] == role and entry["example"]["phase"] == phase
                ][:self.max_examples_per_call]
