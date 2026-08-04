"""EIS measurement trigger — built on top of BiologicClient. (Same as the notebook's ocv_eis)"""
from albatross.drivers.biologic import DEFAULT_EIS_PARAMS, DEFAULT_OCV_PARAMS


def measure(biologic, save_path, params=None, ocv_params=None, channel=None, log=None, tag=""):
    """Measure OCV -> run PEIS at that voltage -> save to save_path. Logs the OCV value when log/tag are given."""
    return biologic.measure_ocv_eis(
        save_path,
        params=params or dict(DEFAULT_EIS_PARAMS),
        ocv_params=ocv_params or dict(DEFAULT_OCV_PARAMS),
        channel=channel, log=log, tag=tag,
    )
