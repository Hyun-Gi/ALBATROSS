from __future__ import annotations
from typing import Dict, Optional, Any, Tuple, List

# This is the real one @@@
def sodium_formulator(
    *,
    x: float,  # target molarity (M) in final electrolyte
    ratios: Dict[str, float],  # solvent fractions (sum can be !=1; will be normalized)
    solvent_info: Dict[str, float],  # {solvent: stock_concentration_M} (e.g., all 3.0)
    target_volume: float = 1.0,  # L (final total volume)
    salt_MW: float = 167.95,  # g/mol
    salt_density: float = 2.369,  # g/mL
    ratios_are_percent: bool = False,
    tol: float = 1e-9, 
    verbose: bool = False,
) -> Optional[Dict[str, Any]]:
    """

    Assumptions / definitions
    - Eureka! We must assume the solvent volume increases by exactly the volume of salt added.
      (Not true in reality — the volume increase differs per solvent.)
    - ratios is "each solvent's share of the total volume in the final 1 L"
      (e.g. 0.2, 0.5, 0.3 -> 0.2 L, 0.5 L, 0.3 L)
    - Every solvent has a stock solution: solvent_info[solv] = salt concentration (M) of that stock
    - Goal: reach salt concentration x (M) in the final 1 L
    - Greedy: consume stock starting from the solvent with the largest salt mass its ratio allows (cap_g)
    - Pure solvent to add: target_solvent_volume - (stock_volume - salt_volume_in_that_stock)

    Returns
    - None if the composition is not achievable
    - otherwise a dict: dispense_stock_{solv}, dispense_pure_{solv}, salt_volume_in_stock_{solv}, ...
    """

    # 0) Clean up / normalize inputs
    ratios = dict(ratios)
    if ratios_are_percent:
        ratios = {k: v / 100.0 for k, v in ratios.items()}

    s = sum(ratios.values())
    if s <= 0:
        raise ValueError("ratios sum to 0.")
    ratios = {k: v / s for k, v in ratios.items()}

    # Check solvent_info
    missing = [k for k in ratios if k not in solvent_info]
    if missing:
        raise ValueError(f"ratios contains solvents that are missing from solvent_info: {missing}")

    V_total = float(target_volume)

    # 1) (Step 1) salt g/L contained in 1 L of each solvent's stock
    #    stock_conc_M * MW = g/L
    salt_g_per_L = {solv: float(solvent_info[solv]) * salt_MW for solv in ratios}

    # 2) (Step 2) required salt in g
    need_salt_mol = x * V_total
    need_salt_g = need_salt_mol * salt_MW

    # 3) (Step 3) salt in g each solvent can supply under its ratio (cap_g)
    #    cap_g_i = (ratio_i * V_total) * (salt_g_per_L_i)
    alloc_L = {solv: ratios[solv] * V_total for solv in ratios}  # target total solvent volume (solution incl. salt) @@@NOTE THIS
    cap_g = {solv: alloc_L[solv] * salt_g_per_L[solv] for solv in ratios}

    # Quick feasibility check: impossible if the total suppliable salt in g falls short
    total_cap_g = sum(cap_g.values())
    if total_cap_g + 1e-12 < need_salt_g:
        if verbose:
            print("Infeasible composition: not enough salt available under the ratio constraints")
            print("need_salt_g =", need_salt_g, "total_cap_g =", total_cap_g)
        return None

    # 4) (Step 4) supply salt starting from the largest cap_g (greedy)
    #    For solvent i, the maximum usable stock volume is alloc_L[i]
    #    Supplying take_g from that solvent needs take_g / salt_g_per_L[i] of stock
    solvents_sorted = sorted(ratios.keys(), key=lambda s_: cap_g[s_], reverse=True)

    remaining_g = need_salt_g
    dispense_stock = {solv: 0.0 for solv in ratios}     # L
    salt_g_from = {solv: 0.0 for solv in ratios}        # g (salt mass supplied from that solvent's stock)

    for solv in solvents_sorted:
        g_per_L = salt_g_per_L[solv]
        if g_per_L <= 0:
            continue

        # Maximum salt in g this solvent can supply
        max_g_here = cap_g[solv]

        take_g = min(remaining_g, max_g_here)
        take_stock_L = take_g / g_per_L

        # Clamp so we never exceed the total solvent volume the ratio allows
        if take_stock_L > alloc_L[solv] + tol:
            take_stock_L = alloc_L[solv]
            take_g = take_stock_L * g_per_L

        dispense_stock[solv] = take_stock_L
        salt_g_from[solv] = take_g
        remaining_g -= take_g

        if remaining_g <= tol:
            remaining_g = 0.0
            break

    if remaining_g > tol:
        # The total_cap_g check above normally prevents this (only numeric/input anomalies land here)
        if verbose:
            print("Infeasible composition: still short on salt after the greedy pass")
            print("remaining_g =", remaining_g)
        return None

    # 5) Pure-solvent calculation (mirrors the k logic in test())
    #    salt_volume_in_stock_i = salt_g_from_i / density / 1000 (L)
    salt_vol_in_stock = {solv: (salt_g_from[solv] / salt_density) / 1000.0 for solv in ratios}  # L
    solvent_from_stock = {solv: dispense_stock[solv] - salt_vol_in_stock[solv] for solv in ratios}  # L

    # k from test():
    # k = V_total - salt_total_volume
    salt_total_vol_L = sum(salt_vol_in_stock.values())
    k = V_total - salt_total_vol_L

    if k < -tol:
        if verbose:
            print("Infeasible composition: salt volume exceeds the target volume")
            print("k =", k, "V_total =", V_total, "salt_total_vol_L =", salt_total_vol_L)
        return None

    # Distribute the target total 'pure solvent' amount k by ratios, then subtract the pure
    # solvent that already arrived via the stock (solvent_from_stock) to get the pure top-up
    dispense_pure = {}
    for solv in ratios:
        target_pure_i = ratios[solv] * k
        need_pure = target_pure_i - solvent_from_stock[solv]

        if need_pure < -tol:
            if verbose:
                print(f"Infeasible composition: pure solvent arriving via stock for {solv} exceeds the target (pure<0)")
                print("target_pure_i =", target_pure_i, "solvent_from_stock =", solvent_from_stock[solv])
            return None

        dispense_pure[solv] = max(0.0, need_pure)
    # Total-volume check: sum(stock solution) + sum(pure solvent) must equal V_total
    total_volume_check = sum(dispense_stock.values()) + sum(dispense_pure.values())
    if abs(total_volume_check - V_total) > 1e-6 and verbose:
        print("Warning: total volume mismatch:", total_volume_check, "vs", V_total)

    # Total salt volume (for reference)
    salt_total_vol_L = sum(salt_vol_in_stock.values())

    out: Dict[str, Any] = {
        "x": x,
        "target_volume": V_total,
        "need_salt_mol": need_salt_mol,
        "need_salt_g": need_salt_g,
        "salt_total_volume_L": salt_total_vol_L,
        "total_volume_check": total_volume_check,
        "total_stock_volume_L": sum(dispense_stock.values()),
        "total_pure_volume_L": sum(dispense_pure.values()),
    }

    for solv in ratios:
        out[f"ratio_{solv}"] = ratios[solv]
        out[f"alloc_{solv}"] = alloc_L[solv]  # target total solvent volume (solution incl. salt)
        out[f"stock_M_{solv}"] = float(solvent_info[solv])
        out[f"salt_g_per_L_{solv}"] = salt_g_per_L[solv]
        out[f"cap_salt_g_{solv}"] = cap_g[solv]
        out[f"dispense_stock_{solv}"] = dispense_stock[solv]
        out[f"salt_g_from_{solv}"] = salt_g_from[solv]
        out[f"salt_volume_in_stock_{solv}"] = salt_vol_in_stock[solv]
        out[f"solvent_from_stock_{solv}"] = solvent_from_stock[solv]
        out[f"dispense_pure_{solv}"] = dispense_pure[solv]

    return out


# ------------------------------------------------------------------
# result_df construction (notebook cell 40, unchanged) + per-range required amounts
# ------------------------------------------------------------------
import pandas as pd

SOLVENTS = ["PC", "EMC", "DEGDME", "DME", "CME", "DPE"]

# Dispense-component column prefixes — the number of leading meta columns in result_df varies
# (assembly only: starts at x -> components [7:] / with EIS: round, index, x -> components [9:]).
# Slicing by position breaks one of the two cases, so select components by name instead.
COMPONENT_PREFIXES = ("NaPF6_in_", "pure_")


def component_columns(result_df):
    """Select only the dispense-component columns (NaPF6_in_* / pure_*) by name.
    Always picks the right components regardless of how many leading meta columns there are (7, 9, ...)."""
    return [c for c in result_df.columns if str(c).startswith(COMPONENT_PREFIXES)]


# Solvent order for display. Salt group (NaPF6_in_*) first, then the pure solvent group (pure_*).
DISPLAY_SOLVENT_ORDER = ["PC", "EMC", "DPE", "DME", "DEGDME", "CME"]


def _display_key(comp):
    """Component name -> sort key: (group, solvent order, name). Salt first; unlisted solvents go last."""
    s = str(comp)
    if s.startswith("NaPF6_in_"):
        grp, solv = 0, s[len("NaPF6_in_"):]
    elif s.startswith("pure_"):
        grp, solv = 1, s[len("pure_"):]
    else:
        grp, solv = 2, s
    idx = DISPLAY_SOLVENT_ORDER.index(solv) if solv in DISPLAY_SOLVENT_ORDER else len(DISPLAY_SOLVENT_ORDER)
    return (grp, idx, solv)


def order_components(names):
    """Sort a list of component names into display order (salt first, solvents PC-EMC-DPE-DME-DEGDME-CME)."""
    return sorted(names, key=_display_key)


def build_result_df(df, solvent_info, solvents=SOLVENTS):
    """Apply sodium_formulator to the source df (each row: x, ratio_<solv>) to build a dispense table.
    Columns: x, ratio_*, NaPF6_in_* (stock uL), pure_* (pure solvent uL). Index 0..N-1."""
    results = []
    for _, row in df.iterrows():
        x = float(row["x"])
        ratios = {s: float(row[f"ratio_{s}"]) for s in solvents}
        out = sodium_formulator(x=x, ratios=ratios, solvent_info=solvent_info,
                                target_volume=1.0, verbose=False)
        if out:
            results.append({
                "x": x,
                **{f"ratio_{s}": ratios[s] for s in solvents},
                **{f"NaPF6_in_{s}": round(float(out[f"dispense_stock_{s}"]) * 1000 / 2) for s in solvents},
                **{f"pure_{s}":  round(float(out[f"dispense_pure_{s}"])  * 1000 / 2) for s in solvents},
            })
    return pd.DataFrame(results).fillna(1)


def required_amounts(result_df, n_start, n_end, include_zero=False):
    """Total amount (uL) needed per component for compositions n_start..n_end (inclusive).
    include_zero=False: skip components that come to 0. True: include 0 µL components (for display)."""
    cols = order_components(component_columns(result_df))   # display order (salt first, then solvent order)
    sub = result_df.iloc[n_start:n_end + 1]
    out = {}
    for c in cols:
        tot = float(sub[c].sum())
        if include_zero or tot > 0:
            out[c] = tot
    return out
