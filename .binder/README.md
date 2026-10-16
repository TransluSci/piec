# Binder quick start

Binder installs the repository checkout using `.binder/requirements.txt` and
opens `Measurements/Quickstart/quick_start.ipynb`. Run one cell at a time, from top to bottom,
to try sine, square, and ramp waves and plot the virtual sample response. No VISA backend or physical instrument is needed.

The public badge targets `master`; new changes become available after merging.
To preview a pushed branch, replace `master` in the launch URL with its URL-encoded
branch name or commit SHA. Download notebook changes and CSVs before the session
ends. Binder is for virtual examples; bench instruments require local Jupyter.

Configuration follows [repo2docker's configuration files](https://repo2docker.readthedocs.io/en/stable/configuration/)
and [Binder's JupyterLab launch URLs](https://mybinder.readthedocs.io/en/latest/howto/user_interface.html).
