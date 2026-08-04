"""
Biologic potentiostat driver (easy_biologic).
A direct port of the notebook's ocv_eis() logic (measure OCV -> apply as initial voltage -> PEIS).
"""
import time
import random

# Default EIS measurement parameters (notebook params)
DEFAULT_EIS_PARAMS = {
    "voltage": -3.56,            # automatically replaced by the measured OCV
    "amplitude_voltage": 0.01,
    "initial_frequency": 200000,
    "final_frequency": 0.1,
    "frequency_number": 39,
    "duration": 0,
    "vs_initial": False,
    "repeat": 2,
    "wait": 0.1,
}
# Default OCV measurement parameters (notebook params_ocv)
DEFAULT_OCV_PARAMS = {"time": 2, "time_interval": 1}


class BiologicClient:
    def __init__(self, ip="192.168.1.128", easy_biologic_path=None,
                 eis_channel=1, simulation=False):
        self.ip = ip
        self.easy_biologic_path = easy_biologic_path
        self.eis_channel = eis_channel
        self.simulation = simulation
        self.bl = None
        self.blp = None
        self.connected = False

    def connect(self):
        if self.simulation:
            self.connected = True
            return
        import sys
        if self.easy_biologic_path:
            sys.path.append(self.easy_biologic_path)
        import easy_biologic as ebl
        import easy_biologic.base_programs as blp
        self.blp = blp
        self.bl = ebl.BiologicDevice(self.ip)
        self.bl.connect()
        self.connected = True

    def disconnect(self):
        if self.bl:
            try:
                self.bl.disconnect()
            except Exception:
                pass
        self.bl = None
        self.connected = False

    def measure_ocv_eis(self, save_path, params=None, ocv_params=None, channel=None,
                        log=None, tag=""):
        """Measure OCV, then run EIS (PEIS) using that voltage as the initial voltage and save to
        save_path. If log is given, records the OCV value and 'EIS measurement started' with tag."""
        params = dict(params or DEFAULT_EIS_PARAMS)
        ocv_params = dict(ocv_params or DEFAULT_OCV_PARAMS)
        channel = self.eis_channel if channel is None else channel

        if self.simulation:
            time.sleep(1)
            voc = round(random.uniform(-3.6, -3.4), 4)
            if log:
                log(f"{tag}  OCV value : {voc:.3f} V")
                log(f"{tag}  EIS measurement started...")
            return {"voltage": voc, "save_path": save_path, "sim": True}

        # --- OCV ---
        ocv = self.blp.OCV(self.bl, ocv_params, channels=[channel])
        ocv.run()
        voc = {ch: [d.voltage for d in data] for ch, data in ocv.data.items()}
        voc = {ch: sum(v) / len(v) for ch, v in voc.items()}
        params["voltage"] = list(voc.values())[0]
        if log:
            log(f"{tag}  OCV value : {params['voltage']:.3f} V")
            log(f"{tag}  EIS measurement started...")

        # --- PEIS ---
        peis = self.blp.PEIS(self.bl, params, channels=[channel])
        peis.run()
        peis.save_data(save_path)
        return {"voltage": params["voltage"], "save_path": save_path}
