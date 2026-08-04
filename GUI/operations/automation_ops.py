"""Automation operations — move a paused Neware cell to EIS, measure it, and return it
(the core cycle_server logic).

- process_cell     : handle one paused cell
- run_cycle_server : blocking loop (shared by Jupyter, scripts, and the worker)
"""
import os
import time
import datetime
from albatross.operations import jig_ops, eis_ops


def wait_gantry(plc, job, index, should_run, equal=True, interval=1.0):
    """Wait until DataJig.Gantry equals (job, index) — or, with equal=False, until it no longer
    does. Stays responsive to stop requests."""
    while should_run():
        time.sleep(interval)
        g = plc.read_gantry()
        if not g:
            continue
        match = (g[0] == job and g[1] == str(index))
        if equal and match:
            return True
        if not equal and not match:
            return True
    return False


def process_cell(neware, plc, biologic, ch, eis_jig, directory,
                 params, ocv_params, should_run, log=print,
                 settle_move=15, interval=1.0):
    """One paused cell: retrieve -> insert into EIS -> measure -> return -> resume.
    Returns the save path."""
    sub, chl = neware.index_to_subchl(ch)
    log(f"pause detected: {sub}-{chl} (ch {ch})")

    jig_ops.jig_retrieve(plc, ch)
    jig_ops.eis_insert(plc, eis_jig)
    if not wait_gantry(plc, "Jig_Retrieve", ch, should_run, interval=interval):
        return None
    if not wait_gantry(plc, "EIS_Insert", eis_jig, should_run, interval=interval):
        return None
    time.sleep(settle_move)   # travel time from origin to the EIS channel

    os.makedirs(directory, exist_ok=True)
    today = datetime.datetime.now().strftime("%y%m%d%H%M%S")
    save_path = "{}/{}_{}({}-{}).csv".format(directory, today, ch, sub, chl)

    tag = "{}_{}({}-{})".format(datetime.datetime.now().strftime("%y%m%d"), ch, sub, chl)
    eis_ops.measure(biologic, save_path, params, ocv_params, channel=eis_jig, log=log, tag=tag)

    jig_ops.eis_retrieve(plc, eis_jig)
    jig_ops.jig_insert(plc, ch)
    if not wait_gantry(plc, "Jig_Insert", ch, should_run, interval=interval):
        return save_path
    if not wait_gantry(plc, "Jig_Insert", ch, should_run, equal=False, interval=interval):
        return save_path

    neware.continue_(sub, chl)
    log(f"{sub}-{chl} Resume Charge/Discharge")
    return save_path


def run_cycle_server(neware, plc, biologic, directory, check_ch, eis_jig=1,
                     params=None, ocv_params=None, should_run=None, log=print,
                     on_measured=None, settle_move=15, poll_interval=1.0):
    """Blocking automation loop. Shared by the GUI worker, Jupyter, and scripts.

    Jupyter: omit should_run (always True) -> stop with a kernel interrupt (■ / Ctrl+C).
    GUI:     should_run=lambda: worker._running, on_measured=signal.emit.
    """
    if should_run is None:
        should_run = lambda: True
    os.makedirs(directory, exist_ok=True)
    check_ch = list(check_ch)
    log(f"Automation started — monitoring {len(check_ch)} channel(s)")
    try:
        while should_run():
            time.sleep(poll_interval)
            for ch in check_ch:
                if not should_run():
                    break
                sub, chl = neware.index_to_subchl(ch)
                if neware.status(sub, chl) != "pause":
                    continue
                path = process_cell(neware, plc, biologic, ch, eis_jig, directory,
                                    params, ocv_params, should_run=should_run, log=log,
                                    settle_move=settle_move, interval=poll_interval)
                if path and on_measured:
                    on_measured(ch, path)
    except KeyboardInterrupt:
        log("Interrupted by user (KeyboardInterrupt)")
    log("Automation ended")
