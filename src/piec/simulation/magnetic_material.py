import numpy as np

class MagneticSample:
    """
    Simulation model for a magnetic sample, used for generating synthetic magneto-transport data.
    """
    def __init__(self, r_base=100.0, amr_ratio=0.02, phi_offset=0.0):
        """
        Initialize the magnetic sample.
        
        Args:
            r_base (float): Base resistance in Ohms.
            amr_ratio (float): (R_par - R_perp) / R_perp.
            phi_offset (float): Angle offset in degrees.
        """
        self.r_base = r_base
        self.amr_ratio = amr_ratio
        self.phi_offset = phi_offset
        self.current_angle = 0.0 # degrees
        self.current_field = 0.0 # Oe
        self.name = "virtual_magnetic_sample"

    def get_resistance(self, angle=None, field=None):
        """
        Calculate resistance based on the current angle and field.
        Simplified AMR model: R = R_perp + (R_par - R_perp) * cos^2(theta - phi)
        
        Args:
            angle (float, optional): Angle in degrees. Uses current_angle if None.
            field (float, optional): Field in Oe. Uses current_field if None.
            
        Returns:
            float: Simulated resistance in Ohms.
        """
        theta = np.radians(angle if angle is not None else self.current_angle)
        phi = np.radians(self.phi_offset)
        
        # Simple AMR cos^2 dependence
        r_perp = self.r_base
        r_par = self.r_base * (1 + self.amr_ratio)
        
        resistance = r_perp + (r_par - r_perp) * (np.cos(theta - phi)**2)
        
        # Add some noise
        noise = np.random.normal(0, self.r_base * 0.0001)
        return resistance + noise

    def get_voltage_response(self, current_v=1.0):
        """
        Simulate a lock-in voltage response.
        V = V_drive * (R_sample / (R_load + R_sample)) or similar
        For simplicity, let's assume V proportional to R
        """
        r = self.get_resistance()
        # Scale to something reasonable for a lock-in (e.g. 100 uV range)
        return r * 1e-6 
