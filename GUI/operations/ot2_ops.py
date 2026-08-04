"""
OT-2 electrolyte dosing operations — port of the notebook's pipette / as_dp / formulate_n_electrolyte.
Component list = result_df.columns[7:]. Destination well = num_wellplate[composition index].
"""

# Destination well plate, 96 wells (notebook num_wellplate)
NUM_WELLPLATE = [f"{r}{c}" for c in range(1, 13) for r in "ABCDEFGH"]


def components(result_df):
    """Dispense-component columns (NaPF6_in_* / pure_*) — selected by name, so the number of
    leading meta columns (7/9) does not matter."""
    from albatross.operations import formulation
    return formulation.component_columns(result_df)


def pipette(plc, log=print):
    """Return the next (tiprack, index) to use based on the PLC DataOT2.Pipette0/1 counters,
    and increment the counter. Raises RuntimeError when both are empty (96/96) — the GUI must
    then perform a 'Reset tip racks'."""
    t0 = plc.read("DataOT2.Pipette0")
    t1 = plc.read("DataOT2.Pipette1")
    t0 = 0 if t0 is None else int(t0)
    t1 = 0 if t1 is None else int(t1)
    if t0 == 0 and 0 < t1 < 96:
        plc.send("DataOT2.Pipette1", t1 + 1); return "tiprack_2", t1
    if t0 == 96 and 0 <= t1 < 96:
        plc.send("DataOT2.Pipette1", t1 + 1); return "tiprack_2", t1
    if t0 == 96 and t1 == 96:
        raise RuntimeError("All tip racks are empty — set the counters via 'OT2 tab -> Reset tip racks'.")
    plc.send("DataOT2.Pipette0", t0 + 1); return "tiprack_1", t0


def as_dp(ot2, plc, result_df, plate_mapping, n, comp, log=print):
    """Dispense component comp into the destination well of composition n (notebook as_dp)."""
    if comp not in result_df.columns or n not in result_df.index:
        return
    residue = float(result_df.loc[n, comp])
    if residue == 0:
        return
    src = plate_mapping[comp]
    dst = NUM_WELLPLATE[n]
    tip = pipette(plc, log)
    ot2.raw("left_tip.pick_up_tip({}.wells()[{}])".format(tip[0], tip[1]))
    while residue > 280:
        ot2.raw("left_tip.aspirate(250, {}, rate=20)".format(src))
        ot2.raw("left_tip.air_gap(20)")
        ot2.raw("left_tip.touch_tip(location = {}, radius=1, v_offset=-7, speed = 50 )".format(src))
        residue -= 250
        ot2.raw("left_tip.dispense(270, wellplate['{}'].top(z=-5), rate=20)".format(dst))
        ot2.raw("left_tip.touch_tip(location = wellplate['{}'], radius=1, v_offset=-7, speed = 50 )".format(dst))
        ot2.raw("left_tip.blow_out()")
    ot2.raw("left_tip.aspirate({}, {}, rate=20)".format(residue, src))
    ot2.raw("left_tip.air_gap(20)")
    ot2.raw("left_tip.touch_tip(location = {}, radius=1, v_offset=-7, speed = 50 )".format(src))
    ot2.raw("left_tip.dispense({}, wellplate['{}'].top(z=-5), rate=20)".format(residue + 20, dst))
    ot2.raw("left_tip.touch_tip(location = wellplate['{}'], radius=1, v_offset=-7, speed = 50 )".format(dst))
    ot2.raw("left_tip.blow_out()")
    ot2.raw("left_tip.drop_tip()")


def formulate_n_electrolyte(ot2, plc, result_df, plate_mapping, n, comps=None, log=print):
    """Dispense every component of composition n, then mix (notebook formulate_n_electrolyte).
    Components that are not dispensed (0 µL, or missing from plate_mapping) are logged as skipped."""
    comps = comps or components(result_df)
    if n not in result_df.index:
        log(f"  Composition {n}: no data -> skipping entirely")
        return
    todo, skipped = [], []
    for comp in comps:
        if comp in plate_mapping and float(result_df.loc[n, comp]) > 0:
            todo.append(comp)
        else:
            skipped.append(comp)
    if skipped:
        log(f"  Composition {n}, skipped ({len(skipped)}): {', '.join(skipped)}")
    for comp in todo:
        as_dp(ot2, plc, result_df, plate_mapping, n, comp, log)
    dst = NUM_WELLPLATE[n]
    tip = pipette(plc, log)
    ot2.raw("left_tip.pick_up_tip({}.wells()[{}])".format(tip[0], tip[1]))
    ot2.raw("left_tip.mix(25, 150, wellplate['{}'])".format(dst))
    ot2.raw("left_tip.touch_tip(location = wellplate['{}'], radius=1, v_offset=-7, speed = 50 )".format(dst))
    ot2.raw("left_tip.blow_out()")
    ot2.raw("left_tip.drop_tip()")


def formulate_range(ot2, plc, result_df, plate_mapping, n_start, n_end,
                    should_run=None, log=print, on_comp_start=None, on_comp_done=None):
    """Dispense compositions n_start..n_end (inclusive) in order. Progress is reported via
    on_comp_start/done(n)."""
    if should_run is None:
        should_run = lambda: True
    on_comp_start = on_comp_start or (lambda n: None)
    on_comp_done = on_comp_done or (lambda n: None)
    comps = components(result_df)
    log(f"Dosing started: compositions {n_start}-{n_end} · {len(comps)} component(s) ({', '.join(comps)})")
    for n in range(n_start, n_end + 1):
        if not should_run():
            break
        on_comp_start(n)
        log(f"--- Dosing composition {n} ---")
        formulate_n_electrolyte(ot2, plc, result_df, plate_mapping, n, comps, log)
        on_comp_done(n)
    log("Dosing ended")


def safety(plc, should_run=None, log=print, interval=0.5, warn_after=120):
    """Wait indefinitely until OT2_interlock is True (notebook safety). After warn_after seconds it
    logs one warning and keeps waiting.
    True = success / False = stopped (should_run returned False). When the light comes on, the PLC
    raises OT2_interlock to True (Python only reads it)."""
    import time
    if should_run is None:
        should_run = lambda: True
    waited = 0.0
    warned = False
    while should_run():
        try:
            if plc.read("OT2_interlock"):
                return True
        except Exception:
            pass
        time.sleep(interval)
        waited += interval
        if warn_after and not warned and waited >= warn_after:
            log(f"⚠ Waiting {warn_after:.0f}s for OT2_interlock — check the OT2 safety light (still waiting)")
            warned = True
    return False
