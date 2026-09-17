import matplotlib.pyplot as plt


def plot_bode(data, title=None, path=None, show_plots=True, save_plots=False):
    """
    Plots a Bode plot (magnitude in dB and phase in degrees vs. log-frequency)
    from frequency response data, e.g. as produced by
    piec.measurement.frequency_response.FrequencyResponse.

    :param data: DataFrame with 'Frequency (Hz)', 'Magnitude (dB)', and 'Phase (deg)' columns
    :param title: Optional plot title
    :param path: Base path used to derive the saved filename (mirrors the
        piec convention of deriving '<path>_bode.png' from the data's CSV path)
    :param show_plots: If True, displays the plot interactively
    :param save_plots: If True, saves the plot to '<path>_bode.png'

    returns:
        (Figure, (Axes, Axes)): The created figure and (magnitude, phase) axes.
    """
    fig, (ax_mag, ax_phase) = plt.subplots(2, 1, sharex=True, tight_layout=True)

    freq = data['Frequency (Hz)']

    ax_mag.semilogx(freq, data['Magnitude (dB)'], color='k')
    ax_mag.set_ylabel('Magnitude (dB)')
    ax_mag.grid(True, which='both', alpha=0.3)
    if title:
        ax_mag.set_title(title)

    ax_phase.semilogx(freq, data['Phase (deg)'], color='r')
    ax_phase.set_xlabel('Frequency (Hz)')
    ax_phase.set_ylabel('Phase (deg)')
    ax_phase.grid(True, which='both', alpha=0.3)

    if save_plots:
        if path is None:
            raise ValueError("path must be provided when save_plots=True")
        fig.savefig(path[:-4] + '_bode.png' if path.endswith('.csv') else path + '_bode.png')
    if show_plots:
        plt.show()

    return fig, (ax_mag, ax_phase)
