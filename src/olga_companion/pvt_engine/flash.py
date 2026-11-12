"""Phase equilibrium: stability, Rachford-Rice, successive substitution with Newton acceleration.

Public sources:
- Wilson, Chem. Eng. Prog. Symp. Ser. 65 (1969): K-value start.
- Michelsen, Fluid Phase Equilibria 9 (1982) 1: tangent-plane stability analysis (iterated on
  ln Y_i = d_i - ln phi_i(y); the feed is unstable when sum Y > 1 for a non-trivial trial).
- Michelsen, Fluid Phase Equilibria 9 (1982) 21: two-phase flash, successive substitution switched
  to Newton iteration. Here the Newton step is taken on ln K with a finite-difference Jacobian
  of the fugacity equations (at most eight components).
- Rachford & Rice, J. Pet. Technol. 4 (1952) 19.

Only vapour-liquid splits are searched. Liquid-liquid and three-phase equilibria are out of scope.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .cubic import R, CubicEOS
from .errors import PvtEngineError, UnsupportedStateError

_SS_SWITCH = 1e-3
_SS_MAX = 600
_STAB_MAX = 1000


@dataclass(frozen=True)
class PhaseSplit:
    kind: str  # "gas" or "liquid"
    x: tuple[float, ...]
    fraction: float  # mole fraction of the overall amount
    Z: float
    root: str  # "vapor" (largest root) or "liquid" (smallest root)


@dataclass(frozen=True)
class FlashResult:
    phases: tuple[PhaseSplit, ...]
    converged: bool
    iterations: int
    trace: dict | None = field(default=None, compare=False)

    @property
    def n_phases(self) -> int:
        return len(self.phases)

    @property
    def vapor_fraction(self) -> float:
        """Mole fraction of gas: 1 for a single gas phase, 0 for a single liquid phase."""
        return sum(p.fraction for p in self.phases if p.kind == "gas")


def rachford_rice(z: Sequence[float], K: Sequence[float]) -> float:
    """Root V of sum z_i (K_i - 1) / (1 + V (K_i - 1)) = 0 inside the negative-flash bracket."""
    kmax, kmin = max(K), min(K)
    if not kmax > 1.0 > kmin:
        raise ValueError("Rachford-Rice needs at least one K above 1 and one below 1.")
    vmin, vmax = 1.0 / (1.0 - kmax), 1.0 / (1.0 - kmin)
    lo, hi = vmin + 1e-14 * (vmax - vmin), vmax - 1e-14 * (vmax - vmin)
    v = min(max(0.5, lo), hi)

    def f(val: float) -> float:
        return sum(zi * (ki - 1.0) / (1.0 + val * (ki - 1.0)) for zi, ki in zip(z, K))

    for _ in range(200):
        fv = f(v)
        if fv > 0:
            lo = v
        else:
            hi = v
        df = -sum(zi * (ki - 1.0) ** 2 / (1.0 + v * (ki - 1.0)) ** 2 for zi, ki in zip(z, K))
        new = v - fv / df if df != 0.0 else 0.5 * (lo + hi)
        if not lo < new < hi:
            new = 0.5 * (lo + hi)
        if abs(new - v) < 1e-15:
            v = new
            break
        v = new
    return v


def wilson_k(eos: CubicEOS, T: float, P: float) -> list[float]:
    return [c.pc * 1e5 / P * math.exp(5.373 * (1.0 + c.omega) * (1.0 - c.tc / T)) for c in eos.components]


def _normalise(z: Sequence[float], n: int) -> list[float]:
    if len(z) != n:
        raise ValueError(f"Composition has {len(z)} entries for {n} components.")
    if any((not math.isfinite(v)) or v < 0 for v in z):
        raise ValueError("Mole fractions must be finite and non-negative.")
    total = sum(z)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"Mole fractions must sum to 1 (got {total:.8g}).")
    return [v / total for v in z]


def flash_tp(eos: CubicEOS, T: float, P: float, z: Sequence[float], trace: bool = False) -> FlashResult:
    """Pressure-temperature flash of feed ``z`` (mole fractions) on ``eos``."""
    z = _normalise(z, eos.n)
    idx = tuple(i for i, zi in enumerate(z) if zi > 0.0)
    if len(idx) < eos.n:
        sub = eos.subset(idx)
        inner = flash_tp(sub, T, P, [z[i] for i in idx], trace)

        def expand(x: Sequence[float]) -> tuple[float, ...]:
            full = [0.0] * eos.n
            for k, i in enumerate(idx):
                full[i] = x[k]
            return tuple(full)

        phases = tuple(PhaseSplit(p.kind, expand(p.x), p.fraction, p.Z, p.root) for p in inner.phases)
        return FlashResult(phases, inner.converged, inner.iterations, inner.trace)
    return _flash(eos, T, P, z, trace)


def _single(eos, T, P, z, Zf, mix, converged, iterations, tr) -> FlashResult:
    roots = eos.z_roots(T, P, z, mix)
    root = "vapor" if Zf == roots[-1] else "liquid"
    if len(roots) > 1:
        kind = "gas" if root == "vapor" else "liquid"
    else:
        kind = "liquid" if eos.is_liquid_like(T, P, z, Zf, mix) else "gas"
    return FlashResult((PhaseSplit(kind, tuple(z), 1.0, Zf, root),), converged, iterations, tr)


def _flash(eos: CubicEOS, T: float, P: float, z: list[float], want_trace: bool) -> FlashResult:
    n = eos.n
    mix_z = eos.mix(T, z)
    zf, lnphi_z, roots = eos.stable_root(T, P, z, mix_z)
    tr: dict | None = None
    if want_trace:
        tr = {
            "T_K": T, "P_Pa": P, "z": list(z),
            "feed_roots": [
                {"Z": r, "phase_like": "liquid" if eos.is_liquid_like(T, P, z, r, mix_z) else "gas",
                 "gibbs_residual_over_RT": sum(zi * li for zi, li in zip(z, eos.ln_phi(T, P, z, r, mix_z)))}
                for r in roots
            ],
            "selected_feed_root_Z": zf,
        }
    if n == 1:
        if tr is not None:
            tr["stability"] = {"unstable": False, "trials": [], "note": "pure component: single root of lowest Gibbs energy"}
            tr["successive_substitution"], tr["newton"], tr["split"] = [], [], None
        return _single(eos, T, P, z, zf, mix_z, True, 0, tr)

    d = [math.log(zi) + lp for zi, lp in zip(z, lnphi_z)]
    k_wilson = wilson_k(eos, T, P)
    trials = []
    best = None
    for kind, start in (("vapor-like", [zi * k for zi, k in zip(z, k_wilson)]),
                        ("liquid-like", [zi / k for zi, k in zip(z, k_wilson)])):
        ln_y = [math.log(v) for v in start]
        iterations = 0
        for iterations in range(1, _STAB_MAX + 1):
            ys = sum(math.exp(v) for v in ln_y)
            y = [math.exp(v) / ys for v in ln_y]
            _, lnphi_y, _ = eos.stable_root(T, P, y)
            new = [di - lp for di, lp in zip(d, lnphi_y)]
            err = max(abs(a - b) for a, b in zip(new, ln_y))
            ln_y = new
            if err < 1e-10:
                break
        y_mole = [math.exp(v) for v in ln_y]
        sum_y = sum(y_mole)
        trivial = max(abs(v - math.log(zi)) for v, zi in zip(ln_y, z)) < 1e-4
        unstable = (not trivial) and sum_y > 1.0 + 1e-8
        trials.append({"kind": kind, "iterations": iterations, "sum_Y": sum_y, "tpd": 1.0 - sum_y,
                       "trivial": trivial, "unstable": unstable, "y": [v / sum_y for v in y_mole]})
        if unstable and (best is None or sum_y > best[0]):
            if kind == "vapor-like":
                k_start = [(v / sum_y) / zi for v, zi in zip(y_mole, z)]
            else:
                k_start = [zi / (v / sum_y) for v, zi in zip(y_mole, z)]
            best = (sum_y, k_start)
    if tr is not None:
        tr["stability"] = {"unstable": best is not None, "trials": trials}
    if best is None:
        if tr is not None:
            tr["successive_substitution"], tr["newton"], tr["split"] = [], [], None
        return _single(eos, T, P, z, zf, mix_z, True, 0, tr)
    return _two_phase(eos, T, P, z, best[1], zf, mix_z, tr)


def _fugacity_pair(eos, T, P, x, y):
    """ln phi of the liquid at x (smallest root) and the vapour at y (largest root), with their Z."""
    rx = eos.z_roots(T, P, x)
    ry = eos.z_roots(T, P, y)
    if not rx or not ry:
        return None
    zl, zv = rx[0], ry[-1]
    return eos.ln_phi(T, P, x, zl), eos.ln_phi(T, P, y, zv), zl, zv


def _evaluate(eos, T, P, z, u):
    k = [math.exp(v) for v in u]
    if not max(k) > 1.0 > min(k):
        return None
    v = rachford_rice(z, k)
    x = [zi / (1.0 + v * (ki - 1.0)) for zi, ki in zip(z, k)]
    y = [ki * xi for ki, xi in zip(k, x)]
    if min(x) <= 0 or min(y) <= 0:
        return None
    pair = _fugacity_pair(eos, T, P, x, y)
    if pair is None:
        return None
    lnl, lnv, zl, zv = pair
    g = [a - b - ui for a, b, ui in zip(lnl, lnv, u)]
    return g, v, x, y, zl, zv


def _solve_linear(a: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-300:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    out = [0.0] * n
    for r in range(n - 1, -1, -1):
        out[r] = (m[r][n] - sum(m[r][c] * out[c] for c in range(r + 1, n))) / m[r][r]
    return out


def _two_phase(eos, T, P, z, k0, zf, mix_z, tr) -> FlashResult:
    n = eos.n
    u = [math.log(k) for k in k0]
    ss_log, newton_log = [], []
    state = _evaluate(eos, T, P, z, u)
    iterations = 0
    converged = False
    stop_newton = False
    while state is not None and iterations < _SS_MAX:
        g, v, x, y, zl, zv = state
        err = max(abs(gi) for gi in g)
        if tr is not None:
            ss_log.append({"iteration": iterations, "K": [math.exp(ui) for ui in u], "vapor_fraction": v, "max_ln_fugacity_residual": err})
        if err < 1e-11:
            converged = True
            break
        iterations += 1
        if err < _SS_SWITCH and not stop_newton:
            jac = [[0.0] * n for _ in range(n)]
            ok = True
            for j in range(n):
                up = u[:]
                h = 1e-7
                up[j] += h
                trial = _evaluate(eos, T, P, z, up)
                if trial is None:
                    ok = False
                    break
                for i in range(n):
                    jac[i][j] = (trial[0][i] - g[i]) / h
            step = _solve_linear(jac, [-gi for gi in g]) if ok else None
            if step is not None:
                lam = 1.0
                accepted = None
                for _ in range(8):
                    cand = [ui + lam * si for ui, si in zip(u, step)]
                    trial = _evaluate(eos, T, P, z, cand)
                    if trial is not None and max(abs(gi) for gi in trial[0]) < err:
                        accepted = (cand, trial)
                        break
                    lam *= 0.5
                if accepted:
                    u, state = accepted
                    if tr is not None:
                        newton_log.append({"iteration": iterations, "step_scale": lam,
                                           "max_ln_fugacity_residual": max(abs(gi) for gi in state[0])})
                    continue
            stop_newton = True
        u = [ui + gi for ui, gi in zip(u, g)]
        state = _evaluate(eos, T, P, z, u)
    if tr is not None:
        tr["successive_substitution"] = ss_log
        tr["newton"] = newton_log
    if state is None:
        return _single(eos, T, P, z, zf, mix_z, False, iterations, tr)
    g, v, x, y, zl, zv = state
    if max(abs(ui) for ui in u) < 1e-6 or not 1e-12 < v < 1.0 - 1e-12:
        if tr is not None:
            tr["split"] = None
            tr["note"] = "split collapsed to one phase"
        outside = not 1e-12 < v < 1.0 - 1e-12
        return _single(eos, T, P, z, zf, mix_z, converged or outside, iterations, tr)
    phases = (
        PhaseSplit("gas", tuple(y), v, zv, "vapor"),
        PhaseSplit("liquid", tuple(x), 1.0 - v, zl, "liquid"),
    )
    if tr is not None:
        tr["split"] = {"vapor_fraction": v, "x": x, "y": y, "Z_liquid": zl, "Z_vapor": zv,
                       "max_ln_fugacity_residual": max(abs(gi) for gi in g), "converged": converged}
    return FlashResult(phases, converged, iterations, tr)


def _wilson_psat(eos: CubicEOS, T: float) -> list[float]:
    return [c.pc * 1e5 * math.exp(5.373 * (1.0 + c.omega) * (1.0 - c.tc / T)) for c in eos.components]


def _saturation(eos: CubicEOS, T: float, z: Sequence[float], kind: str) -> float:
    z = _normalise(z, eos.n)
    psat = _wilson_psat(eos, T)
    if kind == "bubble":
        p = sum(zi * pi for zi, pi in zip(z, psat))
    else:
        p = 1.0 / sum(zi / pi for zi, pi in zip(z, psat))
    k = [pi / p for pi in psat]
    for _ in range(400):
        if kind == "bubble":
            s = sum(zi * ki for zi, ki in zip(z, k))
            incipient = [zi * ki / s for zi, ki in zip(z, k)]
            liquid, vapor = z, incipient
        else:
            s = sum(zi / ki for zi, ki in zip(z, k))
            incipient = [zi / ki / s for zi, ki in zip(z, k)]
            liquid, vapor = incipient, z
        rl, rv = eos.z_roots(T, p, liquid), eos.z_roots(T, p, vapor)
        if not rl or not rv:
            p *= 1.2 if kind == "bubble" else 0.8
            continue
        lnl = eos.ln_phi(T, p, liquid, rl[0])
        lnv = eos.ln_phi(T, p, vapor, rv[-1])
        new_k = [math.exp(a - b) for a, b in zip(lnl, lnv)]
        s_new = sum(zi * ki for zi, ki in zip(z, new_k)) if kind == "bubble" else sum(zi / ki for zi, ki in zip(z, new_k))
        change = max(abs(math.log(a / b)) for a, b in zip(new_k, k))
        k = new_k
        if abs(math.log(s_new)) < 1e-12 and change < 1e-10:
            if max(abs(math.log(ki)) for ki in k) < 1e-5:
                raise UnsupportedStateError(f"No {kind} point at {T:g} K: the trial phase collapsed onto the feed.")
            return p
        p = p * s_new if kind == "bubble" else p / s_new
    raise UnsupportedStateError(f"The {kind} pressure at {T:g} K did not converge.")


def bubble_pressure(eos: CubicEOS, T: float, z: Sequence[float]) -> float:
    return _saturation(eos, T, z, "bubble")


def dew_pressure(eos: CubicEOS, T: float, z: Sequence[float]) -> float:
    return _saturation(eos, T, z, "dew")


def phase_envelope(eos: CubicEOS, z: Sequence[float], temperatures: Sequence[float]) -> list[dict]:
    """Bubble and dew pressure per temperature; None where no such point exists at that temperature."""
    out = []
    for t in temperatures:
        row: dict = {"T": t, "bubble": None, "dew": None}
        for kind, key in (("bubble", "bubble"), ("dew", "dew")):
            try:
                row[key] = _saturation(eos, t, z, kind)
            except (PvtEngineError, ValueError, ZeroDivisionError, OverflowError):
                row[key] = None
        out.append(row)
    return out
