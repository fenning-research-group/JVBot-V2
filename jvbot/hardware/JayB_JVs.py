import os
import time
import re
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from frghardware.keithleyjv import control3

class JayBJVs:
    """Execution:
    >>> conda activate jvbot2
    >>> ipython
    >>> from jvbot.hardware.JayB_JVs import JayBJVs
    >>> jb = JayBJVs(BASE_DIR = r'C:\JV Data\JayB')
    >>> jb.run_single_scan("[0605]_[0604]_Set6_Pbcl24%_S2", vsteps = 100, pixel = "P4")
    Swap out the pixel keyword argument for any other pixels you scan (P1, P2, P3, etc.).
    """
    def __init__(
            self,
            BASE_DIR: str,
            folder_name: str = None,
        ):
        if folder_name is None:
            folder_name = datetime.now().strftime('%y%m%d')
        if BASE_DIR is None:
            raise Exception("The `BASE_DIR` should be given of the form r'C:\JV Data\JayB' replacing your user name.")
        WORKING_DIR = os.path.join(BASE_DIR, folder_name)
        if not os.path.exists(WORKING_DIR):
            os.makedirs(WORKING_DIR)
        os.chdir(WORKING_DIR)
        self.c = control3.Control(address = 'GPIB0::22::INSTR')
        self._setup_keithley()
    
    def _setup_keithley(self):
        """Configure Keithley settings with 2x accelerated scan speed parameters."""
        self.c.keithley.current_nplc = 0.05       # Low NPLC for high-speed tracking
        self.c.keithley.compliance_current = 0.1  # Safety threshold (100mA)
        self.c.keithley.write(":SYST:RSEN OFF")   # Force 2-wire mode
        
        # 2x Speed Up: Internal hardware delay optimized to 20ms
        self.c.keithley.source_delay = 0.02      
        self.c.area = 0.07  
        
        # 2x Speed Up: Reduced software pause to 20ms
        self.c.delay = 0.02                       
    def restore_keithley_defaults(self):
        """Restore default settings for other lab users (Cleanup)."""
        print("\n[System] Restoring Keithley default settings for the next user...")
        self.c.keithley.current_nplc = 1.0        # Restore to standard NPLC
        self.c.keithley.compliance_current = 1.05 # Restore to default max compliance
        self.c.keithley.write(":SYST:RSEN ON")    # Restore to standard 4-wire mode
        self.c.keithley.write(":OUTPUT OFF")      # Ensure output is disabled

    def get_unique_filename(self, base_name):
        """Automatically increments the scan number (e.g., _s1 -> _s2)."""
        clean_name = re.sub(r'_s\d+$', '', base_name)
        suffix = 1
        while True:
            name = f"{clean_name}_s{suffix}"
            if not (os.path.exists(f"{name}_rev_light.csv") or os.path.exists(f"{name}_fwd_light.csv")):
                return name
            suffix += 1
    def analyze_and_save(self, data_list, sample_name, direction):
        """Analyze PV parameters and display a consolidated text preview."""
        cols = ['number', 'Voltage (V)', 'Current Density (mA/cm2)', 'Current (A)', 'Measured Voltage (V)', 'Power Density (mW/cm2)']
        df = pd.DataFrame(data_list, columns=cols)
        
        V, J, I = df['Voltage (V)'].values, df['Current Density (mA/cm2)'].values, df['Current (A)'].values
        
        # Sign Correction
        v_sort_idx = np.argsort(V)
        if np.interp(0, V[v_sort_idx], J[v_sort_idx]) < 0:
            df['Current Density (mA/cm2)'] *= -1
            df['Current (A)'] *= -1
            df['Power Density (mW/cm2)'] = df['Voltage (V)'] * df['Current Density (mA/cm2)']
            J, I = df['Current Density (mA/cm2)'].values, df['Current (A)'].values

        # 1. Parameter Calculation (Voc, Jsc)
        js, vs = J[np.argsort(J)], V[np.argsort(J)]
        Voc = np.interp(0, js, vs)
        Jsc = np.abs(np.interp(0, V[np.argsort(V)], J[np.argsort(V)]))
        
        # 2. PCE / Fill Factor
        p_quad = df[(df['Voltage (V)'] >= 0) & (df['Voltage (V)'] <= Voc + 0.01)]
        if not p_quad.empty:
            pmax_idx = p_quad['Power Density (mW/cm2)'].idxmax()
            pmax = df.loc[pmax_idx, 'Power Density (mW/cm2)']
            ff = (pmax / (Voc * Jsc)) * 100
        else:
            pmax, ff = 0, 0

        # 3. Resistance Analysis (UNIST Style)
        try:
            idx_rs = (V > Voc - 0.02) & (V < Voc + 0.1)
            if sum(idx_rs) > 3:
                slope_rs, _ = np.polyfit(V[idx_rs], I[idx_rs], 1)
                rs_ohm = abs(1 / slope_rs)
            else:
                slope_rs, _ = np.polyfit(V[np.argsort(V)][-10:], I[np.argsort(V)][-10:], 1)
                rs_ohm = abs(1 / slope_rs)

            idx_rsh = (V > -0.05) & (V < 0.05)
            if sum(idx_rsh) > 3:
                slope_rsh, _ = np.polyfit(V[idx_rsh], I[idx_rsh], 1)
                rsh_ohm = abs(1 / slope_rsh)
            else:
                rsh_ohm = 1e7
        except:
            rs_ohm, rsh_ohm = 0, 0

        # Summary Text Output Preview
        print(f"\n=======================================")
        print(f" 🚀 {direction.upper()} SCAN METRICS SUMMARY ({sample_name})")
        print(f"=======================================")
        print(f"  Jsc  : {Jsc:.3f} mA/cm2")
        print(f"  Voc  : {Voc:.4f} V")
        print(f"  FF   : {ff:.2f} %")
        print(f"  PCE  : {pmax:.2f} %")
        print(f"  Rs   : {rs_ohm:.2f} ohm")
        print(f"  Rsh  : {rsh_ohm:.1f} ohm")
        print(f"=======================================")

        # Plotting
        plt.clf()
        plt.plot(V, J, color='blue' if direction=='rev' else 'red', label=direction.upper())
        plt.axhline(0, color='black', lw=0.5); plt.axvline(0, color='black', lw=0.5)
        plt.xlim(-0.2, 1.4); plt.ylim(-2, 30); plt.grid(True); plt.legend()
        plt.xlabel('Voltage (V)'); plt.ylabel('Current Density (mA/cm2)')
        plt.savefig(f"{sample_name}_{direction}.png", dpi=150)

        # File saving
        fname = f"{sample_name}_{direction}_light.csv"
        df[cols].to_csv(fname, index=False)
        with open(fname, 'a') as f:
            f.write(f"\nJsc,{Jsc:.3f}\nVoc,{Voc:.4f}\nFF,{ff:.2f}\nPCE,{pmax:.2f}\n")
            f.write(f"Rs,{rs_ohm:.2f}\nRsh,{rsh_ohm:.1f}\n")
        
        return pmax

    def run_single_scan(self, base_prefix, vmax=1.3, vmin=-0.2, vsteps=100, pixel="P1"):
        """Execute accelerated Reverse-only JV scan exactly once for the specified pixel."""
        self.setup_keithley() 
        
        # Combine prefix and pixel to create the full target name (e.g., [260417]_[260416]_PIN_Set1_S1_P1)
        full_target_name = f"{base_prefix}_{pixel}"
        unique = self.get_unique_filename(full_target_name)
        
        print(f"\n[Storage]: {self.WORKING_DIR}")
        print(f"[Measuring]: {unique} (Single Reverse Scan)")
        
        try:
            self.c.keithley.write(":OUTPUT ON")
            
            for d, v_arr in [("rev", np.linspace(vmax, vmin, vsteps))]:
                data = []
                for i, v_set in enumerate(v_arr):
                    self.c.keithley.write(f":SOURCE:VOLT {v_set}") 
                    time.sleep(self.c.delay)
                    
                    self.c.keithley.write(":READ?")
                    r = self.c.keithley.read().split(',')
                    curr_a = float(r[1])
                    j_den = (curr_a * 1000) / self.c.area
                    data.append([i, v_set, j_den, curr_a, float(r[0]), v_set * j_den])
                    print(f" {d.upper()} {i:3d}/{vsteps} | V:{v_set:5.2f} | J:{j_den:6.2f}", end='\r')
                    
                self.analyze_and_save(data, unique, d)
                
            self.c.keithley.write(":OUTPUT OFF")
            
        finally:
            self.restore_keithley_defaults()
            print(f"\n[Finished] Measurement and device reset completed.")
