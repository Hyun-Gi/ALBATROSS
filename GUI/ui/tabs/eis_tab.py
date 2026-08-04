"""EIS measurement tab: params form + one-shot OCV/EIS measurement + Nyquist plot."""
import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QGroupBox, QPushButton, QLineEdit, QSpinBox,
                             QDoubleSpinBox, QCheckBox, QFileDialog, QLabel)
from albatross.drivers.biologic import DEFAULT_EIS_PARAMS, DEFAULT_OCV_PARAMS

try:                        # without matplotlib only the plot is disabled (the tab still works)
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    _HAS_MPL = True
except Exception:
    _HAS_MPL = False


class EisTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        root = QHBoxLayout(self)
        left = QWidget()
        left.setMaximumWidth(270)             # keep the left controls narrow (does not grow with the window)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self._param_box())
        lv.addWidget(self._run_box())
        lv.addStretch(1)
        root.addWidget(left, 0)               # narrow fixed-width sidebar
        root.addWidget(self._plot_box(), 1)   # all remaining space — the Nyquist plots

    def _param_box(self):
        box = QGroupBox("EIS Parameters")
        form = QFormLayout(box)
        d = DEFAULT_EIS_PARAMS
        self.amp = self._dspin(d["amplitude_voltage"], 0, 10, 3)
        self.f_init = self._dspin(d["initial_frequency"], 0, 1e7, 1)
        self.f_final = self._dspin(d["final_frequency"], 0, 1e7, 3)
        self.f_num = self._ispin(d["frequency_number"], 1, 200)
        self.repeat = self._ispin(d["repeat"], 1, 100)
        self.wait = self._dspin(d["wait"], 0, 100, 2)
        form.addRow("Amplitude Voltage [V]", self.amp)
        form.addRow("Initial Frequency [Hz]", self.f_init)
        form.addRow("Final Frequency [Hz]", self.f_final)
        form.addRow("Frequency Count", self.f_num)
        form.addRow("Repeat", self.repeat)
        form.addRow("wait", self.wait)
        return box

    def _run_box(self):
        box = QGroupBox("Measurement")
        v = QVBoxLayout(box)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("EIS Channel"))
        self.channel = QSpinBox(); self.channel.setRange(0, 1)
        self.channel.setValue(self.main.cfg.get("biologic", {}).get("eis_channel", 1))
        r1.addWidget(self.channel); r1.addStretch(1)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Save Path"))
        self.save_path = QLineEdit("C:/EIS/test.csv")
        r2.addWidget(self.save_path)
        b_browse = QPushButton("Browse")
        b_browse.clicked.connect(self._browse)
        r2.addWidget(b_browse)
        v.addLayout(r2)
        self.btn_run = QPushButton("Measure OCV / EIS")
        self.btn_run.clicked.connect(self._run)
        v.addWidget(self.btn_run)
        return box

    def _plot_box(self):
        box = QGroupBox("Nyquist — Latest Measurement (auto)")
        v = QVBoxLayout(box)
        r = QHBoxLayout()
        r.addWidget(QLabel("EIS Folder"))
        self.eis_folder = QLineEdit("C:/EIS/")
        r.addWidget(self.eis_folder)
        b_fd = QPushButton("Browse"); b_fd.clicked.connect(self._browse_folder)
        r.addWidget(b_fd)
        b_open = QPushButton("Open File (new window)"); b_open.clicked.connect(self._open_file)
        r.addWidget(b_open)
        r.addStretch(1)
        v.addLayout(r)
        self._popups = []
        if _HAS_MPL:
            self.lbl_auto = QLabel("Auto — latest measurement (refreshes on each measurement)")
            v.addWidget(self.lbl_auto)
            self.fig_auto = Figure(figsize=(6, 6)); self.canvas_auto = FigureCanvas(self.fig_auto)
            self.ax_auto = self.fig_auto.add_subplot(111); self._style_ax(self.ax_auto)
            v.addWidget(self.canvas_auto)
        else:
            self.canvas_auto = None
            v.addWidget(QLabel("matplotlib not installed — plotting disabled (pip install matplotlib)"))
        return box

    def _style_ax(self, ax):
        ax.set_xlabel("Z' (Ω)"); ax.set_ylabel("-Z'' (Ω)"); ax.grid(True)
        try:
            ax.set_box_aspect(1)                             # square box (equal 0..max scaling is applied in _draw)
        except Exception:
            pass

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Path", "", "CSV (*.csv)")
        if path:
            self.save_path.setText(path)

    def _params(self):
        p = dict(DEFAULT_EIS_PARAMS)
        p.update(amplitude_voltage=self.amp.value(),
                 initial_frequency=self.f_init.value(),
                 final_frequency=self.f_final.value(),
                 frequency_number=self.f_num.value(),
                 repeat=self.repeat.value(), wait=self.wait.value())
        return p

    def _run(self):
        if not self.main.writable():        # read-only: an EIS measurement is a write, so it is blocked
            return
        if not self.main.biologic.connected:
            self.main.log("[Warning] Biologic is not connected.")
            return
        import datetime
        tag = "{}_ch{}".format(datetime.datetime.now().strftime("%y%m%d"), self.channel.value())
        self.main.run_task(
            self.main.ctrl.measure_eis, self.save_path.text(),
            params=self._params(), ocv_params=dict(DEFAULT_OCV_PARAMS),
            channel=self.channel.value(), log=self.main.log, tag=tag, busy=self.btn_run,
            on_done=self._plot_nyquist)

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select EIS Folder")
        if path:
            self.eis_folder.setText(path)

    def _plot_nyquist(self, result):
        """Measurement-complete callback — plots the newest file in the folder for a real run,
        or a demo curve in simulation."""
        self.main.log(f"Measurement complete: {result}")
        if not _HAS_MPL or self.canvas_auto is None:
            return
        if isinstance(result, dict) and result.get("sim"):
            self._plot_demo()
        else:
            self._plot_latest()

    def _plot_latest(self):
        """Plot the most recently created csv in the selected EIS folder into the left (auto) panel."""
        if not _HAS_MPL or self.canvas_auto is None:
            return
        import glob
        folder = self.eis_folder.text().strip()
        files = glob.glob(os.path.join(folder, "*.csv"))
        if not files:
            self.main.log(f"[Info] No csv files found in '{folder}'.")
            return
        path = max(files, key=os.path.getctime)          # most recently created file
        fname = os.path.basename(path)
        folder_name = os.path.basename(os.path.normpath(folder))
        self.lbl_auto.setText(f"Auto — [{folder_name}] {fname}")
        self.main.log(f"Nyquist (auto): {fname}")
        self._draw(self.ax_auto, self.fig_auto, self.canvas_auto, path, fname)

    def _open_file(self):
        """Pick a file and show its Nyquist plot in a new popup window (for comparison/review)."""
        if not _HAS_MPL:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open EIS csv",
                                              self.eis_folder.text().strip(), "CSV (*.csv)")
        if not path:
            return
        self._popup_nyquist(path)

    def _popup_nyquist(self, path):
        from PyQt6.QtWidgets import QDialog
        dlg = QDialog(self)
        dlg.setWindowTitle(os.path.basename(path))
        dlg.resize(560, 560)
        lay = QVBoxLayout(dlg)
        fig = Figure(figsize=(6, 6)); canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111); self._style_ax(ax)
        lay.addWidget(canvas)
        self._draw(ax, fig, canvas, path, os.path.basename(path))
        self._popups.append(dlg)                                     # prevent garbage collection
        dlg.finished.connect(lambda _r, d=dlg: self._popups.remove(d) if d in self._popups else None)
        dlg.show()                                                   # modeless (several can be open at once)

    def _draw(self, ax, fig, canvas, path, title):
        """CSV -> compute Z (same as the notebook's Zcal) -> Nyquist on the given axes."""
        try:
            import numpy as np, pandas as pd
            df = pd.read_csv(path, header=1)              # header=1
            if "Impedance modulus" not in df.columns or "Impedance phase" not in df.columns:
                self.main.log(f"[Info] {os.path.basename(path)} does not look like an EIS file (no Impedance columns)")
                return
            Z = df["Impedance modulus"].values * np.exp(1j * df["Impedance phase"].values)
            x = Z.real; y = -Z.imag
            ax.clear()
            ax.scatter(x, y, s=12)
            ax.set_title(title, fontsize=9)
            self._style_ax(ax)
            m = float(max(x.max(), y.max(), 1.0)) * 1.05      # start at 0 + identical x/y range (square, equal scale)
            ax.set_xlim(0, m); ax.set_ylim(0, m)
            fig.tight_layout()
            canvas.draw()
        except Exception as e:
            self.main.log(f"[Error] Nyquist plot ({os.path.basename(path)}): {e}")

    def _plot_demo(self):
        import numpy as np
        w = np.logspace(-1, 5, 40)
        Z = 20 + 120.0 / (1 + 1j * w * 120 * 1e-5)
        x = Z.real; y = -Z.imag
        self.ax_auto.clear()
        self.ax_auto.scatter(x, y, s=12)
        self.ax_auto.set_title("(simulation demo)", fontsize=9)
        self._style_ax(self.ax_auto)
        m = float(max(x.max(), y.max(), 1.0)) * 1.05
        self.ax_auto.set_xlim(0, m); self.ax_auto.set_ylim(0, m)
        self.fig_auto.tight_layout()
        self.canvas_auto.draw()

    @staticmethod
    def _dspin(val, lo, hi, dec):
        s = QDoubleSpinBox(); s.setRange(lo, hi); s.setDecimals(dec); s.setValue(val)
        return s

    @staticmethod
    def _ispin(val, lo, hi):
        s = QSpinBox(); s.setRange(lo, hi); s.setValue(int(val))
        return s
