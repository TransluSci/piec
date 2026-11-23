"""Standard MOKE hysteresis-loop analysis and publication-style plotting."""
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd

from .utilities import standard_csv_to_metadata_and_data


def _extract_branches(field, signal):
    """Split one closed MOKE loop into increasing and decreasing branches in acquisition order.

    Rolling the circular loop to start at ``nanargmin(field)`` unwraps branches
    that wrap across the start/end of the array when acquisition begins near
    zero field.
    """
    n = len(field)
    idx_min = int(np.nanargmin(field))
    idx_max = int(np.nanargmax(field))
    shifted_h = np.roll(field, -idx_min)
    shifted_s = np.roll(signal, -idx_min)
    peak_pos = (idx_max - idx_min) % n
    inc_h = shifted_h[:peak_pos + 1]
    inc_s = shifted_s[:peak_pos + 1]
    dec_h = np.concatenate([shifted_h[peak_pos:], shifted_h[:1]])
    dec_s = np.concatenate([shifted_s[peak_pos:], shifted_s[:1]])
    return (inc_h, inc_s), (dec_h, dec_s)


def _find_single_crossing(x, y, target):
    """Find the unique x where y crosses target in acquisition order without bridging NaN gaps."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    diff = y - float(target)
    crossings = []
    gap_crossing = False
    last_finite = None

    for i in range(len(x)):
        if not finite[i]:
            continue
        if last_finite is not None:
            if last_finite == i - 1:
                d0, d1 = diff[i - 1], diff[i]
                if d0 == 0.0:
                    crossings.append(float(x[i - 1]))
                elif d0 * d1 < 0.0:
                    t = -d0 / (d1 - d0)
                    crossings.append(float(x[i - 1] + t * (x[i] - x[i - 1])))
            else:
                if diff[last_finite] == 0.0 or diff[last_finite] * diff[i] <= 0.0:
                    gap_crossing = True
        last_finite = i

    if last_finite is not None and diff[last_finite] == 0.0:
        crossings.append(float(x[last_finite]))

    if gap_crossing:
        return None, 'Midpoint crossing spans missing data (NaN gap)'
    if not crossings:
        return None, 'Branch does not cross optical midpoint'
    if len(crossings) > 1:
        return None, f'Ambiguous midpoint crossings ({len(crossings)} found)'
    return crossings[0], None


def _interpolate_y_at_x(x, y, target_x=0.0):
    """Interpolate y at target_x along a branch without extrapolation or bridging NaN gaps."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    values = []
    gap_crossing = False
    last_finite = None

    for i in range(len(x)):
        if not finite[i]:
            continue
        if last_finite is not None:
            if last_finite == i - 1:
                x0, x1 = x[i - 1], x[i]
                if x0 == target_x:
                    values.append(float(y[i - 1]))
                elif (x0 - target_x) * (x1 - target_x) < 0.0:
                    t = (target_x - x0) / (x1 - x0)
                    values.append(float(y[i - 1] + t * (y[i] - y[i - 1])))
            else:
                if (x[last_finite] - target_x) * (x[i] - target_x) <= 0.0:
                    gap_crossing = True
        last_finite = i

    if last_finite is not None and x[last_finite] == target_x:
        values.append(float(y[last_finite]))

    if gap_crossing:
        return None, f'{target_x:g} Oe crossing spans missing data (NaN gap)'
    if not values:
        return None, f'Branch does not bracket {target_x:g} Oe'
    if len(values) > 1:
        return None, f'Ambiguous {target_x:g} Oe crossings ({len(values)} found)'
    return values[0], None


def analyze_moke_loop(
    field,
    signal,
    *,
    requested_field=None,
    field_source=None,
    plateau_fraction=0.15,
    min_plateau_points=3,
    max_plateau_slope_ratio=0.50,
    min_snr=3.0,
):
    """Analyze one completed MOKE hysteresis loop and return metrics with availability reasons.

    Saturation plateaus use a documented heuristic: the outer
    ``plateau_fraction`` of the acquired field span at both positive and
    negative extremes (default 15% of ``H_max - H_min`` at each end, requiring
    at least ``min_plateau_points`` samples and a plateau slope <=
    ``max_plateau_slope_ratio`` of the loop's overall secant slope).

    Note: LabVIEW's ``hyst params.vi`` evaluates remanence at the loop center;
    PIEC evaluates squareness ``Mr/Ms`` at zero applied field (``H = 0 Oe``)
    by default.
    """
    h = np.asarray(field, dtype=float).ravel()
    s = np.asarray(signal, dtype=float).ravel()
    if len(h) != len(s):
        raise ValueError('field and signal must have the same length')

    if field_source is None:
        if requested_field is not None:
            req = np.asarray(requested_field, dtype=float).ravel()
            if len(req) == len(h) and np.allclose(h, req, rtol=1e-9, atol=1e-9, equal_nan=True):
                field_source = 'commanded'
            else:
                field_source = 'measured'
        else:
            field_source = 'measured'
    elif field_source == 'estimated':
        field_source = 'commanded'

    valid = np.isfinite(h) & np.isfinite(s)
    h_valid, s_valid = h[valid], s[valid]

    reasons = {}
    result = {
        'field_source': field_source,
        'uses_commanded_field': field_source != 'measured',
        'h_increasing_oe': None,
        'h_decreasing_oe': None,
        'hc_oe': None,
        'loop_center_oe': None,
        'amplitude_v': None,
        'midpoint_v': None,
        's_pos_sat_v': None,
        's_neg_sat_v': None,
        's_inc_zero_v': None,
        's_dec_zero_v': None,
        'squareness': None,
        'reasons': reasons,
    }

    def _fail_all(reason):
        for key in ('h_increasing_oe', 'h_decreasing_oe', 'hc_oe', 'loop_center_oe', 'amplitude_v', 'squareness'):
            reasons[key] = reason
        return result

    if len(h_valid) < 6:
        return _fail_all('Insufficient valid data points')

    h_min, h_max = float(np.min(h_valid)), float(np.max(h_valid))
    h_span = h_max - h_min
    if h_span <= 0.0:
        return _fail_all('Zero magnetic field span')

    # Verify the input represents a closed cycle rather than a partial/one-way sweep
    nonzero_steps = np.abs(np.diff(h_valid))
    nonzero_steps = nonzero_steps[nonzero_steps > 0.0]
    median_step = float(np.median(nonzero_steps)) if len(nonzero_steps) > 0 else 0.0
    closure_tol = max(5.0 * median_step, 0.15 * h_span)
    if abs(float(h_valid[-1]) - float(h_valid[0])) > closure_tol:
        return _fail_all('Incomplete loop (sweep does not close)')

    (inc_h, inc_s), (dec_h, dec_s) = _extract_branches(h, s)
    n_inc = int(np.sum(np.isfinite(inc_h) & np.isfinite(inc_s)))
    n_dec = int(np.sum(np.isfinite(dec_h) & np.isfinite(dec_s)))
    if n_inc < 3 or n_dec < 3:
        return _fail_all('Incomplete increasing or decreasing branch')

    # Saturation plateau windows (outer plateau_fraction of total field span)
    pos_mask = valid & (h >= (h_max - plateau_fraction * h_span))
    neg_mask = valid & (h <= (h_min + plateau_fraction * h_span))
    saturation_reason = None
    if int(np.sum(pos_mask)) < min_plateau_points or int(np.sum(neg_mask)) < min_plateau_points:
        saturation_reason = 'Missing saturation plateau (too few points at field extremes)'
    else:
        s_pos = float(np.mean(s[pos_mask]))
        s_neg = float(np.mean(s[neg_mask]))
        amp = abs(s_pos - s_neg) / 2.0
        mid = 0.5 * (s_pos + s_neg)
        result['s_pos_sat_v'] = s_pos
        result['s_neg_sat_v'] = s_neg
        result['midpoint_v'] = mid

        noise_std = max(float(np.std(s[pos_mask])), float(np.std(s[neg_mask])), 0.0)
        if amp <= 0.0:
            saturation_reason = 'Insufficient signal (zero switching amplitude)'
        elif noise_std > 0.0 and amp < min_snr * noise_std:
            saturation_reason = 'Insufficient signal-to-noise ratio'
        else:
            secant_slope = abs(s_pos - s_neg) / h_span
            for mask in (pos_mask, neg_mask):
                h_win, s_win = h[mask], s[mask]
                if np.ptp(h_win) > 0.0:
                    slope = float(np.polyfit(h_win, s_win, 1)[0])
                    if abs(slope) / secant_slope > max_plateau_slope_ratio:
                        saturation_reason = 'Missing saturation plateau (signal not saturated at field extremes)'
                        break

    if saturation_reason is not None:
        return _fail_all(saturation_reason)

    result['amplitude_v'] = amp

    # Midpoint crossings, coercivity, and loop center
    h_inc, inc_reason = _find_single_crossing(inc_h, inc_s, mid)
    h_dec, dec_reason = _find_single_crossing(dec_h, dec_s, mid)
    result['h_increasing_oe'] = h_inc
    result['h_decreasing_oe'] = h_dec
    if inc_reason:
        reasons['h_increasing_oe'] = inc_reason
    if dec_reason:
        reasons['h_decreasing_oe'] = dec_reason

    if h_inc is not None and h_dec is not None:
        result['hc_oe'] = abs(h_inc - h_dec) / 2.0
        result['loop_center_oe'] = (h_inc + h_dec) / 2.0
    else:
        pair_reason = inc_reason or dec_reason
        reasons['hc_oe'] = pair_reason
        reasons['loop_center_oe'] = pair_reason

    # Squareness Mr/Ms at zero applied field (separate validity check)
    s_inc_0, zero_inc_reason = _interpolate_y_at_x(inc_h, inc_s, 0.0)
    s_dec_0, zero_dec_reason = _interpolate_y_at_x(dec_h, dec_s, 0.0)
    result['s_inc_zero_v'] = s_inc_0
    result['s_dec_zero_v'] = s_dec_0
    if zero_inc_reason or zero_dec_reason:
        reasons['squareness'] = zero_inc_reason or zero_dec_reason
    else:
        result['squareness'] = abs(s_inc_0 - s_dec_0) / (2.0 * amp)

    return result


def _select_loop_dataframe(df, cycle=None):
    """Extract one single loop from a single-cycle or multi-cycle MOKE DataFrame."""
    if df is None or df.empty or 'cycle' not in df.columns:
        return df
    unique_cycles = df['cycle'].dropna().unique()
    if len(unique_cycles) <= 1 and cycle is None:
        return df
    if cycle is not None:
        selected = df[df['cycle'] == cycle]
        if selected.empty:
            raise ValueError(f'Cycle {cycle} not found in DataFrame')
        return selected
    counts = df.groupby('cycle').size()
    expected_len = int(counts.max())
    pool = df[df['included'] == True] if 'included' in df.columns else df  # noqa: E712
    if pool.empty:
        pool = df
    pool_counts = pool.groupby('cycle').size()
    complete = [c for c, cnt in pool_counts.items() if cnt == expected_len]
    chosen = complete[-1] if complete else pool_counts.index[-1]
    return df[df['cycle'] == chosen]


def analyze_moke_dataframe(df, *, field_source=None, cycle=None, **kwargs):
    """Run :func:`analyze_moke_loop` on a single-loop or multi-cycle MOKE DataFrame."""
    loop_df = _select_loop_dataframe(df, cycle=cycle)
    if loop_df is None or loop_df.empty or 'field (Oe)' not in loop_df or 'signal (V)' not in loop_df:
        return analyze_moke_loop([], [], field_source=field_source, **kwargs)
    req = loop_df['requested field (Oe)'].to_numpy() if 'requested field (Oe)' in loop_df else None
    return analyze_moke_loop(
        loop_df['field (Oe)'].to_numpy(),
        loop_df['signal (V)'].to_numpy(),
        requested_field=req,
        field_source=field_source,
        **kwargs,
    )


def process_moke_csv(path, *, cycle=None, save_plot=False, show_plot=False, title=None, **kwargs):
    """Load a PIEC MOKE CSV (raw or ``_average.csv``), analyze one loop, and optionally plot."""
    metadata, df = standard_csv_to_metadata_and_data(path)
    df = df.dropna(axis=1, how='all')
    field_source = None
    if 'field_source' in metadata.columns and not metadata['field_source'].empty:
        field_source = str(metadata['field_source'].iloc[0])
    loop_df = _select_loop_dataframe(df, cycle=cycle)
    analysis = analyze_moke_dataframe(loop_df, field_source=field_source, **kwargs)
    if save_plot or show_plot:
        geometry = str(metadata['geometry'].iloc[0]).capitalize() if 'geometry' in metadata else 'MOKE'
        plot_title = title or f'{geometry} MOKE'
        plot_path = str(Path(path).with_suffix('')) + '_kerr.png' if save_plot else None
        plot_moke_loop(
            loop_df['field (Oe)'].to_numpy(),
            loop_df['signal (V)'].to_numpy(),
            analysis=analysis,
            title=plot_title,
            save_path=plot_path,
            show=show_plot,
        )
    return analysis


def plot_moke_loop(
    field,
    signal,
    *,
    analysis=None,
    title='MOKE',
    color='#1f4e78',
    ax=None,
    save_path=None,
    show=False,
):
    """Render a Nature-style Kerr signal (ΔV in mV) vs. Magnetic Field (Oe) plot."""
    h = np.asarray(field, dtype=float).ravel()
    s = np.asarray(signal, dtype=float).ravel()
    if analysis is not None and analysis.get('midpoint_v') is not None:
        v_mid = float(analysis['midpoint_v'])
    else:
        v_mid = 0.5 * (float(np.nanmax(s)) + float(np.nanmin(s)))
    h_closed = np.append(h, h[0]) if len(h) > 1 else h
    dv_mv = (np.append(s, s[0]) - v_mid) * 1e3 if len(s) > 1 else (s - v_mid) * 1e3

    created_fig = ax is None
    if created_fig:
        with plt.rc_context({
            'font.family': 'sans-serif',
            'font.sans-serif': ['Arial', 'DejaVu Sans'],
            'svg.fonttype': 'none',
            'axes.linewidth': 1.1,
        }):
            fig, ax = plt.subplots(figsize=(4.6, 4.0), dpi=300)
    else:
        fig = ax.figure

    ax.axhline(0, color='#d0d0d0', lw=0.9, ls='--', zorder=1)
    ax.axvline(0, color='#d0d0d0', lw=0.9, ls='--', zorder=1)
    ax.plot(h_closed, dv_mv, color=color, lw=1.8, zorder=3)
    ax.scatter(h, (s - v_mid) * 1e3, color=color, s=10, alpha=0.55, edgecolors='none', zorder=4)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#333333')
    ax.spines['bottom'].set_color('#333333')
    ax.tick_params(direction='in', length=4.5, width=1.0, colors='#333333', labelsize=10)
    ax.xaxis.set_major_locator(ticker.MaxNLocator(nbins=5))
    ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=5))
    ax.set_xlabel('Magnetic Field (Oe)', fontsize=11, labelpad=6)
    ax.set_ylabel('Kerr Signal, ΔV (mV)', fontsize=11, labelpad=6)
    ax.set_title(title, fontsize=12, fontweight='bold', pad=10)

    if created_fig:
        fig.tight_layout(pad=1.5)
        if save_path is not None:
            fig.savefig(save_path, dpi=300, bbox_inches='tight')
        if show:
            plt.show()
        else:
            plt.close(fig)
    elif save_path is not None:
        fig.savefig(save_path, dpi=300, bbox_inches='tight')

    return fig, ax
