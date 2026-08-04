"""
gateway.py — OPC UA Aggregation Gateway
========================================

Purpose
-------
- Subscribe to the main nodes of the Omron PLC (192.168.1.100:4840, ns=4) and mirror them into
  the gateway namespace's PLC.* nodes only when a value changes
  (+ a periodic safety-net re-read for nodes the subscription misses)
- Automation scripts (Jupyter / Python) connect as clients and update the gateway's own
  Run.* / Cell.* / Control.* / Biologic.* nodes
- UaExpert and the PyQt GUI only need to look at the gateway (:4841)

Layout
------
    Omron PLC (192.168.1.100:4840, ns=4)
        ↑↓                    ↑↓
    Python (Jupyter)       ProdTracker
    automation script         camera
        │
        └─ additionally connects to the gateway (127.0.0.1:4841) as a client
           to update Run.* / Cell.* / Control.*
                       │
                       ├── UaExpert
                       └── PyQt GUI

Run
---
    pip install asyncua
    python gateway.py

Quit: Ctrl+C

How an automation script uses it (example)
-----------------------------------------
    from opcua import Client            # existing code still talks only to the PLC
    plc = Client("opc.tcp://192.168.1.100:4840"); plc.connect()

    # one extra line — also connect to the gateway as a client
    gw = Client("opc.tcp://127.0.0.1:4841/gateway/"); gw.connect()

    def gw_send(node, value):
        gw.get_node(f"ns=2;s={node}").set_value(value)

    def gw_read(node):
        return gw.get_node(f"ns=2;s={node}").get_value()

    # usage
    gw_send("Run.CurrentStep", "dosing_cell_5")
    gw_send("Cell.CurrentChannel", 7)
    if gw_read("Control.StopRequest"):
        break
"""

import asyncio
import logging
from asyncua import Server, Client, ua


# ─────────────────────────────────────────────────────────────
# Settings — adjust as needed
# ─────────────────────────────────────────────────────────────
PLC_ENDPOINT     = "opc.tcp://192.168.1.100:4840"
GATEWAY_ENDPOINT = "opc.tcp://0.0.0.0:4841/gateway/"
GATEWAY_URI      = "http://lab/gateway"
PLC_SUB_PERIOD   = 200  # PLC subscription publish interval (ms) — a change is notified within this window
# Periodically re-read only the "odd" nodes that never fire a subscription notification.
# (All other nodes are pure subscription. An empty set() = fully pure subscription.)
RECONCILE_ONLY     = {"Crimper_On"}
RECONCILE_INTERVAL = 1.0   # re-read interval for those nodes (seconds)
DEBUG_WATCH      = set()  # diagnostics: log PLC->mirror updates for these nodes (e.g. {"Crimper_On"})

# Nodes to mirror from the PLC (names are used verbatim as ns=4;s=<name>)
# (PLC_node_name, asyncua_datatype) — exposed under PLC.* on the gateway
PLC_MIRROR_NODES = [
    ("Robot_moving",      ua.VariantType.Boolean),
    ("Robot_moving2",     ua.VariantType.Boolean),
    ("Crimper_Done",      ua.VariantType.Boolean),
    ("Crimper_On",        ua.VariantType.Boolean),
    ("OT2_interlock",     ua.VariantType.Boolean),
    ("bAt_readypos",     ua.VariantType.Boolean),
    ("bJOB_idle",          ua.VariantType.Boolean),
    ("Jig_Readypos",      ua.VariantType.Boolean),
    ("DataOT2.Pipette0",  ua.VariantType.Int16),
    ("DataOT2.Pipette1",  ua.VariantType.Int16),
    ("bPlate_aligncheck",  ua.VariantType.Boolean),
    ("Data.Gantry",       ua.VariantType.String),
    ("Jigmove_csv",       ua.VariantType.Float),
    ("bCCSactu_aligncheck",    ua.VariantType.Boolean), 
    ("iCCSactu_seq",       ua.VariantType.Int16),
    ("bCCSactu_move",    ua.VariantType.Boolean), 
    ("bPlate_aligncheck",    ua.VariantType.Boolean),
    ("DataJig.Cycler",    ua.VariantType.ExtensionObject),
    ("DataJig.EIS",       ua.VariantType.ExtensionObject),
    ("DataJig.Gantry",    ua.VariantType.String),
    ("Actu.iIndex",       ua.VariantType.Int16),
    ("Actu.iPos",       ua.VariantType.Int16),
    ("Actu.bMove",    ua.VariantType.Boolean),
    ("fbMotorRelay", ua.VariantType.Boolean),
    ("MotorSwitch",  ua.VariantType.Boolean),   # physical emergency switch (read)
    ("Serial_Busy",  ua.VariantType.Boolean),   # serial actuator comms in progress (used to verify actu_move)
    ("Serial_Error", ua.VariantType.Boolean),   # serial comms error
    ("Serial_Errid", ua.VariantType.UInt16),    # serial error code (PLC WORD)
    # ── [added] Jig-tab PLC global variables (read-only mirror). Entries already listed above are omitted ──
    ("Motor1.bUp",            ua.VariantType.Boolean),
    ("Motor1.bOrigin",        ua.VariantType.Boolean),
    ("Motor2.bUp",            ua.VariantType.Boolean),
    ("Motor2.bOrigin",        ua.VariantType.Boolean),
    ("Motor3.bUp",            ua.VariantType.Boolean),
    ("Motor3.bOrigin",        ua.VariantType.Boolean),
    ("Motor4.bUp",            ua.VariantType.Boolean),
    ("Motor4.bOrigin",        ua.VariantType.Boolean),
    ("bCCS_aligncheck",       ua.VariantType.Boolean),
    ("bAssem_aligncheck",     ua.VariantType.Boolean),
    ("Program0.JOBList_Clear", ua.VariantType.Boolean),
    ("fbMotor1.bANSEnable",  ua.VariantType.Boolean), 
    ("fbMotor1.rABSPos",  ua.VariantType.Double), 
    ("fbMotor1.rABSVel",  ua.VariantType.Double), 
    ("fbMotor1.rABSAccel",  ua.VariantType.Double), 
    ("fbMotor1.rABSDecel",  ua.VariantType.Double), 
    ("fbMotor2.bANSEnable",  ua.VariantType.Boolean), 
    ("fbMotor2.rABSPos",  ua.VariantType.Double), 
    ("fbMotor2.rABSVel",  ua.VariantType.Double), 
    ("fbMotor2.rABSAccel",  ua.VariantType.Double), 
    ("fbMotor2.rABSDecel",  ua.VariantType.Double), 
    ("fbMotor3.bANSEnable",  ua.VariantType.Boolean), 
    ("fbMotor3.rABSPos",  ua.VariantType.Double), 
    ("fbMotor3.rABSVel",  ua.VariantType.Double), 
    ("fbMotor3.rABSAccel",  ua.VariantType.Double), 
    ("fbMotor3.rABSDecel",  ua.VariantType.Double), 
    ("fbMotor4.bANSEnable",  ua.VariantType.Boolean), 
    ("fbMotor4.rABSPos",  ua.VariantType.Double), 
    ("fbMotor4.rABSVel",  ua.VariantType.Double), 
    ("fbMotor4.rABSAccel",  ua.VariantType.Double), 
    ("fbMotor4.rABSDecel",  ua.VariantType.Double), 
    # add more as needed below
    # ("fbMotor1.Power.bPowerEnable", ua.VariantType.Boolean),
    # ("Assemalign_Check",            ua.VariantType.Boolean),
]


# ─────────────────────────────────────────────────────────────
# [added] Command nodes — the GUI writes them on the gateway and they are forwarded to the PLC
# (write-through).
#   (name, vtype, value_rank, initial)   value_rank: -1 scalar / 1 = 1D / 2 = 2D
#   They live in a separate namespace (ns=4, Cmd) so they never collide with the state mirror (ns=3).
# ─────────────────────────────────────────────────────────────
def _motor_command_nodes():
    nodes = []
    for n in (1, 2, 3, 4):
        nodes.append((f"fbMotor{n}.Power.bPowerEnable", ua.VariantType.Boolean, -1, False))
        nodes.append((f"fbMotor{n}.MoveABS.rABSVel",    ua.VariantType.Double,  -1, 0.0))
        nodes.append((f"fbMotor{n}.MoveABS.rABSAccel",  ua.VariantType.Double,  -1, 0.0))
        nodes.append((f"fbMotor{n}.MoveABS.rABSDecel",  ua.VariantType.Double,  -1, 0.0))
        nodes.append((f"fbMotor{n}.MoveABS.rABSPos",    ua.VariantType.Double,  -1, 0.0))
        nodes.append((f"fbMotor{n}.MoveABS.bABSEnable", ua.VariantType.Boolean, -1, False))
    return nodes


COMMAND_NODES = [
    ("JOB",         ua.VariantType.String, 1, ["", ""]),   # ARRAY[0..1] OF STRING[256]
    ("Jigmove_csv", ua.VariantType.Float,  2, None),       # ARRAY[0..47,0..5] OF REAL
    ("EISmove_csv", ua.VariantType.Float,  2, None),       # ARRAY[0..1,0..3] OF REAL
    ("DataOT2.Pipette0", ua.VariantType.Int16, -1, 0),     # OT2 tip rack 0 counter (write)
    ("DataOT2.Pipette1", ua.VariantType.Int16, -1, 0),     # OT2 tip rack 1 counter (write)
    ("fbMotorRelay",     ua.VariantType.Boolean, -1, False),  # emergency stop: True makes the PLC cut motor power
    ("Robot_moving2",    ua.VariantType.Boolean, -1, False),  # robot-moving flag (written by tcp)
    # ── Cell assembly command nodes ──
    ("ActuIndex",        ua.VariantType.Int16,   -1, 0),      # serial actuator index
    ("ActuMove",         ua.VariantType.Int16,   -1, 0),      # serial actuator target value
    ("Open_Serial",      ua.VariantType.Boolean, -1, False),  # serial transmit trigger
    ("CCSactu_Index",    ua.VariantType.Int16,   -1, 0),      # CCS actuator index (actu())
    ("CCSactu_Check",    ua.VariantType.Boolean, -1, False),  # CCS actuator trigger
    ("Motor1.bUp",       ua.VariantType.Boolean, -1, False),  # raise assembly stage motor 1
    ("Motor2.bUp",       ua.VariantType.Boolean, -1, False),  # raise assembly stage motor 2
    ("bAssem_aligncheck", ua.VariantType.Boolean, -1, False), # assembly alignment check trigger
    ("bPlate_aligncheck", ua.VariantType.Boolean, -1, False), # plate alignment check (cycler insertion)
    ("Crimper_On",       ua.VariantType.Boolean, -1, False),  # start the crimper
    ("bAt_readypos",     ua.VariantType.Boolean, -1, False),  # reset the ready-position confirmation (write)
    ("ProdTracker.Capture.bStart", ua.VariantType.Boolean, -1, False),  # camera capture trigger
    # ── [added] Jig-tab PLC global variables (write). Entries already listed above are omitted ──
    ("Actu.iIndex",            ua.VariantType.Int16,   -1, 0),
    ("Actu.iPos",              ua.VariantType.Int16,   -1, 0),
    ("Actu.bMove",             ua.VariantType.Boolean, -1, False),
    ("Motor1.bOrigin",         ua.VariantType.Boolean, -1, False),
    ("Motor2.bOrigin",         ua.VariantType.Boolean, -1, False),
    ("Motor3.bUp",             ua.VariantType.Boolean, -1, False),
    ("Motor3.bOrigin",         ua.VariantType.Boolean, -1, False),
    ("Motor4.bUp",             ua.VariantType.Boolean, -1, False),
    ("Motor4.bOrigin",         ua.VariantType.Boolean, -1, False),
    ("bCCS_aligncheck",        ua.VariantType.Boolean, -1, False),
    ("bJOB_idle",              ua.VariantType.Boolean, -1, False),
    ("iCCSactu_seq",           ua.VariantType.Int16,   -1, 0),
    ("bCCSactu_move",          ua.VariantType.Boolean, -1, False),
    ("Program0.JOBList_Clear", ua.VariantType.Boolean, -1, False),
] + _motor_command_nodes()


# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logging.getLogger("asyncua").setLevel(logging.WARNING)
log = logging.getLogger("gateway")


# ─────────────────────────────────────────────────────────────
# Node definitions
# ─────────────────────────────────────────────────────────────
def _default_for(vtype: ua.VariantType):
    return {
        ua.VariantType.Boolean: False,
        ua.VariantType.Int16:   0,
        ua.VariantType.UInt16:  0,
        ua.VariantType.Int32:   0,
        ua.VariantType.Double:  0.0,
        ua.VariantType.Float:   0.0,
        ua.VariantType.String:  "",
    }.get(vtype, None)


def _iter_struct_fields(inst):
    """Iterate (field name, value) pairs of an ExtensionObject instance decoded by asyncua.

    After load_data_type_definitions(), user-defined struct classes normally carry ua_types
    metadata. Falls back to vars() when they do not.
    """
    types = getattr(type(inst), "ua_types", None)
    if types:
        for fname, _ftype in types:
            yield fname, getattr(inst, fname)
    else:
        for fname, fval in vars(inst).items():
            if fname.startswith("_"):
                continue
            yield fname, fval


async def setup_self_nodes(server: Server, idx: int):
    """The gateway's own nodes (Run/Cell/Control/Biologic) — string NodeIds."""
    objects = server.nodes.objects

    async def add_folder(parent, folder_name, items):
        # Objects (folders) also get string NodeIds — ns=2;s=Run
        obj = await parent.add_object(ua.NodeId(folder_name, idx), folder_name)
        for var_name, init in items:
            full = f"{folder_name}.{var_name}"      # e.g. "Run.ID"
            var = await obj.add_variable(
                ua.NodeId(full, idx),               # ns=2;s=Run.ID
                var_name,                            # BrowseName: "ID"
                init,
            )
            await var.set_writable()
        return obj

    await add_folder(objects, "Run", [
        ("ID", ""), ("StartTime", ""), ("CurrentStep", ""), ("Progress", 0.0),
    ])
    await add_folder(objects, "Cell", [
        ("CurrentChannel", 0), ("Composition", ""), 
        ("DosingDone", False), ("CrimpingDone", False),
    ])
    await add_folder(objects, "Control", [
        ("PauseRequest", False), ("StopRequest", False),
        ("SkipStep", False), ("Emergency", False),
    ])
    await add_folder(objects, "Biologic", [
        ("Connected", False), ("CurrentFreq", 0.0),
        ("LastEIS_Zreal", 0.0), ("LastEIS_Zimag", 0.0),
    ])

    log.info("self nodes ready under ns=%d (Run / Cell / Control / Biologic)", idx)


async def setup_mirror_nodes(
    server: Server, idx: int, plc: Client | None
) -> tuple[dict, dict]:
    """Create the PLC mirror nodes.

    Scalar:  ns=3;s=<name>           (Boolean / Int / String / ...)
    Struct:  ns=3;s=<name>           (folder object)
             ns=3;s=<name>.<field>   (child variables — String[] etc. handled automatically)

    handles[name]
      = {"kind":"scalar", "var": Node, "vtype": VariantType}
      = {"kind":"struct", "obj": Node, "fields": {fname: Node},
         "cache": inst, "lock": asyncio.Lock()}

    child_lookup[child_nodeid] = (parent_name, field_name)
        — used by the write-through handler to map a child node back to its parent/field.

    If the PLC is disconnected or a struct read fails, only that ExtensionObject entry is skipped.
    """
    plc_obj = await server.nodes.objects.add_object(
        ua.NodeId("PLC", idx), "PLC"
    )
    handles: dict = {}
    child_lookup: dict = {}

    _seen = set()
    for name, vtype in PLC_MIRROR_NODES:
        if name in _seen:                       # [added] guard against duplicate nodes (e.g. bPlate_aligncheck)
            log.warning("skip duplicate mirror node [%s]", name)
            continue
        _seen.add(name)
        full = f"{name}"
        if vtype == ua.VariantType.ExtensionObject:
            if plc is None:
                log.warning("skip ExtensionObject mirror [%s] — PLC not connected", name)
                continue
            try:
                src = plc.get_node(f"ns=4;s={name}")
                inst = await src.read_value()
                parent = await plc_obj.add_object(ua.NodeId(full, idx), name)
                fields: dict = {}
                for fname, fval in _iter_struct_fields(inst):
                    child_nodeid = ua.NodeId(f"{full}.{fname}", idx)
                    child = await parent.add_variable(child_nodeid, fname, fval)
                    await child.set_writable()
                    fields[fname] = child
                    child_lookup[child_nodeid] = (name, fname)
                handles[name] = {
                    "kind":   "struct",
                    "obj":    parent,
                    "fields": fields,
                    "cache":  inst,
                    "lock":   asyncio.Lock(),
                }
                log.info("struct mirror [%s] — fields: %s",
                         name, ", ".join(fields.keys()))
            except Exception as e:
                log.warning("failed to init ExtensionObject mirror [%s]: %s", name, e)
                continue
        else:
            var = await plc_obj.add_variable(
                ua.NodeId(full, idx), name, _default_for(vtype),
            )
            await var.set_writable()
            handles[name] = {"kind": "scalar", "var": var, "vtype": vtype}

    log.info("mirror nodes ready under ns=%d.PLC (%d entries)", idx, len(handles))
    return handles, child_lookup


async def setup_command_nodes(server: Server, idx: int) -> dict:
    """"Command" nodes that the GUI (as a client) writes on the gateway to forward to the PLC.

    They are created regardless of whether the PLC is connected (writes are forwarded via
    write-through). Scalars/1D/2D are created with matching ValueRank/ArrayDimensions.
    Returns: handles[name] = {"kind":"scalar", "var":Node, "vtype":VariantType}
    """
    cmd_obj = await server.nodes.objects.add_object(ua.NodeId("Cmd", idx), "Cmd")
    handles: dict = {}
    for name, vtype, rank, init in COMMAND_NODES:
        if init is None:
            if name == "Jigmove_csv":
                init = [[0.0] * 6 for _ in range(48)]
            elif name == "EISmove_csv":
                init = [[0.0] * 4 for _ in range(2)]
            else:
                init = _default_for(vtype)
        var = await cmd_obj.add_variable(ua.NodeId(name, idx), name,
                                         ua.Variant(init, vtype))
        await var.set_writable()
        if rank >= 1:
            await var.write_attribute(
                ua.AttributeIds.ValueRank,
                ua.DataValue(ua.Variant(rank, ua.VariantType.Int32)))
            await var.write_attribute(
                ua.AttributeIds.ArrayDimensions,
                ua.DataValue(ua.Variant([0] * rank, ua.VariantType.UInt32)))
        handles[name] = {"kind": "scalar", "var": var, "vtype": vtype}
    log.info("command nodes ready under ns=%d.Cmd (%d entries)", idx, len(handles))
    return handles


class _WriteThroughHandler:
    """Forward values that UaExpert or a client writes to a mirror node (ns=3) on to the real PLC (ns=4).

    - Scalar: write_attribute with a DataValue carrying only Value
      (works around the Omron PLC rejecting a simultaneous SourceTimestamp + ServerTimestamp write)
    - Struct child field: update just that field in the parent instance cache, then write_value
      the whole instance to the PLC
    """

    def __init__(self, plc: Client, handles: dict, child_lookup: dict):
        self.plc = plc
        self.handles = handles
        self.child_lookup = child_lookup
        self.scalar_lookup = {
            h["var"].nodeid: (name, h["vtype"])
            for name, h in handles.items() if h["kind"] == "scalar"
        }
        self.enabled = False

    async def datachange_notification(self, node, val, data):
        if not self.enabled:
            return

        info = self.scalar_lookup.get(node.nodeid)
        if info is not None:
            name, vtype = info
            try:
                dv = ua.DataValue(
                    Value=ua.Variant(val, vtype),
                    SourceTimestamp=None,
                    ServerTimestamp=None,
                )
                await self.plc.get_node(f"ns=4;s={name}").write_attribute(
                    ua.AttributeIds.Value, dv
                )
                log.info("write-through PLC.%s ← %r", name, val)
            except Exception as e:
                log.warning("write-through failed [%s]: %s", name, e)
            return

        sub = self.child_lookup.get(node.nodeid)
        if sub is not None:
            parent_name, field_name = sub
            h = self.handles.get(parent_name)
            if h is None or h["kind"] != "struct":
                return
            try:
                async with h["lock"]:
                    setattr(h["cache"], field_name, val)
                    inst = h["cache"]
                    dv = ua.DataValue(
                        Value=ua.Variant(inst, ua.VariantType.ExtensionObject),
                        SourceTimestamp=None,
                        ServerTimestamp=None,
                    )
                    await self.plc.get_node(f"ns=4;s={parent_name}").write_attribute(
                        ua.AttributeIds.Value, dv
                    )
                log.info("write-through PLC.%s.%s ← %r", parent_name, field_name, val)
            except Exception as e:
                log.warning("write-through failed [%s.%s]: %s",
                            parent_name, field_name, e)


# ─────────────────────────────────────────────────────────────
# PLC subscription (mirror nodes update only on change) + safety-net re-read
# ─────────────────────────────────────────────────────────────
class _PlcMirrorHandler:
    """Apply PLC (ns=4) values to the mirror nodes (ns=3).

    Both the subscription notification (datachange_notification) and the safety-net re-read
    (reconcile loop) go through the same apply() logic.

    Duplicate detection compares against the mirror node's **actual current value**, not a
    separate 'last' cache. This keeps things consistent even when a user writes to the mirror
    directly from UaExpert (fixing a bug in the old 'last' approach).
    """

    def __init__(self, handles: dict):
        self.handles = handles
        self.by_nodeid: dict = {}     # PLC nodeid -> (name, handle)

    def build_targets(self, plc: Client) -> list:
        """Build the list of PLC nodes to subscribe to and fill the nodeid reverse map."""
        self.by_nodeid.clear()
        nodes = []
        for name, h in self.handles.items():
            node = plc.get_node(f"ns=4;s={name}")
            self.by_nodeid[node.nodeid] = (name, h)
            nodes.append(node)
        return nodes

    async def apply(self, name: str, h: dict, val):
        """Apply a value read from the PLC to the mirror. Writes only when it differs from the
        mirror's actual value."""
        if h["kind"] == "scalar":
            cur = await h["var"].read_value()
            if name in DEBUG_WATCH:
                log.info("apply [%s] PLC=%r mirror=%r -> %s",
                         name, val, cur, "WRITE" if cur != val else "skip")
            if cur != val:
                await h["var"].write_value(val)
        else:   # struct — write the whole ExtensionObject
            async with h["lock"]:
                h["cache"] = val
                for fname, child in h["fields"].items():
                    fval = getattr(val, fname)
                    cur = await child.read_value()
                    if cur != fval:
                        await child.write_value(fval)

    async def datachange_notification(self, node, val, data):
        entry = self.by_nodeid.get(node.nodeid)
        if entry is None:
            return
        name, h = entry
        try:
            await self.apply(name, h, val)
        except Exception as e:
            log.warning("PLC mirror update failed [%s]: %s", name, e)


async def plc_reconcile_loop(plc: Client, handler: "_PlcMirrorHandler"):
    """Periodically re-read only the "odd" nodes listed in RECONCILE_ONLY.

    Some Omron variables (e.g. Crimper_On) never refresh their SourceTimestamp, so they never
    fire a subscription notification — relying on the subscription alone would freeze them.
    Instead of polling everything, this corrects just the problematic nodes.
    """
    targets = [(n, handler.handles[n]) for n in RECONCILE_ONLY
               if n in handler.handles]
    if not targets:
        log.info("reconcile loop disabled (RECONCILE_ONLY empty)")
        return
    log.info("reconcile loop active — nodes: %s (every %.1fs)",
             ", ".join(n for n, _ in targets), RECONCILE_INTERVAL)
    while True:
        await asyncio.sleep(RECONCILE_INTERVAL)
        for name, h in targets:
            try:
                val = await plc.get_node(f"ns=4;s={name}").read_value()
                await handler.apply(name, h, val)
            except Exception as e:
                log.debug("reconcile read failed [%s]: %s", name, e)


async def plc_mirror_subscribe(plc: Client, handler: "_PlcMirrorHandler"):
    """Subscribe to the PLC so the mirror only updates when a value changes.

    A subscription does not survive a reconnect, so when the connection drops it automatically
    reconnects and re-subscribes. (This combines polling and keep_plc_connected into one job.)
    """
    while True:
        try:
            sub = await plc.create_subscription(PLC_SUB_PERIOD, handler)
            nodes = handler.build_targets(plc)
            # On subscribing, each node's current value arrives once, initializing the mirror
            await sub.subscribe_data_change(nodes)
            log.info("PLC subscription active (period=%dms, %d nodes)",
                     PLC_SUB_PERIOD, len(nodes))

            # Connection keep-alive check — a drop raises and falls into the except below
            while True:
                await asyncio.sleep(5)
                await plc.check_connection()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("PLC subscription lost — reconnecting: %s", e)
            try:
                await plc.disconnect()
            except Exception:
                pass
            try:
                await plc.connect()
                log.info("PLC reconnected — resubscribing")
                try:
                    await plc.load_data_type_definitions()
                except Exception as e3:
                    log.warning("load_data_type_definitions failed: %s", e3)
            except Exception as e2:
                log.error("PLC reconnect failed: %s", e2)
                await asyncio.sleep(5)


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────
async def main():
    # 1) Prepare the gateway server
    server = Server()
    await server.init()
    server.set_endpoint(GATEWAY_ENDPOINT)
    server.set_server_name("Lab Aggregation Gateway")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

    idx_self   = await server.register_namespace(GATEWAY_URI)            # ns=2
    idx_mirror = await server.register_namespace(GATEWAY_URI + "/PLC")   # ns=3
    idx_cmd    = await server.register_namespace(GATEWAY_URI + "/Cmd")   # ns=4  [added] command nodes

    # 2) Connect the PLC client — attempted before node creation so ExtensionObject mirror nodes
    #    can be expanded automatically. The gateway still starts if this fails.
    plc = Client(PLC_ENDPOINT)
    plc_connected = False
    try:
        await plc.connect()
        plc_connected = True
        log.info("Connected to PLC %s", PLC_ENDPOINT)
        try:
            await plc.load_data_type_definitions()
            log.info("PLC data type definitions loaded")
        except Exception as e:
            log.warning("load_data_type_definitions failed (struct mirror may degrade): %s", e)
    except Exception as e:
        log.error("PLC connect failed (gateway keeps running anyway): %s", e)

    await setup_self_nodes(server, idx_self)
    mirror_handles, child_lookup = await setup_mirror_nodes(
        server, idx_mirror, plc if plc_connected else None
    )
    cmd_handles = await setup_command_nodes(server, idx_cmd)   # [added] command nodes (created even without a PLC)

    plc_tasks = []
    if plc_connected:
        # PLC -> mirror handler (shared by the subscription and the safety-net re-read)
        mirror_handler = _PlcMirrorHandler(mirror_handles)
        # Subscription: fast updates on change + automatic reconnect/resubscribe on drop
        plc_tasks.append(asyncio.create_task(plc_mirror_subscribe(plc, mirror_handler)))
        # Safety net: periodically read values the subscription missed straight from the PLC
        plc_tasks.append(asyncio.create_task(plc_reconcile_loop(plc, mirror_handler)))

        # Subscription targets: scalar variables + the child field variables of structs
        watch_vars = []
        for h in mirror_handles.values():
            if h["kind"] == "scalar":
                watch_vars.append(h["var"])
            else:
                watch_vars.extend(h["fields"].values())

        all_handles = {**mirror_handles, **cmd_handles}   # [changed] state mirror + command nodes
        handler = _WriteThroughHandler(plc, all_handles, child_lookup)
        sub = await server.create_subscription(100, handler)
        watch_vars = watch_vars + [h["var"] for h in cmd_handles.values()]  # [added]
        await sub.subscribe_data_change(watch_vars)
        await asyncio.sleep(0.5)         # let the initial value notifications pass through
        handler.enabled = True
        log.info("write-through subscription active (mirror -> PLC, %d nodes)", len(watch_vars))

    # 3) Run the server
    async with server:
        log.info("Gateway listening on %s", GATEWAY_ENDPOINT)
        log.info("  self   ns=%d  -> Run.* / Cell.* / Control.* / Biologic.*", idx_self)
        log.info("  mirror ns=%d  -> PLC.<plc-node-name>", idx_mirror)
        log.info("  e.g.)  ns=%d;s=Run.CurrentStep   ns=%d;s=PLC.Robot_moving",
                 idx_self, idx_mirror)
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            log.info("shutting down...")
        finally:
            for t in plc_tasks:
                t.cancel()
            try:
                await plc.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
