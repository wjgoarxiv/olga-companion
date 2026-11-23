"""Cubic equations of state: Peng-Robinson (1976, 1978 alpha) and Soave-Redlich-Kwong.

Public sources:
- Peng & Robinson, Ind. Eng. Chem. Fundam. 15 (1976) 59; kappa above acentric factor 0.49 from
  Robinson & Peng, GPA Research Report 28 (1978).
- Soave, Chem. Eng. Sci. 27 (1972) 1197.
- Peneloux, Rauzy & Freze, Fluid Phase Equilibria 8 (1982) 7: constant volume translation. The shift moves
  volumes only; fugacities, phase splits and caloric departures use the untranslated volume.
- Spencer & Danner, J. Chem. Eng. Data 17 (1972) 236: Rackett saturated-liquid volume used to set the shift.
- Van der Waals one-fluid mixing, symmetric binary parameters k_ij that default to zero.

Units: SI (K, Pa, m3/mol, J/mol) inside the module; compositions are mole-fraction lists.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Mapping, Sequence

from .components import Component, get_component
from .errors import UnsupportedModelError, UnsupportedStateError

R = 8.314462618  # J/mol/K

SUPPORTED_EOS = ("PR", "PR78", "SRK")

_MODELS = {
    "PR": {"u": 2.0, "w": -1.0, "omega_a": 0.45724, "omega_b": 0.07780, "vc_over_b": 3.951},
    "PR78": {"u": 2.0, "w": -1.0, "omega_a": 0.45724, "omega_b": 0.07780, "vc_over_b": 3.951},
    "SRK": {"u": 1.0, "w": 0.0, "omega_a": 0.42748, "omega_b": 0.08664, "vc_over_b": 3.847},
}


# Share of the repulsive stiffness left at the pseudo-root; the engine's single design constant for it.
PSEUDO_STIFFNESS_FRACTION = 0.1


def _kappa(model: str, omega: float) -> float:
    if model == "SRK":
        return 0.480 + 1.574 * omega - 0.176 * omega ** 2
    if model == "PR78" and omega > 0.49:
        return 0.379642 + 1.48503 * omega - 0.164423 * omega ** 2 + 0.016666 * omega ** 3
    return 0.37464 + 1.54226 * omega - 0.26992 * omega ** 2


def solve_cubic(c2: float, c1: float, c0: float) -> list[float]:
    """Real roots of z^3 + c2 z^2 + c1 z + c0 = 0, ascending, Newton-polished."""
    p = c1 - c2 * c2 / 3.0
    q = 2.0 * c2 ** 3 / 27.0 - c2 * c1 / 3.0 + c0
    disc = (q / 2.0) ** 2 + (p / 3.0) ** 3
    if disc > 0:
        root = math.sqrt(disc)
        s = math.copysign(abs(-q / 2.0 + root) ** (1 / 3), -q / 2.0 + root)
        t = math.copysign(abs(-q / 2.0 - root) ** (1 / 3), -q / 2.0 - root)
        roots = [s + t - c2 / 3.0]
    else:
        m = 2.0 * math.sqrt(-p / 3.0) if p < 0 else 0.0
        if m == 0.0:
            roots = [-c2 / 3.0]
        else:
            arg = max(-1.0, min(1.0, 3.0 * q / (p * m)))
            theta = math.acos(arg) / 3.0
            roots = [m * math.cos(theta - 2.0 * math.pi * k / 3.0) - c2 / 3.0 for k in range(3)]
    polished = []
    for z in roots:
        for _ in range(6):
            f = ((z + c2) * z + c1) * z + c0
            df = (3.0 * z + 2.0 * c2) * z + c1
            if df == 0.0:
                break
            step = f / df
            z -= step
            if abs(step) < 1e-15 * max(1.0, abs(z)):
                break
        polished.append(z)
    polished.sort()
    unique: list[float] = []
    for z in polished:
        if not unique or abs(z - unique[-1]) > 1e-9:
            unique.append(z)
    return unique


class _TData:
    """Temperature-dependent pure and pair terms, built once per temperature."""

    __slots__ = ("T", "aij", "aij1", "aij2")


class Mix:
    """Mixture parameters at one temperature and composition."""

    __slots__ = ("a", "a1", "a2", "b", "c", "s")


class CubicEOS:
    def __init__(
        self,
        model: str,
        components: Sequence[object],
        kij: Mapping[tuple[str, str], float] | None = None,
        shift: bool = True,
    ) -> None:
        if model not in _MODELS:
            raise UnsupportedModelError(
                f"EOS {model!r} is not available in the independent engine. Supported: {', '.join(SUPPORTED_EOS)}."
            )
        self.model = model
        self.components: tuple[Component, ...] = tuple(get_component(c) for c in components)
        self.n = len(self.components)
        self.names = tuple(c.name for c in self.components)
        spec = _MODELS[model]
        self.u, self.w = spec["u"], spec["w"]
        self.sqrt_delta = math.sqrt(self.u ** 2 - 4.0 * self.w)
        self.vc_over_b = spec["vc_over_b"]
        self.kij = [[0.0] * self.n for _ in range(self.n)]
        self.kij_given: dict[tuple[str, str], float] = {}
        for (left, right), value in (kij or {}).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise UnsupportedStateError(f"Binary interaction parameter {left}-{right} must be a finite number.")
            a, b = get_component(left).name, get_component(right).name
            if a not in self.names or b not in self.names or a == b:
                raise UnsupportedStateError(f"Binary interaction parameter {left}-{right} names a pair that is not in the fluid.")
            i, j = self.names.index(a), self.names.index(b)
            self.kij[i][j] = self.kij[j][i] = float(value)
            self.kij_given[(a, b)] = float(value)
        self.bi = [spec["omega_b"] * R * c.tc / (c.pc * 1e5) for c in self.components]
        self.ac = [spec["omega_a"] * R ** 2 * c.tc ** 2 / (c.pc * 1e5) for c in self.components]
        self.kappa = [_kappa(model, c.omega) for c in self.components]
        self.mw = [c.molar_mass / 1000.0 for c in self.components]  # kg/mol
        self.ci = [peneloux_shift(model, c) if shift else 0.0 for c in self.components]
        self.shift = shift
        self._tcache: _TData | None = None

    # -- temperature terms -------------------------------------------------
    def _tdata(self, T: float) -> _TData:
        cached = self._tcache
        if cached is not None and cached.T == T:
            return cached
        f, f1, f2 = [], [], []
        for comp, kappa in zip(self.components, self.kappa):
            sq = math.sqrt(T * comp.tc)
            fi = 1.0 + kappa * (1.0 - math.sqrt(T / comp.tc))
            if fi <= 0.0:
                raise UnsupportedStateError(f"The alpha function of {comp.name} is not usable at {T:g} K.")
            f.append(fi)
            f1.append(-kappa / (2.0 * sq))
            f2.append(kappa / (4.0 * T * sq))
        n = self.n
        data = _TData()
        data.T = T
        data.aij = [[0.0] * n for _ in range(n)]
        data.aij1 = [[0.0] * n for _ in range(n)]
        data.aij2 = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i, n):
                base = (1.0 - self.kij[i][j]) * math.sqrt(self.ac[i] * self.ac[j])
                v0 = base * f[i] * f[j]
                v1 = base * (f1[i] * f[j] + f[i] * f1[j])
                v2 = base * (f2[i] * f[j] + 2.0 * f1[i] * f1[j] + f[i] * f2[j])
                data.aij[i][j] = data.aij[j][i] = v0
                data.aij1[i][j] = data.aij1[j][i] = v1
                data.aij2[i][j] = data.aij2[j][i] = v2
        self._tcache = data
        return data

    def mix(self, T: float, x: Sequence[float]) -> Mix:
        data = self._tdata(T)
        n = self.n
        m = Mix()
        m.s = [sum(x[j] * data.aij[i][j] for j in range(n)) for i in range(n)]
        m.a = sum(x[i] * m.s[i] for i in range(n))
        m.a1 = sum(x[i] * x[j] * data.aij1[i][j] for i in range(n) for j in range(n))
        m.a2 = sum(x[i] * x[j] * data.aij2[i][j] for i in range(n) for j in range(n))
        m.b = sum(x[i] * self.bi[i] for i in range(n))
        m.c = sum(x[i] * self.ci[i] for i in range(n))
        return m

    # -- compressibility roots ---------------------------------------------
    def z_roots(self, T: float, P: float, x: Sequence[float], mix: Mix | None = None) -> list[float]:
        m = mix or self.mix(T, x)
        A = m.a * P / (R * T) ** 2
        B = m.b * P / (R * T)
        u, w = self.u, self.w
        c2 = -(1.0 + B - u * B)
        c1 = A + w * B * B - u * B - u * B * B
        c0 = -(A * B + w * B * B + w * B ** 3)
        return [z for z in solve_cubic(c2, c1, c0) if z > B * (1.0 + 1e-12)]

    def ln_phi(self, T: float, P: float, x: Sequence[float], Z: float, mix: Mix | None = None) -> list[float]:
        m = mix or self.mix(T, x)
        A = m.a * P / (R * T) ** 2
        B = m.b * P / (R * T)
        u, sd = self.u, self.sqrt_delta
        log_term = math.log((2.0 * Z + B * (u + sd)) / (2.0 * Z + B * (u - sd)))
        base = -math.log(Z - B)
        out = []
        for i in range(self.n):
            bi_b = self.bi[i] / m.b
            out.append(bi_b * (Z - 1.0) + base - A / (B * sd) * (2.0 * m.s[i] / m.a - bi_b) * log_term)
        return out

    def is_liquid_like(self, T: float, P: float, x: Sequence[float], Z: float, mix: Mix | None = None) -> bool:
        m = mix or self.mix(T, x)
        return Z * R * T / P / m.b < self.vc_over_b

    def stable_root(self, T: float, P: float, x: Sequence[float], mix: Mix | None = None):
        """Lowest-Gibbs-energy root: (Z, ln_phi, roots)."""
        m = mix or self.mix(T, x)
        roots = self.z_roots(T, P, x, m)
        if not roots:
            raise UnsupportedStateError(f"No physical volume root at {T:g} K, {P:g} Pa.")
        best = None
        for z in roots:
            lnp = self.ln_phi(T, P, x, z, m)
            g = sum(xi * li for xi, li in zip(x, lnp))
            if best is None or g < best[0]:
                best = (g, z, lnp)
        return best[1], best[2], roots

    # -- volumes and derivatives -------------------------------------------
    def pressure_derivatives(self, T: float, v: float, m: Mix) -> tuple[float, float]:
        """(dP/dv)_T and (dP/dT)_v on the untranslated volume."""
        b, u, w = m.b, self.u, self.w
        q = v * v + u * b * v + w * b * b
        dpdv = -R * T / (v - b) ** 2 + m.a * (2.0 * v + u * b) / q ** 2
        dpdt = R / (v - b) - m.a1 / q
        return dpdv, dpdt

    def molar_mass(self, x: Sequence[float]) -> float:
        """kg/mol."""
        return sum(xi * mi for xi, mi in zip(x, self.mw))

    def density_at_root(self, T: float, P: float, x: Sequence[float], which: str) -> float:
        """Translated mass density (kg/m3) at the vapor (largest) or liquid (smallest) root."""
        m = self.mix(T, x)
        roots = self.z_roots(T, P, x, m)
        if not roots:
            raise UnsupportedStateError(f"No physical volume root at {T:g} K, {P:g} Pa.")
        z = roots[-1] if which == "vapor" else roots[0]
        return self.molar_mass(x) / (z * R * T / P - m.c)

    # -- pseudo-root for a phase that has no cubic root ---------------------
    def pressure(self, T: float, v: float, m: Mix) -> float:
        """EOS pressure (Pa) at the untranslated molar volume ``v`` (m3/mol)."""
        return R * T / (v - m.b) - m.a / (v * v + self.u * m.b * v + self.w * m.b * m.b)

    def pseudo_volume(self, T: float, x: Sequence[float], which: str, mix: Mix | None = None) -> float:
        """Untranslated molar volume (m3/mol) of the liquid-like or vapour-like pseudo-root.

        Where the cubic has one real root the other phase has no root at all. Mathias, Boston & Watanasiri
        (1984, AIChE J. 30:182) and Gosset, Heyen & Kalitventzeff (1986, Fluid Phase Equilib. 25:51) replace
        a missing root by a continuous stand-in so that every column stays defined and smooth. Their texts
        were not available to this engine; the construction below is its own, built to the same purpose.

        With y = v/b the isothermal stiffness is -dP/dv = RT/(b^2 (y-1)^2) * (1 - L g(y)), where
        L = a/(R T b) and g(y) = (2y+u)(y-1)^2/(y^2+u y+w)^2. The attraction term L g(y) cancels the repulsive
        stiffness exactly at the spinodals and peaks at y = vc/b (the critical-point condition), so:
        - the liquid-like volume is the smaller y at which L g(y) = 1 - f, the vapour-like volume the larger
          y, with f = ``PSEUDO_STIFFNESS_FRACTION`` of the repulsive stiffness left (a stable state, finite
          compressibility, never inside the loop);
        - when L g never reaches 1 - f (supercritical) both stand-ins sit at the critical volume vc.
        The volume depends on T and composition only, so the stand-in is bounded, smooth and monotone in T,
        and it joins the real root's branch where one exists.
        """
        m = mix or self.mix(T, x)
        lam = m.a / (R * T * m.b)
        u, w = self.u, self.w

        def level(y: float) -> float:
            return lam * (2.0 * y + u) * (y - 1.0) ** 2 / (y * y + u * y + w) ** 2

        y_c = self.vc_over_b
        target = 1.0 - PSEUDO_STIFFNESS_FRACTION
        if level(y_c) <= target:
            return y_c * m.b
        if which == "liquid":
            lo, hi = 1.0, y_c  # level rises from 0 to its peak on (1, vc/b)
            for _ in range(80):
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if level(mid) < target else (lo, mid)
        else:
            lo, hi = y_c, 10.0 * y_c + 4.0 * lam  # level falls like 2 L / y beyond the peak
            for _ in range(80):
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if level(mid) > target else (lo, mid)
        return 0.5 * (lo + hi) * m.b


def _rackett_volume(comp: Component, T: float) -> float:
    z_ra = 0.29056 - 0.08775 * comp.omega
    tr = T / comp.tc
    return R * comp.tc / (comp.pc * 1e5) * z_ra ** (1.0 + (1.0 - tr) ** (2.0 / 7.0))


def pure_saturation_pressure(eos: CubicEOS, T: float) -> float:
    """Saturation pressure (Pa) of a one-component EOS by successive substitution on P."""
    if eos.n != 1:
        raise UnsupportedStateError("Saturation pressure of a pure component needs a one-component EOS.")
    comp = eos.components[0]
    if T >= comp.tc:
        raise UnsupportedStateError(f"{comp.name} has no vapour pressure above its critical temperature.")
    x = [1.0]
    P = comp.pc * 1e5 * math.exp(5.373 * (1.0 + comp.omega) * (1.0 - comp.tc / T))
    for _ in range(300):
        m = eos.mix(T, x)
        roots = eos.z_roots(T, P, x, m)
        if len(roots) < 2:
            if roots and eos.is_liquid_like(T, P, x, roots[0], m):
                P *= 0.9
            else:
                P *= 1.1
            continue
        lnl = eos.ln_phi(T, P, x, roots[0], m)[0]
        lnv = eos.ln_phi(T, P, x, roots[-1], m)[0]
        diff = lnl - lnv
        P *= math.exp(diff)
        if abs(diff) < 1e-13:
            return P
    raise UnsupportedStateError(f"Saturation pressure of {comp.name} at {T:g} K did not converge.")


@lru_cache(maxsize=None)
def peneloux_shift(model: str, comp: Component) -> float:
    """Constant volume shift (m3/mol) that matches the Rackett saturated-liquid volume.

    Calibrated at the lower of 0.7 Tc and 298.15 K.
    """
    t_cal = min(0.7 * comp.tc, 298.15)
    eos = CubicEOS(model, [comp], shift=False)
    psat = pure_saturation_pressure(eos, t_cal)
    z_liq = eos.z_roots(t_cal, psat, [1.0])[0]
    return z_liq * R * t_cal / psat - _rackett_volume(comp, t_cal)


def _subset(self: CubicEOS, idx: tuple[int, ...]) -> CubicEOS:
    """The same EOS restricted to the components at ``idx`` (cached; used for zero-amount components)."""
    cache = self.__dict__.setdefault("_subsets", {})
    if idx not in cache:
        names = [self.names[i] for i in idx]
        given = {pair: v for pair, v in self.kij_given.items() if pair[0] in names and pair[1] in names}
        cache[idx] = CubicEOS(self.model, [self.components[i] for i in idx], kij=given, shift=self.shift)
    return cache[idx]


CubicEOS.subset = _subset
