# ALBATROSS GUI

The EIS automation that used to be run cell by cell in a Jupyter notebook, moved into a PyQt6 GUI.
The existing PLC (Sysmac) program and OPC UA settings are **left untouched**; the same global
variables are read and written through the gateway.

## Connection layout
```
PyQt GUI ──(opcua client)──> Gateway :4841 ──(1 slot)──> Omron PLC :4840 (ns=4)
                              ├ ns=2  Run/Cell/Control/Biologic (coordination)
                              ├ ns=3  PLC.* status mirror  (read)   e.g. DataJig.Gantry
                              └ ns=4  Cmd.* commands       (write)  e.g. JOB, fbMotorN.*, *_csv
```
The PLC's OPC UA slots are full, so the GUI cannot attach to the PLC directly and only ever
talks to **the gateway**.

## Layout
```
ALBATROSS_GUI/
├── main.py                  # GUI entry point
├── gateway.py               # ★ OPC UA aggregating gateway (uses 1 PLC slot)
├── config.yaml              # IPs/nodes/simulation + gateway section
├── requirements.txt
└── albatross/
    ├── drivers/  neware.py · plc.py · biologic.py   # notebook logic, unchanged
    ├── workers/  base.py · poller.py · automation.py # QThread (keeps the GUI from freezing)
    └── ui/       main_window.py · tabs/              # connection/jig/Neware/EIS/automation
```

## Startup order
1) Gateway (on a PC that can talk to the PLC):
```
pip install asyncua
python gateway.py
```
2) GUI:
```
pip install -r requirements.txt
python main.py
```
- Out of the box `app.simulation: true` in `config.yaml`, so the window opens **without any
  hardware or gateway**.
- For real use: set `app.simulation: false` and point `gateway.url` at the gateway PC's address
  (on the same PC that is `opc.tcp://127.0.0.1:4841/gateway/`).

## Using it from Jupyter (triggers only, no GUI)
Run the GUI (`python main.py`) from a terminal. In Jupyter, import the **Controller instead of the
GUI** and call the triggers cell by cell (same as the old notebook workflow, just with cleaner code).

```python
import sys, os; sys.path.insert(0, os.path.abspath("."))   # run from ALBATROSS_GUI
from albatross.config import load_config
from albatross.controller import Controller

ctrl = Controller.build(load_config()); ctrl.connect_all()
ctrl.jig_retrieve(12)                              # jig
ctrl.measure_eis("C:/EIS/test.csv", channel=1)     # EIS
ctrl.start_cycling(range(0,6), "proto.xml", "C:/NewareData/")  # charge/discharge
ctrl.run_automation("C:/EIS/", check_ch=range(48)) # automation (blocking; interrupt the kernel to stop)
```
Ready-to-run notebook: `examples/albatross_jupyter.ipynb`.
Script version: `examples/run_triggers.py` (`python examples/run_triggers.py`).

## OPC UA nodes the GUI uses (via the gateway)
- Write (ns=4 Cmd): `JOB` (jig movement), `fbMotor1~4.*` (motors), `Jigmove_csv`/`EISmove_csv` (coordinates)
- Read (ns=3 mirror): status such as `DataJig.Gantry`
- Coordination (ns=2 self): `Control.StopRequest` / `Control.Emergency` (used by the emergency stop button)

## Changes made to gateway.py (existing behaviour preserved)
- **Command nodes added**: `JOB` (String array), 24 motors, and `Jigmove_csv`/`EISmove_csv` (2D)
  are created under a separate `ns=4` (Cmd) → no conflict with the existing status mirror (ns=3).
  They are passed to the PLC write-through.
- **Duplicate node guard**: `bPlate_aligncheck` appeared twice in `PLC_MIRROR_NODES` and crashed
  startup; duplicates are now skipped.
- Command nodes are created even when the PLC is not connected (so the GUI/gateway can be tested alone).

## Safety
- **Emergency stop** at the top: halts automation, sets `Control.Emergency`/`StopRequest`, and tries to cut motor power.
- The automation loop checks `Control.StopRequest` every cycle, so it can also be stopped from outside.
- All hardware operations run on background threads → the window stays responsive during measurement/motion.
