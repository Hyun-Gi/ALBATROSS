"""
Modbus assembly-robot driver (pymodbus). Port of the notebook's ModbusTcpClient + tcp().
Commands assembly motions through registers on 192.168.1.196:502.
* tcp() reports progress via the PLC's Robot_moving2, so that part only works when the
  gateway (PLC) is connected.
"""
import time


class RobotClient:
    def __init__(self, ip="192.168.1.196", port=502, enabled=True, simulation=False, plc=None):
        self.ip = ip
        self.port = port
        self.enabled = enabled
        self.simulation = simulation
        self.plc = plc                 # used to flag Robot_moving2 (via the gateway)
        self.client = None
        self.connected = False
        self._log = None

    def set_logger(self, fn):
        self._log = fn

    def connect(self):
        if not self.enabled:
            return
        if self.simulation:
            self.connected = True
            return
        from pymodbus.client import ModbusTcpClient      # lazy import
        self.client = ModbusTcpClient(self.ip, port=self.port)
        self.client.connect()
        self.connected = True

    def disconnect(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None
        self.connected = False

    def tcp(self, val, wait=True):
        """Write a command value to register 48 and wait for completion (notebook tcp).
        val = int or list."""
        if isinstance(val, int):
            val = [val]
        if getattr(self, "read_only", False):
            return                              # read-only: block writes
        if self._log:
            self._log(f"ROBOT ◀ tcp({val})")
        if self.simulation or not self.connected:
            return
        if wait and self.plc is not None and self.plc.connected:
            self.plc.send("Robot_moving2", True)
        self.client.write_registers(48, val)
        time.sleep(2)
        cnt = 0
        while True:
            time.sleep(0.2)
            if not self.client.read_coils(0).bits[0]:
                cnt += 1
            if cnt >= 3 and self.client.read_holding_registers(33).registers[0] == 2:
                break
        if wait and self.plc is not None and self.plc.connected:
            self.plc.send("Robot_moving2", False)

    def pressure(self, on=True):
        """Toggle the pressure gauge (write_coils 9)."""
        if getattr(self, "read_only", False):
            return                              # read-only: block writes
        if self._log:
            self._log(f"ROBOT ◀ pressure({on})")
        if self.simulation or not self.connected:
            return
        self.client.write_coils(9, bool(on))

    # ---- Pause / resume (xArm set_state via the Modbus Robot State register 33 = 0x21) ----
    #   The command-protocol PDF documents set_state(3) = 'Suspend the current motion' and
    #   set_state(0) = 'Enter the motion mode' (resume) — same as the pause button in Studio.
    #   In the standard Modbus register map, Robot State = holding register 33 (R/W) -> 3 = pause / 0 = resume.
    #   Coil 0x90 (144) 'isPaused' is not a command; use it read-only to tell whether we are currently paused.
    #   NOTE: if writing register 33 does not work on the hardware, fall back to the isPaused
    #   coil: write_coils(144, True/False).
    def pause(self):
        """Pause the robot (set_state(3) = Suspend). Stops the running motion/Blockly task in
        place, holding position."""
        if getattr(self, "read_only", False):
            return                              # read-only: block writes
        if self._log:
            self._log("ROBOT ◀ pause (set_state 3)")
        if self.simulation or not self.connected:
            return
        self.client.write_registers(33, [3])

    def resume(self):
        """Release the pause — continues from where it stopped (set_state(0))."""
        if getattr(self, "read_only", False):
            return                              # read-only: block writes
        if self._log:
            self._log("ROBOT ◀ resume (set_state 0)")
        if self.simulation or not self.connected:
            return
        self.client.write_registers(33, [0])

    def get_state(self):
        """Read Robot State (1 = moving, 2 = idle, 3 = paused, 4 = stopped)."""
        if self.simulation or not self.connected:
            return None
        try:
            return self.client.read_holding_registers(33).registers[0]
        except Exception:
            return None

    def is_paused(self):
        """Whether the robot is paused (Robot State == 3, with the isPaused coil 144 as a fallback)."""
        if self.simulation or not self.connected:
            return False
        try:
            if self.get_state() == 3:
                return True
            return bool(self.client.read_coils(144).bits[0])
        except Exception:
            return False
