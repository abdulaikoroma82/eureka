"""Application layer: configuration, workflow controller and entry points.

To avoid import cycles (``config`` is imported very early by the engine),
this package init stays lightweight.  Import the heavier objects directly:

    from xlsform_studio.app.workflow import Workflow
    from xlsform_studio.app.config import CONFIG
"""

__all__ = ["Workflow", "WorkflowResult", "CONFIG", "Settings"]


def __getattr__(name):  # PEP 562 lazy attribute access
    if name in ("Workflow", "WorkflowResult"):
        from .workflow import Workflow, WorkflowResult
        return {"Workflow": Workflow, "WorkflowResult": WorkflowResult}[name]
    if name in ("CONFIG", "Settings"):
        from .config import CONFIG, Settings
        return {"CONFIG": CONFIG, "Settings": Settings}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
