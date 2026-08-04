"""Jig/motor motion triggers — built on top of PLCClient. (Same as the notebook's jigjob, etc.)"""


def jigjob(plc, job, index=0):
    plc.jigjob(job, index)


def origin(plc):              plc.jigjob("Jig_Origin")
def ready(plc):               plc.jigjob("Jig_Readypos")
def jig_insert(plc, ch):      plc.jigjob("Jig_Insert", ch)
def jig_retrieve(plc, ch):    plc.jigjob("Jig_Retrieve", ch)
def eis_insert(plc, ch):      plc.jigjob("EIS_Insert", ch)
def eis_retrieve(plc, ch):    plc.jigjob("EIS_Retrieve", ch)


def set_motors(plc, vel=200.0, accel=200.0, decel=200.0, power=True):
    plc.set_motor_params(vel=vel, accel=accel, decel=decel, power=power)


def move_abs(plc, motor, pos):
    plc.move_abs(motor, pos)


def load_coordinates_from_excel(plc, path):
    """Upload jig coordinates from Excel -> Jigmove_csv / EISmove_csv (same column layout as the notebook)."""
    import pandas as pd
    jig = pd.read_excel(path)
    jig_pos = jig.iloc[:, 1:7].values.tolist()
    eis_pos = jig.iloc[0:2, 7:11].values.tolist()
    plc.upload_coordinates(jig_pos, eis_pos)
    return len(jig_pos), len(eis_pos)


def dispose(plc, robot, channels, should_run=None, log=print):
    """Jig disposal — per channel: Jig_Retrieve -> Jig_Readypos -> wait for bAt_readypos ->
    tcp(20) -> reset flag. (Port of the notebook disposal loop.)
    should_run() allows stopping between channels."""
    if should_run is None:
        should_run = lambda: True
    chans = list(channels)
    log(f"Disposal started: channels {chans}")
    for i in chans:
        if not should_run():
            break
        log(f"--- Disposing channel {i} (Jig_Retrieve -> Readypos -> tcp(20)) ---")
        plc.jigjob("Jig_Retrieve", i)
        plc.jigjob("Jig_Readypos")
        # As in the original notebook, wait indefinitely for bAt_readypos to go True
        # (past the threshold it only warns; it never proceeds early)
        if not plc.wait_readypos(should_run=should_run, log=log):
            break                                    # left the wait via a stop -> skip tcp(20)
        robot.tcp([20])
        plc.set_readypos_flag(False)                 # bAt_readypos = False
    log("Disposal ended")
