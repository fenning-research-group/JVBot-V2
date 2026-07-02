from .jv_sweep import JV_SWEEP_CONTAINER as legacy_jv_sweep_container

PROTOCOL_CATALOG = {
    "legacy_jv_sweep": legacy_jv_sweep_container
}

__all__ = ["PROTOCOL_CATALOG"]

# from jvbot.measurement_methods import PROTOCOL_CATALOG
# executor = PROTOCOL_CATALOG["legacy_jv_sweep"].protocol_class()
# formatter = PROTOCOL_CATALOG["legacy_jv_sweep"].protocol_formatter()