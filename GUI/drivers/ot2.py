"""
Opentrons OT-2 driver (SSH/paramiko). Based on the notebook's OT2 class.
Connects to the OT-2 over SSH and sends a single raw Python line (pr) into a
'python -i startup.py' session.
Connects directly to the OT-2 IP, independent of the PLC/gateway.
"""
import time


class OT2Client:
    def __init__(self, ip="192.168.1.6", ssh_key=r"C:\Users\HOME\ot2_ssh_key",
                 ssh_key_password="1234", username="root", enabled=True, simulation=False):
        self.ip = ip
        self.ssh_key = ssh_key
        self.ssh_key_password = ssh_key_password
        self.username = username
        self.enabled = enabled
        self.simulation = simulation
        self.ssh = None
        self.ssh_channel = None
        self.connected = False
        self._log = None       # command-log callback (injected by the GUI)

    def set_logger(self, fn):
        self._log = fn

    def connect(self):
        if not self.enabled:
            return
        if self.simulation:
            self.connected = True
            return
        import paramiko                       # lazy import
        k = paramiko.RSAKey.from_private_key_file(self.ssh_key, self.ssh_key_password)
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(hostname=self.ip, username=self.username, pkey=k,
                         disabled_algorithms={'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512']})
        self.ssh_channel = self.ssh.invoke_shell()
        self.ssh_channel.send('cd /var/lib/jupyter/notebooks\n'.encode()); time.sleep(0.3)
        self.ssh_channel.send('python -i startup.py\n'.encode()); time.sleep(0.3)
        self.connected = True

    def disconnect(self):
        try:
            if self.ssh:
                self.ssh.close()
        except Exception:
            pass
        self.ssh = None
        self.ssh_channel = None
        self.connected = False

    def raw(self, cmd):
        """Send one Python line to the OT-2 session (the notebook's pr). Always logged."""
        if getattr(self, "read_only", False):
            return                              # read-only: block writes
        if self._log:
            self._log(f"OT2 ◀ {cmd}")
        if self.simulation or not self.connected:
            return
        self.ssh_channel.send((str(cmd) + "\n").encode())

    # Notebook-compatible alias: pr = ot2.RawInput
    def RawInput(self, cmd):
        return self.raw(cmd)

    def get_output(self):
        if self.simulation or not self.connected:
            return "(sim) no output"
        if self.ssh_channel.recv_ready():
            return self.ssh_channel.recv(4096).decode(errors="ignore")
        if self.ssh_channel.recv_stderr_ready():
            return self.ssh_channel.recv_stderr(4096).decode(errors="ignore")
        return ""

    # ---- Basic control ----
    def set_temperature(self, celsius):
        self.raw(f"temp_mod.set_temperature(celsius={celsius})")

    def deactivate_temp(self):
        self.raw("temp_mod.deactivate()")

    def home(self):
        self.raw("protocol.home()")

    def rail_lights(self, on=True):
        self.raw(f"protocol.set_rail_lights({bool(on)})")

    def apply_offsets(self, offsets):
        """Apply labware calibration offsets (set_offset) in bulk. offsets = list of pr command strings."""
        for line in offsets or []:
            self.raw(line)


OT2 = OT2Client   # notebook-compatible alias
