from .jv_sweep import JV_SWEEP_CONTAINER as legacy_jv_sweep_container
from .voc_direct import VOC_DIRECT_CONTAINER as voc_direct_container
from .voc_buffered import VOC_BUFFERED_CONTAINER as voc_buffered_container
from .jsc_direct import JSC_DIRECT_CONTAINER as jsc_direct_container
from .jsc_buffered import JSC_BUFFERED_CONTAINER as jsc_buffered_container
from .spo_buffered import SPO_BUFFERED_CONTAINER as spo_buffered_container

PROTOCOL_CATALOG = {
    "jv_sweep": legacy_jv_sweep_container,
    "voc_direct": voc_direct_container,
    "voc_buffered": voc_buffered_container,
    "jsc_direct": jsc_direct_container,
    "jsc_buffered": jsc_buffered_container,
    "spo_buffered": spo_buffered_container
}

__all__ = ["PROTOCOL_CATALOG"]

# from jvbot.measurement_methods import PROTOCOL_CATALOG
# executor = PROTOCOL_CATALOG["jv_sweep"].protocol_class()
# formatter = PROTOCOL_CATALOG["jv_sweep"].protocol_formatter()