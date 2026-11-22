"""Load declarative few-shot examples as validated data."""

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


def _legacy_notebook_payload(text: str, path: Path) -> str:
    cells = [cell for cell in json.loads(text).get("cells", [])
             if cell.get("metadata", {}).get("separation_example")]
    if len(cells) != 1:
        raise ValueError(f"Expected one marked JSON example per notebook: {path.name}")
    cell = cells[0]
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
    return source


class FewShotLibrary:
    """Freeze a bounded catalog and record the hash of each source file."""

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
            raise FileNotFoundError(f"Few-shot example directory not found: {self.directory}")
        records, seen = [], set()
        files = sorted(path for path in self.directory.iterdir()
                       if path.is_file() and path.suffix in {".json", ".ipynb"})
        if not files:
            raise ValueError("No chemical few-shot example files found.")
        if len(files) > 64:
            raise ValueError("Few-shot catalog exceeds 64 example files.")
        for path in files:
            raw = path.read_bytes()
            if len(raw) > 256000:
                raise ValueError(f"Few-shot example file is too large: {path.name}")
            source = raw.decode("utf-8")
            if path.suffix == ".ipynb":
                source = _legacy_notebook_payload(source, path)
            if len(source) > 12000:
                raise ValueError("Few-shot example exceeds the prompt size limit.")
            example = FewShotExample.model_validate_json(source)
            if example.example_id in seen:
                raise ValueError(f"Duplicate few-shot ID: {example.example_id}")
            seen.add(example.example_id)
            records.append({"example": example.model_dump(), "file": path.name,
                            "sha256": hashlib.sha256(raw).hexdigest()})
        self._catalog = records
        return deepcopy(records)

    def select(self, role, phase):
        return [entry for entry in self.catalog()
                if entry["example"]["role"] == role and entry["example"]["phase"] == phase
                ][:self.max_examples_per_call]
