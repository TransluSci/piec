import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from scipy.integrate import cumulative_trapezoid
from piec.analysis.utilities import *

def process_raw_3pp(path:str, show_plots=False, save_plots=False, auto_timeshift=True):
    """Analyze a PUND capture with the applied waveform starting at t=0.

    auto_timeshift is retained for compatibility; scope setup handles alignment.
    """
    metadata, raw_df = standard_csv_to_metadata_and_data(path)
    processed_df = raw_df

    processed_df['time (s)'] = processed_df['time (s)'].values - processed_df['time (s)'].values[0] # make sure time starts at zero

    # get relevant values from metadata and math
    reset_amp = metadata['reset_amp'].values[0]
    reset_width = metadata['reset_width'].values[0]
    reset_delay = metadata['reset_delay'].values[0]
    p_u_amp = metadata['p_u_amp'].values[0]
    p_u_width = metadata['p_u_width'].values[0]
    p_u_delay = metadata['p_u_delay'].values[0]
    timestep = processed_df['time (s)'].values[-1]/len(processed_df)
    area = metadata['area'].values[0]
    length = metadata['length'].values[0]
    polarity = np.sign(p_u_amp) #palarity of the waveform

    # add on time-dependent processed arrays
    processed_df['current (A)'] = processed_df['voltage (V)']/50 # 50Ohm conversion, area correction, C/m^2 to uC/cm^2
    processed_df['polarization (uC/cm^2)'] = cumulative_trapezoid(processed_df['current (A)'], processed_df['time (s)'], initial=0)/area*100

    # time to choppy chop the pund based on the extracted pulse widths and delays
    n_ph = np.searchsorted(processed_df['time (s)'].values, reset_width+reset_delay)
    n_phr = np.searchsorted(processed_df['time (s)'].values, reset_width+reset_delay+p_u_width)
    n_ps = np.searchsorted(processed_df['time (s)'].values, reset_width+reset_delay+p_u_width+p_u_delay)
    n_psr = np.searchsorted(processed_df['time (s)'].values, reset_width+reset_delay+2*p_u_width+p_u_delay)
    try:
        n_end = np.searchsorted(processed_df['time (s)'].values, reset_width+reset_delay+2*p_u_width+2*p_u_delay)
    except:
        n_end = len(processed_df)

    ph = processed_df['polarization (uC/cm^2)'].values[n_ph:n_phr]
    phr = processed_df['polarization (uC/cm^2)'].values[n_phr:n_ps]
    ps = processed_df['polarization (uC/cm^2)'].values[n_ps:n_psr]
    psr = processed_df['polarization (uC/cm^2)'].values[n_psr:n_end]

    # homogenize lengths for array math
    ph = ph[:min(len(ph), len(ps))]
    ps = ps[:min(len(ph), len(ps))]
    phr = phr[:min(len(phr), len(psr))]
    psr = psr[:min(len(phr), len(psr))]

    dp = np.concatenate([ph, phr]) - np.concatenate([ps, psr]) # time dependent FE polarization is diff between p and u pulse polarizations
    array_dict = {'P^':ph, 'P*':ps, 'P^r':phr, 'P*r':psr, 'dP':dp} # this naming convention mimics the one set by Radiant

    for key in array_dict.keys():
        array_dict[key] = array_dict[key] - array_dict[key][0] # zero polarizations without mutating a pandas view
        repeat_values = np.zeros(len(processed_df)-len(array_dict[key]))+array_dict[key][-1]
        array_dict[key] = np.concatenate([array_dict[key], repeat_values]) # add repeat values to the end of arrays so they can be added to the dataframe
        processed_df[key+' (uC/cm^2)'] = array_dict[key] # add analysys arrays to dataframe

    # Scope setup aligns the applied waveform with the start of the capture.
    times = [0, reset_width, reset_delay, p_u_width, p_u_delay, p_u_width, p_u_delay,]
    sum_times = [sum(times[:i+1]) for i, t in enumerate(times)]
    # calculate full amplitude of pulse profile and fractional amps of pulses

    # specify sparse t and v coordinates which define PUND pulse train
    sparse_t = np.array([sum_times[0], sum_times[1], sum_times[1], sum_times[2], sum_times[2], sum_times[3], sum_times[3],
                            sum_times[4], sum_times[4], sum_times[5], sum_times[5], sum_times[6],])
    sparse_v = np.array([-reset_amp, -reset_amp, 0, 0, p_u_amp, p_u_amp, 0, 0,
                            p_u_amp, p_u_amp, 0, 0,]) * polarity
    
    n_points = int(length/timestep) # n points to use is max

    # densify the array, rise/fall times of pulses will be equal to the awg resolution
    v_applied = interpolate_sparse_to_dense(sparse_t, sparse_v, total_points=n_points)

    if len(v_applied)<len(processed_df):
        v_applied = np.concatenate([v_applied, np.zeros(len(processed_df) - len(v_applied))]) # make sure arrays are the same length

    processed_df['applied voltage (V)'] = v_applied[:len(processed_df)]

    # optional plotting
    if show_plots or save_plots:
        #dP vs time plot
        fig, ax = plt.subplots(tight_layout=True)
        ax.plot(processed_df['time (s)'], processed_df['dP (uC/cm^2)'], color='k')
        ax.set_xlabel('time (s)')
        ax.set_ylabel('dP (uC/cm^2)')
        if save_plots:
            fig.savefig(path[:-4]+'_dPvst.png')
        if show_plots:
            plt.show()
        plt.close()

        #Current response and applied voltage trace plot
        fig, ax = plt.subplots(tight_layout=True)
        ax.plot(processed_df['time (s)'], processed_df['current (A)'], color='k')
        ax.set_xlabel('time (s)')
        ax.set_ylabel('current (A)')
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
