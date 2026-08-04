"""
Controller — bundles the three drivers (Neware/PLC/Biologic) and exposes high-level "triggers".
Both the GUI and scripts only need to call this object's methods (the motion logic lives in operations).
"""
from albatross.drivers.neware import NewareClient
from albatross.drivers.plc import PLCClient
from albatross.drivers.biologic import BiologicClient
from albatross.drivers.robot import RobotClient
from albatross.drivers.ot2 import OT2Client
from albatross.operations import jig_ops, cycler_ops, eis_ops, automation_ops


class Controller:
    def __init__(self, neware, plc, biologic, robot=None, ot2=None, cfg=None):
        self.neware = neware
        self.plc = plc
        self.biologic = biologic
        self.robot = robot
        self.ot2 = ot2
        self.cfg = cfg or {}
        self._recipe_df = None
        self._result_df = None

    @classmethod
    def build(cls, cfg):
        """Build the drivers from a config dict and create a Controller."""
        sim = cfg.get("app", {}).get("simulation", True)
        plc = PLCClient(simulation=sim, **_plc_kwargs(cfg))
        return cls(
            NewareClient(simulation=sim, **_neware_kwargs(cfg)),
            plc,
            BiologicClient(simulation=sim, **_biologic_kwargs(cfg)),
            RobotClient(simulation=sim, plc=plc, **_robot_kwargs(cfg)),
            OT2Client(simulation=sim, **_ot2_kwargs(cfg)),
            cfg=cfg,
        )

    # ---- Connection ----
    def connect_all(self, log=print):
        for name, c in (("Neware", self.neware), ("PLC", self.plc),
                        ("Biologic", self.biologic), ("Robot", self.robot),
                        ("OT2", self.ot2)):
            try:
                c.connect()
                log(f"{name} " + ("connected" if getattr(c, "connected", False) else "disabled/not connected"))
            except Exception as e:
                log(f"[error] {name} connection failed: {e}")

    def disconnect_all(self):
        for c in (self.ot2, self.robot, self.biologic, self.plc, self.neware):
            try:
                (c.disconnect if hasattr(c, "disconnect") else c.close)()
            except Exception:
                pass

    # ---- Jig/motor triggers ----
    def jigjob(self, job, index=0):      jig_ops.jigjob(self.plc, job, index)

    def jigjob_checked(self, job, index=0, timeout=15, log=print):
        """Send a jig command, then verify DataJig.Gantry reflects it.
        If it does not within the timeout, log a warning that the command may have been
        dropped (motor did not move)."""
        import time
        self.plc.jigjob(job, index)
        waited = 0.0
        while waited < timeout:
            g = self.plc.read_gantry()
            if g and g[0] == job and str(g[1]) == str(index):
                return True
            time.sleep(0.5)
            waited += 0.5
        log(f"⚠ {job}({index}): gantry did not update within {timeout}s — the command may have been dropped or the motor did not move")
        return False
    def origin(self):                    jig_ops.origin(self.plc)
    def ready(self):                     jig_ops.ready(self.plc)
    def jig_insert(self, ch):            jig_ops.jig_insert(self.plc, ch)
    def jig_retrieve(self, ch):          jig_ops.jig_retrieve(self.plc, ch)
    def eis_insert(self, ch):            jig_ops.eis_insert(self.plc, ch)
    def eis_retrieve(self, ch):          jig_ops.eis_retrieve(self.plc, ch)
    def dispose_channels(self, channels, should_run=None, log=print):
        """Jig disposal — dispose each channel in turn (Jig_Retrieve -> Readypos -> tcp(20) -> reset flag)."""
        jig_ops.dispose(self.plc, self.robot, channels, should_run=should_run, log=log)
    def set_motors(self, vel=200.0, accel=200.0, decel=200.0, power=True):
        jig_ops.set_motors(self.plc, vel, accel, decel, power)
    def move_abs(self, motor, pos):      jig_ops.move_abs(self.plc, motor, pos)
    def upload_coordinates(self, excel_path):
        return jig_ops.load_coordinates_from_excel(self.plc, excel_path)
    def power_off(self):                 self.plc.set_power(False)
    def power_on(self):                  self.plc.set_power(True)
    def motor_estop(self):               self.plc.set_motor_relay(True)    # emergency stop (relay)
    def motor_estop_release(self):       self.plc.set_motor_relay(False)   # release emergency stop
    def read_motor_switch(self):         return self.plc.read_motor_switch()

    # ---- Modbus robot triggers ----
    def robot_tcp(self, val):            self.robot.tcp(val)
    def robot_pressure(self, on=True):   self.robot.pressure(on)
    def robot_pause(self):               self.robot.pause()      # xArm pause (state=3)
    def robot_resume(self):              self.robot.resume()     # resume (state=0)
    def robot_is_paused(self):           return self.robot.is_paused()

    # ---- OT-2 triggers ----
    def ot2_raw(self, cmd):              self.ot2.raw(cmd)
    def ot2_set_temp(self, celsius):     self.ot2.set_temperature(celsius)
    def ot2_deactivate_temp(self):       self.ot2.deactivate_temp()
    def ot2_home(self):                  self.ot2.home()
    def ot2_get_output(self):            return self.ot2.get_output()

    def connect_ot2(self, log=print, timeout=120):
        """OT2 connection sequence:
          1) SSH connect
          2) rail lights ON  -> turning these on makes the PLC raise OT2_interlock to True
          3) wait until OT2_interlock is True (read through the gateway)
          4) once True, apply the 9 offsets
        Reading OT2_interlock requires the gateway (PLC) to be connected first.
        """
        import time
        self.ot2.connect()
        log("OT2 connected — rail lights ON")
        self.ot2.rail_lights(True)

        if not self.plc.connected:
            log("[warning] gateway (PLC) not connected — cannot check OT2_interlock. Applying offsets immediately.")
        else:
            log("Waiting for OT2_interlock to go True...")
            ok = False
            waited = 0.0
            while waited < timeout:
                try:
                    if self.plc.read("OT2_interlock"):
                        ok = True
                        break
                except Exception:
                    pass
                time.sleep(0.5)
                waited += 0.5
            if not ok:
                log(f"[warning] OT2_interlock timed out ({timeout}s) — skipping offset application")
                return
            log("OT2_interlock confirmed True -> applying offsets")

        offsets = self.cfg.get("ot2", {}).get("offsets", [])
        self.ot2.apply_offsets(offsets)
        log(f"Applied {len(offsets)} OT2 offset(s)")
    def set_tiprack(self, p0, p1):
        self.plc.send("DataOT2.Pipette0", int(p0))
        self.plc.send("DataOT2.Pipette1", int(p1))

    def dose_range(self, n_start, n_end, heated=True, should_run=None, log=print, result_df=None,
                   on_comp_start=None, on_comp_done=None):
        from albatross.operations import ot2_ops
        if result_df is None:
            result_df = self.get_result_df()
        ot2_ops.formulate_range(self.ot2, self.plc, result_df, self.plate_mapping(heated),
                                n_start, n_end, should_run=should_run, log=log,
                                on_comp_start=on_comp_start, on_comp_done=on_comp_done)

    # ---- Formulation data (computed by sodium_formulator) ----
    def set_recipe_csv(self, path):
        """Change the recipe CSV path and invalidate the cache (recomputed from the new file on next use)."""
        self.cfg.setdefault("ot2", {})["recipe_csv"] = path
        self._recipe_df = None
        self._result_df = None

    def get_recipe_df(self):
        """Load the source recipe CSV (x, ratio_*) — cached."""
        if self._recipe_df is None:
            import pandas as pd
            self._recipe_df = pd.read_csv(self.cfg.get("ot2", {}).get("recipe_csv"))
        return self._recipe_df

    def get_result_df(self):
        """Dispense-amount table computed by sodium_formulator (cached). Index 0..N-1 = composition number."""
        if self._result_df is None:
            from albatross.operations import formulation
            si = self.cfg.get("ot2", {}).get("solvent_info", {})
            self._result_df = formulation.build_result_df(self.get_recipe_df(), si)
        return self._result_df

    def required_amounts(self, n_start, n_end, include_zero=False):
        """Total amount (uL) needed per component for compositions n_start..n_end.
        include_zero=True also includes 0 µL components."""
        from albatross.operations import formulation
        return formulation.required_amounts(self.get_result_df(), n_start, n_end, include_zero=include_zero)

    def plate_mapping(self, heated=True):
        key = "plate_mapping_heated" if heated else "plate_mapping_room"
        return self.cfg.get("ot2", {}).get(key, {})

    # ---- Charge/discharge (Neware) triggers ----
    def start_cycling(self, channels, protocol, savedir, backup=None, skip=()):
        return cycler_ops.start_channels(self.neware, channels, protocol, savedir, backup, skip)
    def continue_channel(self, ch):      return cycler_ops.continue_channel(self.neware, ch)
    def pause_cycling(self, channels, skip=()):
        return cycler_ops.pause_channels(self.neware, channels, skip)
    def status_all(self):                return cycler_ops.status_all(self.neware)
    def status(self, ch):                return cycler_ops.status(self.neware, ch)

    # ---- EIS measurement trigger ----
    def measure_eis(self, save_path, **kw):
        return eis_ops.measure(self.biologic, save_path, **kw)

    # ---- Automation trigger (blocking; for Jupyter/scripts) ----
    def run_automation(self, directory, check_ch=range(48), eis_jig=None,
                       params=None, ocv_params=None, should_run=None,
                       log=print, on_measured=None, settle_move=15, poll_interval=1.0):
        eis_jig = self.biologic.eis_channel if eis_jig is None else eis_jig
        return automation_ops.run_cycle_server(
            self.neware, self.plc, self.biologic, directory, check_ch,
            eis_jig=eis_jig, params=params, ocv_params=ocv_params,
            should_run=should_run, log=log, on_measured=on_measured,
            settle_move=settle_move, poll_interval=poll_interval)

    # ---- Cell assembly automation trigger (blocking; for the worker/scripts) ----
    def run_assembly(self, mode="assembly", n=1, dosing_list=None, plate_info="wellplate",
                     ccs=None, jig_pos=None, protocol=None, savedir=None, backup=None,
                     dispense=None, dst_well=None, should_run=None, log=print,
                     on_step_fail=None, on_cell_start=None, on_cell_done=None):
        """mode='assembly' (assembly only) or 'cycle' (assembly + cycling).
        The vision step_check is configured under config(vision)."""
        from albatross.operations import assembly_ops, vision
        acfg = self.cfg.get("assembly", {})
        vcfg = self.cfg.get("vision", {})
        if dispense is None:
            dispense = tuple(acfg.get("dispense", [70, 90]))
        if dst_well is None:
            dst_well = acfg.get("dst_well", "plate2['A1']")
        step_check = vision.make_step_check(vcfg, on_fail=on_step_fail, log=log,
                                            enabled=(mode == "assembly"))
        return assembly_ops.run_assembly(
            self.plc, self.robot, self.ot2, self.neware,
            mode=mode, n=n, dosing_list=dosing_list or [], plate_info=plate_info,
            ccs=ccs, jig_pos=jig_pos, protocol=protocol, savedir=savedir, backup=backup,
            dispense=dispense, dst_well=dst_well,
            should_run=should_run, log=log, step_check=step_check,
            notify=lambda m: vision.notify_done(vcfg, m, log=log),
            on_cell_start=on_cell_start, on_cell_done=on_cell_done)


# ---- config -> driver kwargs ----
def _neware_kwargs(cfg):
    n = cfg.get("neware", {})
    return dict(host=n.get("host", "127.0.0.1"), port=n.get("port", 502),
                dev_ip=n.get("dev_ip", "192.168.1.2"), devtype=n.get("devtype", 25),
                devid=n.get("devid", 40), channels=n.get("channels", 48))


def _plc_kwargs(cfg):
    p = cfg.get("plc", {})
    return dict(url=p.get("url", "opc.tcp://192.168.1.100:4840"),
                namespace=p.get("namespace", 4), gateway=cfg.get("gateway"))


def _biologic_kwargs(cfg):
    b = cfg.get("biologic", {})
    return dict(ip=b.get("ip", "192.168.1.128"),
                easy_biologic_path=b.get("easy_biologic_path"),
                eis_channel=b.get("eis_channel", 1))


def _robot_kwargs(cfg):
    r = cfg.get("robot", {})
    return dict(ip=r.get("ip", "192.168.1.196"), port=r.get("port", 502),
                enabled=r.get("enabled", True))


def _ot2_kwargs(cfg):
    o = cfg.get("ot2", {})
    return dict(ip=o.get("ip", "192.168.1.6"),
                ssh_key=o.get("ssh_key", r"C:\\Users\\HOME\\ot2_ssh_key"),
                ssh_key_password=o.get("ssh_key_password", "1234"),
                enabled=o.get("enabled", True))
