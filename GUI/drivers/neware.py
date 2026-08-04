"""
Neware cycler driver (TCP socket + BTS XML).
Wraps the existing Jupyter notebook's newaresend/neware_start/neware_check/... logic in a class,
unchanged.
"""
import socket
import time
import re
import random
import threading


class NewareClient:
    def __init__(self, host="127.0.0.1", port=502, dev_ip="192.168.1.2",
                 devtype=25, devid=40, channels=48, timeout=2.0, simulation=False):
        self.host = host
        self.port = port
        self.dev_ip = dev_ip
        self.devtype = devtype
        self.devid = devid
        self.channels = channels
        self.timeout = timeout
        self.simulation = simulation
        self.sock = None
        self.connected = False
        # Multiple QThreads (StatusPoller, TaskWorker for start/pause/continue, ...) can call
        # into this client at the same time. They all share one TCP socket, so only one
        # send+recv round trip may be in flight at once — this lock serializes them.
        self._lock = threading.Lock()

    # ---- Connection ----
    def connect(self):
        if self.simulation:
            self.connected = True
            return
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        self.sock.settimeout(self.timeout)
        self.connected = True

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self.connected = False

    # ---- Low-level send/receive (same as the notebook's newaresend/newarerecv) ----
    def _send(self, cmd: str):
        self.sock.send(cmd.encode("utf-8") + b"#\r\n#\r\n")

    def _recv(self) -> str:
        return self.sock.recv(20000).decode("utf-8")

    # ---- Index conversion (0-47 -> subid, chlid) ----
    @staticmethod
    def index_to_subchl(i: int):
        return i // 8 + 1, i % 8 + 1

    # ---- Start a charge/discharge run (neware_start) ----
    def start(self, subid, chlid, protocol_path, savedir, savename, backup, filetype=0):
        if getattr(self, "read_only", False):
            return "[read-only] write blocked"
        if self.simulation:
            return f"[SIM] start {subid}-{chlid} ({protocol_path})"
        with self._lock:
            self._send('''<?xml version="1.0" encoding="UTF-8" ?>
<bts version="1.0">
 <cmd>start</cmd>
 <list count = "1">
  <start ip="{ip}" devtype="{dt}" devid="{did}" subdevid="{sub}" chlid="{chl}" >{proto}</start>
<backup backupdir="{save}" remotedir="{bk}" filenametype="2" customfilename="{name}" addtimewhenrepeat="0" filetype="{ft}" />
 </list>
</bts>'''.format(ip=self.dev_ip, dt=self.devtype, did=self.devid, sub=subid, chl=chlid,
                 proto=protocol_path, save=savedir, bk=backup, name=savename, ft=filetype))
            time.sleep(1)
            return self._recv()

    # ---- Resume (neware_continue) ----
    def continue_(self, subid, chlid):
        if getattr(self, "read_only", False):
            return "[read-only] write blocked"
        if self.simulation:
            return f"[SIM] continue {subid}-{chlid}"
        with self._lock:
            self._send('''<?xml version="1.0" encoding="UTF-8" ?>
<bts version="1.0">
<cmd>continue</cmd>
<list count = "1">
<continue ip="{ip}" devtype="{dt}" devid="{did}" subdevid="{sub}" chlid="{chl}" >true</continue>
</list>
</bts>'''.format(ip=self.dev_ip, dt=self.devtype, did=self.devid, sub=subid, chl=chlid))
            time.sleep(1)
            return self._recv()

    # ---- Pause (neware_pause) ----
    def pause(self, subid, chlid):
        if getattr(self, "read_only", False):
            return "[read-only] write blocked"
        if self.simulation:
            return f"[SIM] pause {subid}-{chlid}"
        with self._lock:
            self._send('''<?xml version="1.0" encoding="UTF-8" ?>
<bts version="1.0">
<cmd>pause</cmd>
<list count = "1">
<pause ip="{ip}" devtype="{dt}" devid="{did}" subdevid="{sub}" chlid="{chl}" >true</pause>
</list>
</bts>'''.format(ip=self.dev_ip, dt=self.devtype, did=self.devid, sub=subid, chl=chlid))
            time.sleep(1)
            return self._recv()

    # ---- Single-channel status (neware_check) ----
    def status(self, subid, chlid):
        if self.simulation:
            return random.choice(["working", "working", "working", "finish", "pause"])
        with self._lock:
            self._send('''<?xml version="1.0" encoding="UTF-8" ?>
<bts version="1.0">
<cmd>getchlstatus</cmd>
<list count = "1">
<status ip="{ip}" devtype="{dt}" devid="{did}" subdevid="{sub}" chlid="{chl}" >true</status>
</list>
</bts>'''.format(ip=self.dev_ip, dt=self.devtype, did=self.devid, sub=subid, chl=chlid))
            time.sleep(1)
            rv = self._recv()
        for key in ("finish", "working", "stop", "pause"):
            if key in rv:
                return key
        return rv

    # ---- All-channel status (neware_checkall) ----
    def status_all(self):
        if self.simulation:
            return [random.choice(["working", "finish", "stop", "pause"])
                    for _ in range(self.channels)]
        items = []
        for i in range(self.channels):
            sub, chl = self.index_to_subchl(i)
            items.append(
                '<status ip="{ip}" devtype="{dt}" devid="{did}" subdevid="{sub}" chlid="{chl}">true</status>'.format(
                    ip=self.dev_ip, dt=self.devtype, did=self.devid, sub=sub, chl=chl))
        body = ('<?xml version="1.0" encoding="UTF-8" ?><bts version="1.0">'
                '<cmd>getchlstatus</cmd><list count = "{}">{}</list></bts>'.format(
                    self.channels, "".join(items)))
        with self._lock:
            self._send(body)
            time.sleep(1)
            rv = self._recv()
        return re.findall(r'<status[^>]*>(\w+)</status>', rv)
