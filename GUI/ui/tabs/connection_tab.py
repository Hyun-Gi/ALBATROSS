"""Connection tab: connect/disconnect each device + status."""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QGroupBox, QHBoxLayout,
                             QPushButton, QLabel)

# Clicked button = white background, unclicked button = grey (default style)
_BTN_WHITE = "background-color:#FFFFFF; color:#2C2C2A;"   # only the background turns white on click (size unchanged)


class ConnectionTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Connect each device. (In simulation mode, runs without real hardware.)"))
        v.addWidget(self._box("neware", "Neware Charger", main.neware))
        v.addWidget(self._box("plc", "Omron PLC (OPC UA)", main.plc))
        v.addWidget(self._box("biologic", "Biologic Potentiostat", main.biologic))
        v.addWidget(self._box("robot", "Robot Arm (Modbus)", main.robot))
        v.addWidget(self._box("ot2", "OT2 (Opentrons)", main.ot2))
        v.addStretch(1)

    def _box(self, key, title, client):
        box = QGroupBox(title)
        h = QHBoxLayout(box)
        if key == "ot2":
            left = QVBoxLayout()
            note = QLabel("CHECK IF THE LED IS ON")
            note.setStyleSheet("color:#D32F2F; font-weight:bold;")
            left.addWidget(note)                       # top: notice text
            left.addWidget(QLabel(self._info(key)))    # bottom: IP
            h.addLayout(left)
        else:
            h.addWidget(QLabel(self._info(key)))
        h.addStretch(1)
        btn_c = QPushButton("ON")
        btn_d = QPushButton("OFF")
        btn_c.setFixedWidth(54)
        btn_d.setFixedWidth(54)

        def do_connect():
            self.main.log(f"Connecting to {title}...")
            btn_c.setStyleSheet(_BTN_WHITE); btn_d.setStyleSheet("")   # ON clicked -> white
            self.main.set_pill(key, "connecting")
            if key == "ot2":
                w = self.main.run_task(self.main.ctrl.connect_ot2, log=self.main.log, busy=btn_c,
                                       on_done=lambda _r: self._on_connected(key, title))
            else:
                w = self.main.run_task(client.connect, busy=btn_c,
                                       on_done=lambda _r: self._on_connected(key, title))
            w.failed.connect(lambda m: self.main.set_pill(key, False))

        def do_disconnect():
            btn_d.setStyleSheet(_BTN_WHITE); btn_c.setStyleSheet("")   # OFF clicked -> white
            try:
                (client.disconnect if hasattr(client, "disconnect") else client.close)()
            except Exception as e:
                self.main.log(f"[error] {e}")
            self.main.set_pill(key, False)
            self.main.log(f"{title} disconnected")

        btn_c.clicked.connect(do_connect)
        btn_d.clicked.connect(do_disconnect)
        h.addWidget(btn_c)
        h.addWidget(btn_d)
        return box

    def _on_connected(self, key, title):
        self.main.set_pill(key, True)
        self.main.log(f"{title} connected")

    def _info(self, key):
        c = self.main.cfg.get(key, {})
        if key == "neware":
            return f"{c.get('host')}:{c.get('port')}"
        if key == "plc":
            return c.get("url", "")
        return c.get("ip", "")
