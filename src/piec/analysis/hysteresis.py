import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from scipy.integrate import cumulative_trapezoid
from piec.analysis.utilities import *

def process_raw_hyst(path:str, show_plots=False, save_plots=False, auto_timeshift=False):
    """
        Performs standard analysis on a 'raw' hyst data csv. Will add current (in A), and polarization (in uC/cm^2) columns, and will print/save plots if specified.
        
        :param path: system path to target csv data
        :param show_plots: print plots of PV loop and P/t + Vapp/t traces?
        :param save_plots: save plots in same directory as path?
        :param auto_timeshift: Retained for compatibility; scope setup aligns the waveform to t=0.
        """
    metadata, raw_df = standard_csv_to_metadata_and_data(path)
    processed_df = raw_df

    processed_df['time (s)'] = processed_df['time (s)'].values - processed_df['time (s)'].values[0] # make sure time starts at zero

    # get relevant values from metadata and math
    amp = metadata['amplitude'].values[0]
    frequency = metadata['frequency'].values[0]
    length = 1/frequency
    timestep = processed_df['time (s)'].values[-1]/len(processed_df)
    area = metadata['area'].values[0]
    N = metadata['n_cycles'].values[0]
    
    # add on time-dependent processed arrays
    processed_df['current (A)'] = processed_df['voltage (V)']/50 # 50Ohm conversion, area correction, C/m^2 to uC/cm^2
    processed_df['current (A)'] = processed_df['current (A)'].values - np.mean(processed_df['current (A)'].values[:20]) # offset correct
    processed_df['polarization (uC/cm^2)'] = cumulative_trapezoid(processed_df['current (A)']/area*100, processed_df['time (s)'], initial=0)

    # Scope setup aligns the applied waveform with the start of the capture.
    interp_v_array = np.array([0,1,0,-1,0]+([1,0,-1,0]*(N-1)))*amp
    v_applied = interpolate_sparse_to_dense(np.linspace(0,len(interp_v_array),len(interp_v_array)), interp_v_array, total_points=int(length//timestep))

    if len(v_applied)<len(processed_df):
        v_applied = np.concatenate([v_applied, np.zeros(len(processed_df) - len(v_applied))]) #make sure arrays are the same length

    processed_df['applied voltage (V)'] = v_applied[:len(processed_df)]

    # optional plotting
    if show_plots or save_plots:
        #PV Loop plot
        fig, ax = plt.subplots(tight_layout=True)
        ax.plot(processed_df['applied voltage (V)'], processed_df['polarization (uC/cm^2)'], color='k')
        ax.set_xlabel('applied voltage (V)')
        ax.set_ylabel('polarization (uC/cm^2)')
        if save_plots:
            fig.savefig(path[:-4]+'_PV.png')
        if show_plots:
            plt.show()
        plt.close()

        #IV Loop plot
        fig, ax = plt.subplots(tight_layout=True)
        ax.plot(processed_df['applied voltage (V)'], processed_df['current (A)'], color='k')
        ax.set_xlabel('applied voltage (V)')
        ax.set_ylabel('current (A)')
        if save_plots:
            fig.savefig(path[:-4]+'_IV.png')
        if show_plots:
            plt.show()
        plt.close()

        #Polarization vs applied current plot
        fig, ax = plt.subplots(tight_layout=True)
        ax.plot(processed_df['time (s)'], processed_df['polarization (uC/cm^2)'], color='k')
        ax.set_xlabel('time (s)')
        ax.set_ylabel('polarization (uC/cm^2)')
        ax1 = ax.twinx()
        ax1.plot(processed_df['time (s)'], processed_df['applied voltage (V)'], color='r')
        ax1.set_ylabel('applied voltage (V)')
        if save_plots:
            fig.savefig(path[:-4]+'_trace.png')
        if show_plots:
            plt.show()
        plt.close()
        
    metadata['processed'] = True
    # update csv with new processed data
    metadata_and_data_to_csv(metadata, processed_df, path)
