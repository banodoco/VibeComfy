"""The canonical, read-only workflow requirements plan.

This producer describes desired actions. It never grants authority or applies
them. Agent orchestration re-reads its existing consent/grant authority and
recomputes this plan before using the controlled installers and transfers.
"""
from ._plan import plan, plan_digest

__all__ = ["plan", "plan_digest"]
