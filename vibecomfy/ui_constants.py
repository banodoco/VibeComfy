"""UI classification shared by bundle readers and emitters.

Keep this module dependency-free: reading a workflow bundle must not initialize
the emitter, ComfyUI nodes, or native numerical libraries.
"""

from __future__ import annotations


# Only non-executing canvas furniture belongs here. Preview/show classes remain
# semantic nodes: custom packs commonly implement them as auxiliary outputs,
# and canonical bundle emission must preserve their node identity.
UI_ONLY_CLASS_TYPES: frozenset[str] = frozenset(
    {"Note", "MarkdownNote", "Label (rgthree)"}
)
