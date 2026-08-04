"""
Omron PLC driver (OPC UA).

Two modes:
  - Gateway mode (default): connects to opc.tcp://<host>:4841/gateway/
      read    -> mirror ns (ns=3, state)     e.g. DataJig.Gantry
      write   -> command ns (ns=4, commands) e.g. JOB, fbMotorN.*, *_csv
      control -> self ns (ns=2)              e.g. Control.StopRequest / Emergency
  - Direct mode: straight to ns=4 on opc.tcp://192.168.1.100:4840 (only when a PLC slot is available)

Follows the notebook's opc_send/opc_read/jigjob logic exactly. The PLC program itself is untouched.
"""
import time

JIG_JOBS = ["Jig_Origin", "Jig_Readypos", "Jig_Insert", "Jig_Retrieve"]
EIS_JOBS = ["EIS_Insert", "EIS_Retrieve"]


class PLCClient:
    def __init__(self, url="opc.tcp://192.168.1.100:4840", namespace=4,
                 gateway=None, settle=0.2, simulation=False):
        self.url = url
        self.direct_ns = namespace
        self.gateway = gateway or {}
        self.use_gateway = bool(self.gateway.get("use_gateway", False))
        self.settle = settle
        self.simulation = simulation
        self.client = None
        self._ua = None
        self.connected = False
        # Namespaces resolved in connect()
        self.ns_read = namespace    # state reads
        self.ns_write = namespace   # command writes
        self.ns_self = None         # control nodes
        self._sim_gantry = ["Jig_Origin", "0"]

    @property
    def endpoint(self):
        if self.use_gateway:
            return self.gateway.get("url", "opc.tcp://127.0.0.1:4841/gateway/")
        return self.url

    # ---- Connection ----
    def connect(self):
        if self.simulation:
            self.connected = True
            return
        from opcua import Client, ua          # lazy import
        self._ua = ua
        self.client = Client(self.endpoint)
        self.client.connect()
        if self.use_gateway:
            self._resolve_gateway_ns()
        else:
            self.ns_read = self.ns_write = self.direct_ns
            self.ns_self = None
        self.connected = True

    def _resolve_gateway_ns(self):
        g = self.gateway

        def idx(uri, fallback):
            try:
                return self.client.get_namespace_index(uri)
            except Exception:
                return fallback

        self.ns_read = idx(g.get("uri_mirror", "http://lab/gateway/PLC"),
                           g.get("ns_mirror_fallback", 3))
        self.ns_write = idx(g.get("uri_cmd", "http://lab/gateway/Cmd"),
                            g.get("ns_cmd_fallback", 4))
        self.ns_self = idx(g.get("uri_self", "http://lab/gateway"),
                           g.get("ns_self_fallback", 2))

    def disconnect(self):
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.connected = False

    def _node(self, name, ns):
        return self.client.get_node(f"ns={ns};s={name}")

    # ---- Write (command ns) — same type handling as opc_send ----
    def send(self, node, value):
        if getattr(self, "read_only", False):
            return                              # read-only: block writes (backup guard)
        if self.simulation:
            if node == "JOB" and isinstance(value, (list, tuple)) and len(value) == 2:
                self._sim_gantry = [str(value[0]), str(value[1])]
            return
        ua = self._ua
        n = self._node(node, self.ns_write)
        time.sleep(self.settle)
        if isinstance(value, bool):
            n.set_value(ua.DataValue(ua.Variant(value, ua.VariantType.Boolean)))
        elif isinstance(value, int):
            n.set_value(ua.DataValue(ua.Variant(value, ua.VariantType.Int16)))
        elif isinstance(value, float):
            n.set_value(ua.DataValue(ua.Variant(value, ua.VariantType.Double)))
        elif isinstance(value, (list, tuple)):
            value = list(value)
            try:
                n.set_value(ua.DataValue(ua.Variant(value, ua.VariantType.Float)))
            except Exception:
                n.set_value(ua.DataValue(ua.Variant(value, ua.VariantType.String)))
        time.sleep(self.settle)

    # ---- Read (state mirror ns) — same as opc_read ----
    def read(self, node):
        if self.simulation:
            if node == "DataJig.Gantry":
                return list(self._sim_gantry)
            if node.startswith("DataOT2.Pipette"):
                return 0
            if node == "OT2_interlock":
                return True
            if node == "MotorSwitch":
                return False
            return None
        time.sleep(self.settle)
        return self._node(node, self.ns_read).get_value()

    # ---- Jig job trigger (same as jigjob) ----
    def jigjob(self, job, index=0):
        self.send("JOB", [job, str(index)])

    def read_gantry(self):
        return self.read("DataJig.Gantry")

    # ---- Motor parameters ----
    def set_motor_params(self, motors=(1, 2, 3, 4), vel=200.0, accel=200.0, decel=200.0,
                         power=True):
        for n in motors:
            self.send(f"fbMotor{n}.Power.bPowerEnable", bool(power))
        for n in motors:
            self.send(f"fbMotor{n}.MoveABS.rABSVel", float(vel))
            self.send(f"fbMotor{n}.MoveABS.rABSAccel", float(accel))
            self.send(f"fbMotor{n}.MoveABS.rABSDecel", float(decel))

    def set_power(self, enable, motors=(1, 2, 3, 4)):
        """Toggle motor power only (Power.bPowerEnable). For emergency stop — velocity/accel untouched."""
        for n in motors:
            self.send(f"fbMotor{n}.Power.bPowerEnable", bool(enable))

    def set_motor_relay(self, on):
        """Emergency-stop relay. fbMotorRelay=True makes the PLC cut motor power. False = release."""
        self.send("fbMotorRelay", bool(on))

    def read_motor_switch(self):
        """Physical emergency switch (MotorSwitch) state (external switch, read-only)."""
        try:
            return bool(self.read("MotorSwitch"))
        except Exception:
            return False

    def move_abs(self, motor, pos):
        self.send(f"fbMotor{motor}.MoveABS.rABSPos", float(pos))
        self.send(f"fbMotor{motor}.MoveABS.bABSEnable", True)

    # ---- Cell assembly motions ----
    def actu(self, index, wait=True):
        """Move the CCS actuator to a part position (notebook actu). CCSactu_Index + CCSactu_Check."""
        self.send("CCSactu_Index", int(index))
        time.sleep(0.2)
        self.send("CCSactu_Check", True)

    def actu_move(self, index, val, wait=True, verify=True, timeout=6.0, log=print):
        """Move the serial actuator (notebook actu_move). ActuIndex/ActuMove/Open_Serial.
        wait=True: wait for the robot to stop before sending (robot_check).
        verify=True: after sending, check Serial_Busy to confirm the command actually went out —
        if it did not, warn about a dropped command (does not abort)."""
        if wait:
            self._wait_robot_idle(log=log)
        self.send("ActuIndex", int(index))
        self.send("ActuMove", int(val))
        self.send("Open_Serial", True)
        time.sleep(0.2)
        if verify and not self._serial_went_busy(timeout=timeout):
            log(f"⚠ actu_move({index},{val}): Serial_Busy never went high — serial command likely dropped / actuator not moving")
            return False
        return True

    def _wait_robot_idle(self, warn_after=30.0, interval=0.3, log=print):
        """Wait indefinitely until Robot_moving and Robot_moving2 are both False (robot_check).
        After warn_after seconds it logs one warning and keeps waiting (never proceeds early)."""
        if self.simulation:
            return True
        waited = 0.0
        warned = False
        while True:
            try:
                if not (self.read("Robot_moving") or self.read("Robot_moving2")):
                    return True
            except Exception:
                return True
            time.sleep(interval)
            waited += interval
            if warn_after and not warned and waited >= warn_after:
                log(f"⚠ Waited {warn_after:.0f}s for the robot to stop — check Robot_moving (still waiting)")
                warned = True

    def _serial_went_busy(self, timeout=6.0, interval=0.2):
        """Check whether Serial_Busy goes high after Open_Serial (comms started). Returns False on Serial_Error."""
        if self.simulation:
            return True
        waited = 0.0
        while waited < timeout:
            try:
                if self.read("Serial_Error"):
                    return False
                if self.read("Serial_Busy"):
                    return True
            except Exception:
                pass
            time.sleep(interval)
            waited += interval
        return False

    def camera(self):
        """Trigger a ProdTracker camera capture (notebook camera). OPC: ProdTracker.Capture.bStart=True."""
        self.send("ProdTracker.Capture.bStart", True)

    def motor_up(self, motors=(1, 2, 3, 4)):
        """Raise the assembly stage motors (Motor1.bUp / Motor2.bUp)."""
        for n in motors:
            self.send(f"Motor{n}.bUp", True)

    def assem_aligncheck(self):
        self.send("bAssem_aligncheck", True)

    def plate_aligncheck(self):
        self.send("bPlate_aligncheck", True)

    def set_readypos_flag(self, on):
        """Write the ready-position confirmation flag (reset to False after cycler insertion)."""
        self.send("bAt_readypos", bool(on))

    def crimper_on(self):
        self.send("Crimper_On", True)

    def wait_crimper_done(self, should_run=None, warn_after=180.0, interval=1.0, log=print):
        """Wait indefinitely until Crimper_Done is True (notebook: while opc_read('Crimper_Done')).
        After warn_after seconds it logs one warning and keeps waiting (never proceeds early).
        Aborts when should_run() returns False."""
        if should_run is None:
            should_run = lambda: True
        if self.simulation:
            return True
        waited = 0.0
        warned = False
        while should_run():
            try:
                if self.read("Crimper_Done"):
                    return True
            except Exception:
                pass
            time.sleep(interval)
            waited += interval
            if warn_after and not warned and waited >= warn_after:
                log(f"⚠ Waiting {warn_after:.0f}s for Crimper_Done — check the crimper (still waiting)")
                warned = True
        return False

    def wait_readypos(self, should_run=None, warn_after=60.0, interval=0.5, log=print):
        """Wait indefinitely until bAt_readypos is True (notebook: while opc_read('bAt_readypos')).
        After warn_after seconds it logs one warning and keeps waiting (never proceeds early).
        Aborts when should_run() returns False. True = flag confirmed / False = stopped."""
        if should_run is None:
            should_run = lambda: True
        if self.simulation:
            return True
        waited = 0.0
        warned = False
        while should_run():
            try:
                if self.read("bAt_readypos"):
                    return True
            except Exception:
                pass
            time.sleep(interval)
            waited += interval
            if warn_after and not warned and waited >= warn_after:
                log(f"⚠ Waiting {warn_after:.0f}s for bAt_readypos — jig may not have reached ready position (still waiting)")
                warned = True
        return False

    # ---- Coordinate table upload ----
    def upload_coordinates(self, jig_positions, eis_positions):
        self.send("Jigmove_csv", jig_positions)
        self.send("EISmove_csv", eis_positions)

    # ---- Control nodes (gateway self ns) ----
    def read_self(self, path):
        if self.simulation or not self.use_gateway or self.ns_self is None:
            return None
        time.sleep(self.settle)
        return self._node(path, self.ns_self).get_value()

    def write_self(self, path, value):
        if self.simulation or not self.use_gateway or self.ns_self is None:
            return
        ua = self._ua
        node = self._node(path, self.ns_self)
        if isinstance(value, bool):
            node.set_value(ua.DataValue(ua.Variant(value, ua.VariantType.Boolean)))
        else:
            node.set_value(value)

