"""
Cell assembly automation — port of the notebook assembly loop.

Two modes (assembly itself is shared; only post-crimping handling differs):
  - "assembly" : return the finished cell to the rack (tcp 300, ...) -> notify when done
  - "cycle"    : insert into the cycler + neware_start (begin charge/discharge)

Devices: PLC (actu/actu_move/camera/crimper) - robot (tcp) - OT2 (dosing) - Neware (cycle start).
step_check (vision) is injected as a callback — passes when the module/CNN is missing.
On a mismatch, on_fail pauses the GUI.
"""
import datetime

from albatross.operations import ot2_ops


def _noop(*_a, **_k):
    return True


def build_dosing_list(dosing_num, repeat_num, n):
    """Build a list of length n (rounded down) from num_wellplate starting at dosing_num,
    repeating each composition repeat_num times.

    Same as the notebook:
      dosing_list = flatten([[num_wellplate[i]]*repeat_num
                             for i in range(dosing_num, dosing_num + n//repeat_num)])
    (If n is not a multiple of repeat_num it rounds down, so the result may be shorter than n.)
    """
    wells = ot2_ops.NUM_WELLPLATE
    repeat_num = max(1, int(repeat_num))
    n_comps = int(n) // repeat_num
    out = []
    for i in range(int(dosing_num), int(dosing_num) + n_comps):
        if 0 <= i < len(wells):
            out += [wells[i]] * repeat_num
    return out


def build_jig_pos(jig_num, n, jig_list=None):
    """Cycler jig positions = jig_list[jig_num : jig_num+n] (same as the notebook).
    jig_list defaults to 0..47. (Faulty jigs are filtered out beforehand via config assembly.jig_exclude.)"""
    if jig_list is None:
        jig_list = list(range(48))
    return list(jig_list[int(jig_num):int(jig_num) + int(n)])


def _dispense_electrolyte(ot2, plc, plate_info, well, dst_well,
                          ul_aspirate, ul_dispense, log):
    """Electrolyte dosing (the notebook's dosing block). rail lights OFF -> dose -> ON -> safety (wait for interlock)."""
    ot2.raw("protocol.set_rail_lights(False)")
    tip = ot2_ops.pipette(plc, log)
    ot2.raw("left_tip.pick_up_tip({}.wells()[{}])".format(tip[0], tip[1]))
    ot2.raw("left_tip.aspirate({}, {}['{}'])".format(ul_aspirate, plate_info, well))
    ot2.raw("left_tip.air_gap(20)")
    ot2.raw("left_tip.touch_tip(location = {}['{}'], radius=1, v_offset=-7, speed = 50 )".format(plate_info, well))
    ot2.raw("left_tip.dispense({}, {})".format(ul_dispense, dst_well))
    ot2.raw("left_tip.drop_tip()")
    ot2.raw("protocol.set_rail_lights(True)")
    ot2_ops.safety(plc, log=log)


def _assemble_one(plc, robot, ot2, i, comp, plate_info, ccs,
                  dispense, dst_well, step_check, log):
    """Assemble one cell (up to crimping). Feed parts -> align -> dose -> stack."""
    # (1) Feed the part
    plc.actu(ccs + i + 1)
    # (2) Raise the stage + alignment check (can, separator)
    plc.motor_up((1, 2))
    robot.tcp([8]); plc.assem_aligncheck()
    plc.camera(); step_check("can", comp, i)
    robot.tcp([9]); plc.camera(); plc.assem_aligncheck()
    plc.camera(); step_check("separator", comp, i)
    # (3) Electrolyte dosing
    _dispense_electrolyte(ot2, plc, plate_info, comp, dst_well,
                          dispense[0], dispense[1], log)
    # (4) Stack (cathode, spacer, spring, cap)
    robot.tcp([10]); plc.camera(); step_check("cathode", comp, i)
    robot.tcp([11]); plc.camera(); step_check("spacer", comp, i)
    robot.tcp([12]); plc.camera(); step_check("spring", comp, i)
    robot.tcp([13]); plc.camera(); step_check("cap", comp, i)
    robot.tcp([14]); plc.camera()


def _insert_to_cycler(plc, robot, neware, pos, protocol, savedir, backup, log, should_run=None):
    """Mode B: insert the finished cell into the cycler jig + align + neware_start (begin charge/discharge)."""
    plc.jigjob("Jig_Readypos")
    plc.jigjob("Jig_Insert", pos)
    plc.wait_readypos(should_run=should_run, log=log)
    # The cell can bounce and fail to seat -> alignment step
    robot.tcp([300, 103])
    plc.plate_aligncheck()
    import time
    time.sleep(1)
    robot.tcp([153, 302])
    plc.set_readypos_flag(False)          # reset the ready-position confirmation
    sub = pos // 8 + 1
    chl = pos % 8 + 1
    now = datetime.datetime.now().strftime("%y%m%d")
    if neware is not None:
        neware.start(sub, chl, protocol, savedir, f"{now}_{sub}-{chl}", backup)
    log(f"Inserted into cycler + charge/discharge started: pos {pos} (sub {sub}, chl {chl})")


def run_assembly(plc, robot, ot2, neware, *, mode="assembly", n=1, dosing_list=None,
                 plate_info="wellplate", ccs=None, jig_pos=None, protocol=None,
                 savedir=None, backup=None, dispense=(70, 90), dst_well="plate2['A1']",
                 should_run=None, log=print, step_check=None, notify=None,
                 on_cell_start=None, on_cell_done=None):
    """Cell assembly automation loop (blocking). Shared by the GUI worker and Jupyter.

    mode="assembly": assembly only (return to rack) / mode="cycle": assembly + cycling
    (insert into cycler + neware_start).
    The first cell is crimped only; the last cell also retrieves/inserts itself
    (the pipeline runs one step behind).
    """
    should_run = should_run or (lambda: True)
    step_check = step_check or _noop
    on_cell_start = on_cell_start or _noop
    on_cell_done = on_cell_done or _noop
    dosing_list = list(dosing_list or [])
    if ccs is None:
        ccs = 12 - n
    if savedir:
        import os
        os.makedirs(savedir, exist_ok=True)
        if backup:
            os.makedirs(backup, exist_ok=True)

    log(f"Assembly automation started — mode {mode}, {n} cell(s)")
    first = True
    for i in range(n):
        if not should_run():
            log("Stopped by user — automation ended")
            return
        comp = dosing_list[i] if i < len(dosing_list) else ""
        log(f"--- Assembling cell {i} (composition {comp}) ---")
        on_cell_start(i)
        _assemble_one(plc, robot, ot2, i, comp, plate_info, ccs,
                      dispense, dst_well, step_check, log)

        # (5) Crimping
        if first:                              # first cell: crimp only (no retrieve/insert)
            first = False
            plc.wait_crimper_done(should_run, log=log)
            plc.actu_move(10, 700, log=log)
            robot.tcp([15])
            plc.actu_move(10, 0, log=log)
            plc.crimper_on()
            on_cell_done(i)
            continue

        plc.wait_crimper_done(should_run, log=log)
        # (6) After crimping — handle the previous cell (branches on mode)
        if mode == "cycle":
            _insert_to_cycler(plc, robot, neware, jig_pos[i] - 1,
                              protocol, savedir, backup, log, should_run)
        else:
            robot.tcp([300, 100 + ccs + i - 1])       # return to the storage rack
        plc.actu_move(10, 700, log=log)
        robot.tcp([15])
        plc.actu_move(10, 0, log=log)
        plc.crimper_on()

        if i == n - 1:                          # last cell: also handle itself
            plc.wait_crimper_done(should_run, log=log)
            if mode == "cycle":
                _insert_to_cycler(plc, robot, neware, jig_pos[i],
                                  protocol, savedir, backup, log, should_run)
            else:
                robot.tcp([300, 100 + ccs + i])

        on_cell_done(i)

    if mode == "assembly" and notify:
        notify("✅ [ALBATROSS] All cells assembled")
    log("Assembly automation ended")
