"""
AI Weekly Model Configuration — extends the cmbagent model registry.

On import, this module loads backend/config/model_config.yaml and injects
the ``aiweekly`` workflow defaults into the cmbagent ModelRegistry singleton.
All other config (available_models, global_defaults, other workflows) comes
from the installed cmbagent package.

Usage:
    import backend.config.model_config  # side-effect: registers aiweekly defaults
    from cmbagent.config import get_model_registry

    registry = get_model_registry()
    defaults = registry.get_stage_defaults("aiweekly", 2)  # now works
"""

import logging
from pathlib import Path

import yaml

from cmbagent.config import get_model_registry

logger = logging.getLogger(__name__)

_LOCAL_CONFIG_PATH = Path(__file__).parent / "model_config.yaml"


def _inject_aiweekly_defaults() -> None:
    """Load local YAML and merge aiweekly workflow defaults into the registry."""
    try:
        with open(_LOCAL_CONFIG_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        logger.warning(
            "local model_config.yaml not found at %s — aiweekly defaults unavailable",
            _LOCAL_CONFIG_PATH,
        )
        return
    except Exception as exc:
        logger.error("failed to load local model_config.yaml: %s", exc)
        return

    local_workflows = raw.get("workflow_defaults", {})
    if not local_workflows:
        return

    registry = get_model_registry()
    for wf_name, wf_stages in local_workflows.items():
        if wf_name not in registry._workflow_defaults:
            registry._workflow_defaults[wf_name] = {}
        registry._workflow_defaults[wf_name].update(wf_stages)

    logger.info(
        "aiweekly_model_config_injected workflows=%s",
        list(local_workflows.keys()),
    )


# Auto-inject on import
_inject_aiweekly_defaults()
