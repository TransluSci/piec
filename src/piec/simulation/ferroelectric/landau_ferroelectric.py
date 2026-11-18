"""Level-3 Landau-Devonshire ferroelectric simulation model."""
import numpy as np
from scipy.optimize import fsolve
from .ferroelectric import FerroelectricMaterial

EPSILON_0 = 8.854e-12  # F/m

# Calibrated SRO / PZT(52/48) / Pt default parameters
# (Pr ~ 49 uC/cm^2, Ec ~ 61 MV/m, Vc(20 nm) ~ 1.2 V)
DEFAULT_FE_MATERIAL = {
    'ferroelectric': {
        'a0': 5.362e5,              # J*m/(C^2*K)
        'b': -1.287e9,              # J*m^5/C^4
        'c': 5.0e9,                 # J*m^9/C^6
        'T0': 673.0,                # K
        'Q12': -0.046,              # m^4/C^2
        's11': 14.1e-12,            # m^2/N
        's12': -4.56e-12,           # m^2/N
        'lattice_a': 0.395e-9,      # m
        'film_thickness': 20e-9,    # m
        'epsilon_r': 50,
        'leakage_resistance': 10e12,  # Ohm
    },
    'substrate': {
        'lattice_a': 0.395e-9,      # m
    },
    'electrode': {
        'screening_lambda': 0.05e-9,  # m
        'permittivity_e': 1e6,
        'area': 1.0e-10,            # m^2
    },
}


class LandauFerroelectric(FerroelectricMaterial):
    """
    Simulates a ferroelectric material using Landau-Devonshire theory.

    The hysteresis loop is traced by quasi-statically following the stable
    branches of the Landau free energy surface (fsolve branch-tracking). If
    `kinetic_damping` is present in the parameter dictionary, a frequency-
    dependent RK4 simulation is used instead, and dP/dt is stored directly
    from the integrator so that no secondary np.gradient is needed.

    Free energy convention: G = (a/2)P² + (b/4)P⁴ + (c/6)P⁶
    Electric field: E = dG/dP = a·P + b·P³ + c·P⁵
    Voltage:        V = E · d   (d = film thickness)

    Renormalized coefficients:
        a_tilde = a0·(T − T0) + a_strain + a_depol
        b_tilde = b  + 4·Q12²/(s11 + s12)
        c_tilde = c
    """

    def __init__(self, parameter_dict=None, temperature=300, *, name="virtual_fe_sample"):
        super().__init__(parameter_dict=parameter_dict, name=name)
        for section, defaults in DEFAULT_FE_MATERIAL.items():
            sec_dict = self.parameter_dict.setdefault(section, {})
            for key, val in defaults.items():
                sec_dict.setdefault(key, val)
        self.temperature = float(self.parameter_dict.setdefault('temperature', temperature))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_renormalized_coefficients(self, temperature=None):
        """Return (a_tilde, b_tilde, c_tilde, d, landau_V, residual, P_s).

        P_s is the spontaneous polarization computed from the equilibrium
        condition dG/dP = 0  →  a + b·P² + c·P⁴ = 0  (quadratic in P²).
        """
        if temperature is None:
            temperature = self.temperature
        fe = self.parameter_dict['ferroelectric']
        sub = self.parameter_dict['substrate']
        elec = self.parameter_dict['electrode']
        d = fe['film_thickness']

        eta_m = (sub['lattice_a'] - fe['lattice_a']) / fe['lattice_a']
        a_strain = -4 * fe['Q12'] * eta_m / (fe['s11'] + fe['s12'])
        a_depol = elec['screening_lambda'] / (EPSILON_0 * elec['permittivity_e'] * d)

        a_tilde = fe['a0'] * (temperature - fe['T0']) + a_strain + a_depol
        b_tilde = fe['b'] + 4 * fe['Q12'] ** 2 / (fe['s11'] + fe['s12'])
        c_tilde = fe['c']

        def landau_V(P):
            return (a_tilde * P + b_tilde * P ** 3 + c_tilde * P ** 5) * d

        def residual(P, V_target):
            return landau_V(P) - V_target

        # Spontaneous polarization from a + b·P² + c·P⁴ = 0
        disc = b_tilde**2 - 4 * c_tilde * a_tilde
        if disc > 0:
            u = (-b_tilde + np.sqrt(disc)) / (2 * c_tilde)
            P_s = np.sqrt(u) if u > 0 else 0.01
        else:
            P_s = 0.01  # paraelectric / fallback

        return a_tilde, b_tilde, c_tilde, d, landau_V, residual, P_s

    def _find_switching_voltages(self, a_tilde, b_tilde, c_tilde, landau_V):
        """Return (V_c_neg, V_c_pos) coercive voltages from Landau coefficients.

        The switching point P_sw satisfies dE/dP = 0, and landau_V(P_sw) is
        the voltage at which the *same-sign* branch becomes unstable.  For
        first-order ferroelectrics this value is negative (the local extremum
        of E sits below zero), so we take its magnitude to recover the
        symmetric ±Vc pair.
        """
        coeffs = [5 * c_tilde, 3 * b_tilde, a_tilde]
        roots = np.roots(coeffs)
        P_sw = [np.sqrt(np.real(r)) for r in roots if np.isreal(r) and np.real(r) > 0]
        if not P_sw:
            return -np.inf, np.inf  # no switching (paraelectric or 2nd-order)
        Vc = min(abs(landau_V(p)) for p in P_sw)
        return -Vc, Vc

    # ------------------------------------------------------------------
    # Quasi-static simulation (branch-tracking, frequency-independent)
    # ------------------------------------------------------------------

    def run_landau_hysteresis_simulation(self, V_applied_path, temperature=None):
        """
        Trace the ferroelectric hysteresis loop using quasi-static branch tracking.

        At each voltage step the solver stays on whichever stable branch of the
        Landau free energy the system is currently on, switching to the opposite
        branch when the applied voltage crosses the coercive voltage.

        Args:
            V_applied_path (ndarray): Applied voltage waveform (V).
            temperature (float, optional): Override temperature (K).

        Returns:
            ndarray: Polarization response (C/m²).
        """
        a_tilde, b_tilde, c_tilde, d, landau_V, residual, P_s = \
            self._compute_renormalized_coefficients(temperature)

        V_c_neg, V_c_pos = self._find_switching_voltages(a_tilde, b_tilde, c_tilde, landau_V)

        P_loop = np.zeros_like(V_applied_path)
        P_current = fsolve(residual, x0=-P_s, args=(V_applied_path[0],))[0]
        P_loop[0] = P_current
        on_upper_branch = P_current > 0

        for i in range(1, len(V_applied_path)):
            V_now = V_applied_path[i]
            V_prev = V_applied_path[i - 1]
            going_up = V_now > V_prev

            guess = P_current
            if going_up and not on_upper_branch and V_now >= V_c_pos:
                guess = P_s
                on_upper_branch = True
            elif not going_up and on_upper_branch and V_now <= V_c_neg:
                guess = -P_s
                on_upper_branch = False

            sol, info, ier, _ = fsolve(residual, x0=guess, args=(V_now,), full_output=True)
            if ier == 1:
                P_current = sol[0]
            else:
                # Convergence failed — keep previous value as best estimate
                P_current = np.clip(P_current, -2 * P_s, 2 * P_s)
            P_loop[i] = P_current

        return P_loop

    # ------------------------------------------------------------------
    # Kinetic (frequency-dependent) simulation
    # ------------------------------------------------------------------

    def _run_kinetic_simulation(self, v, t):
        """
        Integrate dP/dt = (V − V_Landau(P)) / γ using RK4.

        dP/dt is stored at every step directly from the integrator, so that
        output_voltage = dP/dt · 50 Ω · area requires no secondary np.gradient.

        Returns:
            P_loop (ndarray): Polarization (C/m²).
            dP_dt  (ndarray): Time-derivative of polarization (C/m²/s).
        """
        a_tilde, b_tilde, c_tilde, d, landau_V, residual, P_s = \
            self._compute_renormalized_coefficients()

        gamma = self.parameter_dict['ferroelectric']['kinetic_damping']
        dt = t[1] - t[0]  # assumes uniform timestep
        P_max = 2 * P_s    # physical clamp bound

        def rate(P, V_target):
            return (V_target - landau_V(P)) / gamma

        P_loop = np.zeros_like(v)
        dP_dt = np.zeros_like(v)

        P_current = fsolve(residual, x0=-P_s, args=(v[0],))[0]
        P_loop[0] = P_current
        dP_dt[0] = rate(P_current, v[0])

        for i in range(1, len(v)):
            V_target = v[i]
            k1 = rate(P_current, V_target)
            k2 = rate(P_current + 0.5 * dt * k1, V_target)
            k3 = rate(P_current + 0.5 * dt * k2, V_target)
            k4 = rate(P_current + dt * k3, V_target)
            avg_rate = (k1 + 2 * k2 + 2 * k3 + k4) / 6.0
            P_current = np.clip(P_current + dt * avg_rate, -P_max, P_max)
            P_loop[i] = P_current
            dP_dt[i] = avg_rate

        return P_loop, dP_dt

    # ------------------------------------------------------------------
    # Parasitic effects
    # ------------------------------------------------------------------

    def add_parasitic_effects(self, V_applied_path, P_ideal_loop, t=None, frequency=None):
        """
        Add linear dielectric and ohmic leakage contributions.

        Args:
            V_applied_path (ndarray): Applied voltage (V).
            P_ideal_loop   (ndarray): Ideal Landau polarization (C/m²).
            t (ndarray, optional): Time array (s). Used for leakage integral.
            frequency (float, optional): Fallback frequency if t is None (Hz).

        Returns:
            tuple: (P_total, P_without_leakage) both in C/m².
        """
        fe = self.parameter_dict['ferroelectric']
        elec = self.parameter_dict['electrode']
        d = fe['film_thickness']
        epsilon_r = fe['epsilon_r']
        area = elec['area']
        R_leak = fe['leakage_resistance']

        P_dielectric = EPSILON_0 * (epsilon_r - 1) * V_applied_path / d

        if t is not None and len(t) > 1:
            delta_t = t[1] - t[0]
        else:
            freq = frequency if frequency is not None else 1e6
            delta_t = 1.0 / (freq * len(V_applied_path))

        leakage_integral = np.cumsum(V_applied_path) * delta_t
        P_leak = leakage_integral / (area * R_leak)

        P_total = P_ideal_loop + P_dielectric + P_leak
        return P_total, P_dielectric + P_ideal_loop

    # ------------------------------------------------------------------
    # Level-2 Contract Implementations
    # ------------------------------------------------------------------

    def apply_voltage(self, v, t=0.0):
        """Apply DC voltage or waveform ``v(t)`` (V) and return current in Amperes.

        For scalar DC inputs (or when ``t`` is scalar), returns the DC leakage
        current ``v / leakage_resistance``. For 1D waveform arrays ``(v, t)``,
        computes the displacement + dielectric + leakage current ``dP/dt * area``
        using either the frequency-dependent RK4 path (when ``kinetic_damping``
        is in ``parameter_dict['ferroelectric']``) or quasi-static branch
        tracking, followed by the 5 ns Gaussian filter and active-region DC
        offset removal.
        """
        fe = self.parameter_dict['ferroelectric']
        elec = self.parameter_dict['electrode']
        r_leak = fe['leakage_resistance']
        if np.ndim(v) == 0 or np.ndim(t) == 0 or len(np.atleast_1d(v)) <= 1:
            v_arr = np.asarray(v, dtype=float)
            current = v_arr / r_leak if (r_leak is not None and r_leak > 0) else v_arr
            return float(current) if np.ndim(v) == 0 else current

        v_arr = np.asarray(v, dtype=float)
        t_arr = np.asarray(t, dtype=float)
        area = elec['area']
        d = fe['film_thickness']
        epsilon_r = fe['epsilon_r']

        if 'kinetic_damping' in fe:
            _, dP_ideal_dt = self._run_kinetic_simulation(v_arr, t_arr)
            dV_dt = np.gradient(v_arr, t_arr)
            dP_dielectric_dt = EPSILON_0 * (epsilon_r - 1) / d * dV_dt
            dP_leak_dt = v_arr / (area * r_leak)
            dP_total_dt = dP_ideal_dt + dP_dielectric_dt + dP_leak_dt
            current = dP_total_dt * area
        else:
            P_ideal = self.run_landau_hysteresis_simulation(v_arr)
            P_total, _ = self.add_parasitic_effects(v_arr, P_ideal, t=t_arr)
            current = np.gradient(P_total, t_arr) * area

        n_prep = 20 if (len(current) > 20 and np.all(v_arr[:20] == 0)) else 0

        # 1. Gaussian bandwidth filter (fixed 5 ns time-constant).
        dt = t_arr[1] - t_arr[0]
        sigma = 5e-9
        n_half = max(1, int(3 * sigma / dt))
        if n_half > 1:
            x = np.arange(-n_half, n_half + 1) * dt
            kernel = np.exp(-0.5 * (x / sigma) ** 2)
            kernel /= kernel.sum()
            current = np.convolve(current, kernel, mode='same')

        # 2. Remove DC offset of the active region so integration does not drift.
        if 0 < n_prep < len(current):
            active = current[n_prep:]
            active -= np.mean(active)
            current[:n_prep] = 0.0

        return current


Ferroelectric = LandauFerroelectric
