"""Charge/discharge (Neware) tab: 48-channel status grid + start/continue."""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QGroupBox, QPushButton, QLabel, QSpinBox, QLineEdit,
                             QFileDialog)
from PyQt6.QtCore import Qt, QTimer
from albatross.workers.poller import StatusPoller


class NewareTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.cells = []
        self._polling = False
        v = QVBoxLayout(self)
        v.addWidget(self._grid_box())
        v.addWidget(self._control_box())
        v.addStretch(1)
        # Poller is created once and lives for the whole app session — the auto-refresh
        # button just calls resume()/pause() on this same thread (see _start_polling /
        # _stop_polling), it never tears it down and recreates it.
        self.poller = StatusPoller(self.main.neware, interval=5.0)
        self.poller.statuses.connect(self._update_grid)
        self.poller.failed.connect(lambda m: self.main.log("[Error] " + m))
        self.main._workers.add(self.poller)   # so closeEvent() calls stop()+wait() on app close
        self.poller.start()

    # 48-channel status grid (6 sub x 8 chl)
    def _grid_box(self):
        box = QGroupBox("Channel Status")
        outer = QVBoxLayout(box)
        grid = QGridLayout()
        n = self.main.cfg.get("neware", {}).get("channels", 48)
        for i in range(n):
            lbl = QLabel(f"{i}\n-")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(58, 40)
            lbl.setStyleSheet("border:1px solid #D3D1C7; border-radius:4px;")
            self.cells.append(lbl)
            grid.addWidget(lbl, i // 8, i % 8)
        outer.addLayout(grid)
        row = QHBoxLayout()
        self.btn_poll = QPushButton("Refresh Status (short press = once · long press = auto)")
        self.btn_poll.pressed.connect(self._poll_pressed)
        self.btn_poll.released.connect(self._poll_released)
        row.addWidget(self.btn_poll)
        row.addStretch(1)
        outer.addLayout(row)
        self._press_timer = QTimer(self)
        self._press_timer.setSingleShot(True)
        self._press_timer.timeout.connect(self._poll_longpress)
        self._longpressed = False
        return box

    # Short click = refresh once / long press (600 ms+) = turn auto-polling on.
    # A short click while auto-polling turns it off.
    def _poll_pressed(self):
        self._longpressed = False
        self._press_timer.start(600)

    def _poll_longpress(self):
        self._longpressed = True
        self._start_polling()

    def _poll_released(self):
        if self._press_timer.isActive():
            self._press_timer.stop()
        if self._longpressed:                 # just turned auto on via long press -> keep it
            self._longpressed = False
            return
        if self._polling:                     # short click while auto-refreshing -> stop
            self._stop_polling()
        else:                                 # otherwise a short click -> refresh once
            self._single_refresh()

    def _single_refresh(self):
        if not self.main.neware.connected:
            self.main.log("[Warning] Neware is not connected.")
            return
        self.main.log("Refreshing status once")
        self.main.run_task(self.main.neware.status_all, on_done=self._update_grid)

    def _start_polling(self):
        if self._polling:
            return
        if not self.main.neware.connected:
            self.main.log("[Warning] Neware is not connected.")
            return
        self._polling = True
        self.poller.resume()
        self.btn_poll.setText("Auto-refreshing (short click = stop)")
        self.main.log("Auto status refresh started (5 s interval)")

    def _stop_polling(self):
        self._polling = False
        self.poller.pause()
        self.btn_poll.setText("Refresh Status (short press = once · long press = auto)")
        self.main.log("Auto status refresh stopped")

    def _update_grid(self, statuses):
        for i, st in enumerate(statuses):
            if i >= len(self.cells):
                break
            self.cells[i].setText(f"{i}\n{st}")   # status text only, no color coding (working/pause/stop/finish)

    # Start / continue
    def _control_box(self):
        box = QGroupBox("Charge/Discharge Control")
        v = QVBoxLayout(box)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Protocol"))
        self.proto = QLineEdit("C:/NewareData/protocol.xml")
        r1.addWidget(self.proto)
        b_browse = QPushButton("Browse")
        b_browse.clicked.connect(self._browse_proto)
        r1.addWidget(b_browse)
        v.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Save Folder"))
        self.savedir = QLineEdit("C:/NewareData/")
        r2.addWidget(self.savedir)
        b_savedir = QPushButton("Browse")
        b_savedir.clicked.connect(self._browse_savedir)
        r2.addWidget(b_savedir)
        v.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Channel Range"))
        self.ch_from = QSpinBox(); self.ch_from.setRange(0, 47)
        self.ch_to = QSpinBox(); self.ch_to.setRange(0, 47); self.ch_to.setValue(5)
        r3.addWidget(self.ch_from)
        r3.addWidget(QLabel("~"))
        r3.addWidget(self.ch_to)
        b_start = QPushButton("Start")
        b_start.clicked.connect(self._start_range)
        r3.addWidget(b_start)
        b_pause = QPushButton("Pause")
        b_pause.clicked.connect(self._pause_range)
        r3.addWidget(b_pause)
        r3.addStretch(1)
        v.addLayout(r3)

        r3b = QHBoxLayout()
        r3b.addWidget(QLabel("Or enter directly"))
        self.ch_text = QLineEdit()
        self.ch_text.setPlaceholderText("e.g. 0,1,5,12  or  0-5,10-12   (leave empty to use the range above)")
        r3b.addWidget(self.ch_text)
        v.addLayout(r3b)

        r4 = QHBoxLayout()
        r4.addWidget(QLabel("Continue Channel"))
        self.cont_ch = QSpinBox(); self.cont_ch.setRange(0, 47)
        r4.addWidget(self.cont_ch)
        b_cont = QPushButton("Continue")
        b_cont.clicked.connect(self._continue_one)
        r4.addWidget(b_cont)
        r4.addStretch(1)
        v.addLayout(r4)
        return box

    def _browse_proto(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Protocol File", "", "XML (*.xml)")
        if path:
            self.proto.setText(path)

    def _browse_savedir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Save Folder")
        if path:
            self.savedir.setText(path)

    def _get_channels(self):
        """Parse the direct-entry field when filled (0,1,5 / 0-5,10-12); otherwise use the range
        (ch_from..ch_to). Only 0-47 are accepted."""
        text = self.ch_text.text().strip()
        if not text:
            return list(range(self.ch_from.value(), self.ch_to.value() + 1))
        try:
            chans = []
            for part in text.replace(" ", "").split(","):
                if not part:
                    continue
                if "-" in part:
                    a, b = part.split("-", 1)
                    chans.extend(range(int(a), int(b) + 1))
                else:
                    chans.append(int(part))
        except ValueError:
            self.main.log("[Warning] Invalid channel input format (e.g. 0,1,5,12 or 0-5,10-12)")
            return []
        chans = sorted(set(c for c in chans if 0 <= c <= 47))
        if not chans:
            self.main.log("[Warning] No valid channels (must be within 0-47).")
        return chans

    def _start_range(self):
        if not self.main.writable():        # read-only: block starting a charge/discharge run
            return
        if not self.main.neware.connected:
            self.main.log("[Warning] Neware is not connected.")
            return
        chans = self._get_channels()
        if not chans:
            return
        self.main.log(f"Charge/discharge started: channels {chans}")
        self.main.run_task(self.main.ctrl.start_cycling, chans,
                           self.proto.text(), self.savedir.text())

    def _pause_range(self):
        if not self.main.writable():        # read-only: pausing is a write, so it is blocked
            return
        if not self.main.neware.connected:
            self.main.log("[Warning] Neware is not connected.")
            return
        chans = self._get_channels()
        if not chans:
            return
        self.main.log(f"Charge/discharge paused: channels {chans}  — resumable via 'Continue'")
        self.main.run_task(self.main.ctrl.pause_cycling, chans)

    def _continue_one(self):
        if not self.main.writable():        # read-only: continuing is a write, so it is blocked
            return
        if not self.main.neware.connected:
            self.main.log("[Warning] Neware is not connected.")
            return
        self.main.log(f"Continue: channel {self.cont_ch.value()}")
        self.main.run_task(self.main.ctrl.continue_channel, self.cont_ch.value())
