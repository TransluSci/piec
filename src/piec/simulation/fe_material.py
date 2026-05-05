"""
Ferroelectric Material Simulation Module

Classes:
    Material: Base class for all materials
    Resistor: Simulates ohmic resistance
    Dielectric: Simulates linear dielectric response
    Ferroelectric: Simulates ferroelectric behavior with hysteresis
"""

import numpy as np
from scipy.optimize import fsolve

EPSILON_0 = 8.854e-12  # F/m


class Material:
    def __init__(self):
        self.name = "pass_through"

    def voltage_response(self, v, t):
        return v, t


class Resistor(Material):
    def __init__(self, resistance=1e3):
        self.resistance = resistance
        self.name = "resistor"

    def voltage_response(self, v, t):
        return v / self.resistance, t


class Dielectric(Material):
    def __init__(self, permittivity=8.85e-12):
        self.permittivity = permittivity
        self.name = "dielectric"


class Ferroelectric(Material):
    """
    Simulates a ferroelectric material using Landau-Devonshire theory.

    The hysteresis loop is traced by quasi-statically following the stable
    branches of the Landau free energy surface (fsolve branch-tracking). If
    `kinetic_damping` is present in the material dictionary, a frequency-
    dependent RK4 simulation is used instead, and dP/dt is stored directly
    from the integrator so that no secondary np.gradient is needed.

    Free energy convention: G = (a/2)P² + (b/4)P⁴ + (c/6)P⁶
    Electric field: E = dG/dP = a·P + b·P³ + c·P⁵
    Voltage:        V = E · d   (d = film thickness)

    Renormalized coefficients (computed in apply_waveform):
        a_tilde = a0·(T − T0) + a_strain + a_depol
        b_tilde = b  + 4·Q12²/(s11 + s12)
        c_tilde = c
    """

    def __init__(self, material_dict, temperature=300):
        self.name = None
        self.material_dict = material_dict
        self.temperature = temperature
        self.output_voltage = None
        self.t = None

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
        fe  = self.material_dict['ferroelectric']
        sub = self.material_dict['substrate']
        elec = self.material_dict['electrode']
        d = fe['film_thickness']

        eta_m = (sub['lattice_a'] - fe['lattice_a']) / fe['lattice_a']
        a_strain = -4 * fe['Q12'] * eta_m / (fe['s11'] + fe['s12'])
        a_depol  = elec['screening_lambda'] / (EPSILON_0 * elec['permittivity_e'] * d)

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
        roots  = np.roots(coeffs)
        P_sw   = [np.sqrt(np.real(r)) for r in roots if np.isreal(r) and np.real(r) > 0]
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
            V_now  = V_applied_path[i]
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

        fe    = self.material_dict['ferroelectric']
        gamma = fe['kinetic_damping']
        dt    = t[1] - t[0]  # assumes uniform timestep
        P_max = 2 * P_s      # physical clamp bound

        def rate(P, V_target):
            return (V_target - landau_V(P)) / gamma

        P_loop = np.zeros_like(v)
        dP_dt  = np.zeros_like(v)

        P_current = fsolve(residual, x0=-P_s, args=(v[0],))[0]
        P_loop[0] = P_current
        dP_dt[0]  = rate(P_current, v[0])

        for i in range(1, len(v)):
            V_target = v[i]
            k1 = rate(P_current,             V_target)
            k2 = rate(P_current + 0.5*dt*k1, V_target)
            k3 = rate(P_current + 0.5*dt*k2, V_target)
            k4 = rate(P_current +     dt*k3,  V_target)
            avg_rate   = (k1 + 2*k2 + 2*k3 + k4) / 6.0
            P_current  = np.clip(P_current + dt * avg_rate, -P_max, P_max)
            P_loop[i]  = P_current
            dP_dt[i]   = avg_rate

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
        fe   = self.material_dict['ferroelectric']
        elec = self.material_dict['electrode']
        d        = fe['film_thickness']
        epsilon_r = fe['epsilon_r']
        area     = elec['area']
        R_leak   = fe['leakage_resistance']

        P_dielectric = EPSILON_0 * (epsilon_r - 1) * V_applied_path / d

        if t is not None and len(t) > 1:
            delta_t = t[1] - t[0]
        else:
            freq    = frequency if frequency is not None else 1e6
            delta_t = 1.0 / (freq * len(V_applied_path))

        leakage_integral = np.cumsum(V_applied_path) * delta_t
        P_leak = leakage_integral / (area * R_leak)

        P_total = P_ideal_loop + P_dielectric + P_leak
        return P_total, P_dielectric + P_ideal_loop

    # ------------------------------------------------------------------
    # Main entry point called by the virtual AWG
    # ------------------------------------------------------------------

    def apply_waveform(self, v, t):
        """
        Apply voltage waveform v(t) and compute the voltage that would appear
        across a 50 Ω series resistor (proportional to dP/dt · area).

        If `kinetic_damping` is present in the material dictionary the
        frequency-dependent RK4 path is used and dP/dt comes directly from
        the integrator — no np.gradient needed.  Otherwise the quasi-static
        branch-tracking path is used.
        """
        self.t = t
        fe   = self.material_dict['ferroelectric']
        elec = self.material_dict['electrode']
        area = elec['area']
        d    = fe['film_thickness']
        epsilon_r = fe['epsilon_r']
        R_leak    = fe['leakage_resistance']

        if 'kinetic_damping' in fe:
            # --- frequency-dependent path ---
            P_ideal, dP_ideal_dt = self._run_kinetic_simulation(v, t)

            # Analytical derivatives for parasitic contributions (no gradient needed)
            dV_dt             = np.gradient(v, t)
            dP_dielectric_dt  = EPSILON_0 * (epsilon_r - 1) / d * dV_dt
            dP_leak_dt        = v / (area * R_leak)

            dP_total_dt = dP_ideal_dt + dP_dielectric_dt + dP_leak_dt
            self.output_voltage = dP_total_dt * 50.0 * area

        else:
            # --- quasi-static path ---
            P_ideal = self.run_landau_hysteresis_simulation(v)
            P_total, _ = self.add_parasitic_effects(v, P_ideal, t=t)
            self.output_voltage = np.gradient(P_total, t) * 50.0 * area

        # --- post-processing ---------------------------------------------------
        n_prep = getattr(self, 'prep_points', 10)

        # 1. Gaussian bandwidth filter.
        #    Fixed time-constant: higher-frequency loops get more smearing.
        dt     = t[1] - t[0]
        sigma  = 5e-9                          # Gaussian width (s)
        n_half = max(1, int(3 * sigma / dt))   # 3-sigma half-width
        if n_half > 1:
            x = np.arange(-n_half, n_half + 1) * dt
            kernel = np.exp(-0.5 * (x / sigma) ** 2)
            kernel /= kernel.sum()
            self.output_voltage = np.convolve(
                self.output_voltage, kernel, mode='same')

        # 2. Remove DC offset of the active (non-prep) region so that
        #    cumulative integration in the analysis doesn't drift.
        if 0 < n_prep < len(self.output_voltage):
            active = self.output_voltage[n_prep:]
            active -= np.mean(active)          # modifies slice in-place
            self.output_voltage[:n_prep] = 0.0 # clean quiet baseline

    def get_voltage_response(self):
        """Return (output_voltage, time) as measured across the 50 Ω resistor."""
        return self.output_voltage, self.t
