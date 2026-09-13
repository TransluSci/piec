"""Execute the four Python-only virtual notebooks in isolated temporary folders.

Run with the environment used to install piec. No kernel server, hardware
discovery, source-file mutation or saved-output trust is required.
"""
from pathlib import Path
import json
import os
import shutil
import tempfile

import piec.measurement.gui_utils
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from IPython.display import display


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = (
    'Measurements/AMR/AMR_testing.ipynb',
    'Measurements/MOKE/MOKE_testing.ipynb',
    'Measurements/Ferroelectric Testing/example_hysteresis.ipynb',
    'Measurements/Ferroelectric Testing/FE_testing.ipynb',
)


def main():
    for relative in NOTEBOOKS:
        notebook = json.loads((ROOT / relative).read_text(encoding='utf-8'))
        print(f'Executing {relative}', flush=True)
        with tempfile.TemporaryDirectory(prefix='piec-notebook-') as directory:
            shutil.copyfile(ROOT / 'Measurements/MOKE/example_calibration.csv', Path(directory) / 'example_calibration.csv')
            previous = Path.cwd()
            try:
                os.chdir(directory)
                namespace = {'__name__': '__main__', 'display': display}
                count = 0
                for index, cell in enumerate(notebook['cells']):
                    if cell['cell_type'] != 'code':
                        continue
                    exec(compile(''.join(cell['source']), f'{relative}:cell-{index}', 'exec'), namespace)
                    count += 1
                print(f'PASS: {count} code cells', flush=True)
            finally:
                plt.close('all')
                os.chdir(previous)


if __name__ == '__main__':
    main()
