"""Compatibility imports; numerical tools now live in separation/tools."""
from .tools.dwsim import BinaryVLERequest, DwsimBackend, ShortcutDistillationRequest
__all__ = ["BinaryVLERequest", "DwsimBackend", "ShortcutDistillationRequest"]
