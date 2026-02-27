"""
Ferroelectric Material Simulation Module

This module provides classes for simulating various materials including resistors,
dielectrics, and ferroelectrics. It implements Landau-Devonshire theory for 
ferroelectric hysteresis and includes parasitic effects like leakage current.

Classes:
    Material: Base class for all materials
    Resistor: Simulates ohmic resistance
    Dielectric: Simulates linear dielectric response
    Ferroelectric: Simulates ferroelectric behavior with hysteresis
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import fsolve

class Material:
    """
    Base class for all material simulations.
    
    Provides a pass-through implementation that returns input unchanged.
    Serves as parent class for specific material implementations.
    """
    def __init__(self):
        """Initialize base material."""
        self.name = "pass_through"

    def voltage_response(self, v, t):
        """
        Calculate voltage response for applied waveform.
        
        Args:
            v (ndarray): Voltage waveform array
            t (ndarray): Time points array
            
        Returns:
            tuple: (voltage_response, time_array)
        """
        return v, t

class Resistor(Material):
    """
    Simulates an ideal ohmic resistor.
    
    Implements V=IR relationship for linear current response.
    """
    def __init__(self, resistance=1e3):
        """
        Initialize resistor with given resistance.
        
        Args:
            resistance (float): Resistance in ohms, defaults to 1kΩ
        """
        self.resistance = resistance
        self.name = "resistor"
    
    def voltage_response(self, v, t):
        """
        Calculate current through resistor using Ohm's law.
        
        Args:
            v (ndarray): Applied voltage array
            t (ndarray): Time points array
            
        Returns:
            tuple: (current_response, time_array) where current = V/R
        """
        return v/self.resistance, t

class Dielectric(Material):
    """
    Simulates an ideal linear dielectric material.
    
    Models displacement current response based on permittivity.
    """
    def __init__(self, permittivity=8.85e-12):
        """
        Initialize dielectric with given permittivity.
        
        Args:
            permittivity (float): Material permittivity in F/m, defaults to ε₀
        """
        self.permittivity = permittivity
        self.name = "dielectric"

class Ferroelectric(Material):
    """
    Simulates a ferroelectric material using Landau-Devonshire theory.
    
    Includes:
    - Hysteresis loop calculation
    - Temperature dependence
    - Strain effects
    - Parasitic effects (leakage, linear dielectric)
    
    Attributes:
        material_dict (dict): Material parameters including:
            - ferroelectric: Properties of ferroelectric layer
            - substrate: Properties of substrate
            - electrode: Properties of electrodes
        temperature (float): Operating temperature in Kelvin
        name (str): Material identifier
    """
    
    def __init__(self, material_dict, temperature=300):
        """
        Initialize ferroelectric material simulation.
        
        Args:
            material_dict (dict): Material parameters dictionary
            temperature (float): Temperature in Kelvin, defaults to 300K
        """
        self.name = None
        self.material_dict = material_dict
        self.temperature = temperature
    
    def run_landau_hysteresis_simulation(self, V_applied_path, temperature=300):
        """
        Calculate ferroelectric hysteresis using Landau-Devonshire theory.
        
        Args:
            V_applied_path (ndarray): Applied voltage waveform
            temperature (float): Temperature in Kelvin
            
        Returns:
            ndarray: Polarization response array
        """
        # This function is the same as the previous response that traces the loop.
        # It calculates and returns V_applied_path and P_loop (the ideal ferroelectric loop).
        fe = self.material_dict['ferroelectric']
        sub = self.material_dict['substrate']
        elec = self.material_dict['electrode']
        film_thickness = fe['film_thickness']
        EPSILON_0 = 8.854e-12
        #plt.plot(np.arange(len(V_applied_path)), V_applied_path)
        #V_applied_peak = V_pp / 2.0
        eta_m = (sub['lattice_a'] - fe['lattice_a']) / fe['lattice_a']
        a_strain_term = -4 * fe['Q12'] * eta_m / (fe['s11'] + fe['s12'])
        a_depol_term = elec['screening_lambda'] / (EPSILON_0 * elec['permittivity_e'] * film_thickness)
        a_tilde = fe['a0'] * (temperature - fe['T0']) + a_strain_term + a_depol_term
        b_tilde = fe['b'] + (4 * fe['Q12']**2) / (fe['s11'] + fe['s12'])
        c_tilde = fe['c']
        def landau_voltage_function(P_val):
            return (a_tilde * P_val + b_tilde * P_val**3 + c_tilde * P_val**5) * film_thickness
        def equation_to_solve(P_val, V_target):
            return landau_voltage_function(P_val) - V_target
        coeffs_for_P_squared = [5 * c_tilde, 3 * b_tilde, a_tilde]
        roots_P_squared = np.roots(coeffs_for_P_squared)
        P_switching_points = [np.sqrt(np.real(r_P2)) for r_P2 in roots_P_squared if np.isreal(r_P2) and r_P2 > 0]
        V_switching = sorted([landau_voltage_function(p_sw) for p_sw in P_switching_points])
        V_c_negative, V_c_positive = -V_switching[0], V_switching[0] # Simplified for this example
        #up_ramp = np.linspace(-V_applied_peak, V_applied_peak, num_steps_per_ramp)
        #V_applied_path = np.concatenate([up_ramp, down_ramp])
        P_loop = np.zeros_like(V_applied_path)
        P_current = fsolve(equation_to_solve, x0=np.array([-0.5]), args=(float(V_applied_path[0]),))[0]
        P_loop[0] = P_current
        
        if getattr(self, "t", None) is not None and len(self.t) > 1 and 'kinetic_damping' in fe:
            gamma = fe['kinetic_damping']
            dt = self.t[1] - self.t[0]
            
            def dP_dt(P_val, V_target):
                return (V_target - landau_voltage_function(P_val)) / gamma
                
            for i in range(1, len(V_applied_path)):
                V_target = V_applied_path[i]
                k1 = dP_dt(P_current, V_target)
                k2 = dP_dt(P_current + 0.5 * dt * k1, V_target)
                k3 = dP_dt(P_current + 0.5 * dt * k2, V_target)
                k4 = dP_dt(P_current + dt * k3, V_target)
                P_current += (dt / 6.0) * (k1 + 2*k2 + 2*k3 + k4)
                P_loop[i] = P_current
        else:
            on_upper_branch = (P_current > 0)
            for i in range(1, len(V_applied_path)):
                V_target = V_applied_path[i]
                V_previous = V_applied_path[i-1]
                sweeping_up = (V_target > V_previous)
                initial_guess_P = P_current
                if sweeping_up and not on_upper_branch and V_target >= V_c_positive:
                    initial_guess_P = 0.5; on_upper_branch = True
                elif not sweeping_up and on_upper_branch and V_target <= V_c_negative:
                    initial_guess_P = -0.5; on_upper_branch = False
                P_solution = fsolve(equation_to_solve, x0=np.array([initial_guess_P]), args=(float(V_target),))
                P_current = P_solution[0]
                P_loop[i] = P_current
                
        return P_loop

    def add_parasitic_effects(self, V_applied_path, P_ideal_loop, t=None):
        """
        Add realistic non-ideal effects to hysteresis loop.
        
        Includes:
        - Linear dielectric contribution (loop tilt)
        - Leakage current (loop rounding)
        
        Args:
            V_applied_path (ndarray): Applied voltage waveform
            P_ideal_loop (ndarray): Ideal polarization response
            t (ndarray, optional): Time array corresponding to the waveform
            
        Returns:
            tuple: (total_polarization, parasitic_only_polarization)
        """
        EPSILON_0 = 8.854e-12 # F/m, vacuum permittivity 
        epsilon_r = self.material_dict['ferroelectric']['epsilon_r']
        film_thickness = self.material_dict['ferroelectric']['film_thickness']
        area = self.material_dict['electrode']['area']
        R_leak = self.material_dict['ferroelectric']['leakage_resistance']

        # --- Part 1: Linear Dielectric Contribution (Causes Tilt) ---
        # P_dielectric = epsilon_0 * (epsilon_r - 1) * E = epsilon_0 * (epsilon_r - 1) * V / d
        P_dielectric = EPSILON_0 * (epsilon_r - 1) * V_applied_path / film_thickness
        
        # --- Part 2: Leakage Contribution (Causes Rounding/Fattening) ---
        if t is not None and len(t) > 1:
            delta_t = t[1] - t[0]
        else:
            frequency = 1e6
            num_points = len(V_applied_path)
            period = 1.0 / frequency
            delta_t = period / num_points
            
        leakage_integral_term = np.cumsum(V_applied_path) * delta_t
        P_leak_loop = (1 / (area * R_leak)) * leakage_integral_term

        # --- Part 3: Total Measured Polarization ---
        P_total_loop = P_ideal_loop + P_dielectric + P_leak_loop
        
        return P_total_loop, P_dielectric + P_ideal_loop
   
    def apply_waveform(self, v, t):
        """
        Apply voltage waveform and calculate complete material response.
        
        Combines ideal hysteresis with parasitic effects to generate
        realistic voltage response measured across series resistor.
        
        Args:
            v (ndarray): Voltage waveform array
            t (ndarray): Time points array
        """
        
        self.t = t
        
        import matplotlib.pyplot as plt
        
        p_ideal = self.run_landau_hysteresis_simulation(v)
        p_total, p_noise = self.add_parasitic_effects(v, p_ideal, t=t)
        
        self.output_voltage = (np.gradient(p_total, t))*50*self.material_dict['electrode']['area']
        self.output_voltage[0:10] = self.output_voltage[10]
        

    def get_voltage_response(self):
        """
        Get the calculated voltage response.
        
        Returns:
            tuple: (voltage_response, time_array)
        """
        return self.output_voltage, self.t #multiply current by 50 ohm to get voltage response,




