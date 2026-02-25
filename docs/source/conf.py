# Configuration file for the Sphinx documentation builder.
import os
import sys
sys.path.insert(0, os.path.abspath('../../src/'))


# -- Project information

project = 'piec'
copyright = '2025, Geo Fratian Alexander Qualls'
author = 'Geo Fratian'

release = '0.1'
version = '0.1.2'

# -- General configuration

extensions = [
    'sphinx.ext.duration',
    'sphinx.ext.doctest',
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.intersphinx',
    'sphinx.ext.napoleon',
    'sphinx.ext.todo',
]

# Show todo directives in the built docs
todo_include_todos = True

# Mock heavy/optional dependencies so autodoc can import piec without them installed
autodoc_mock_imports = [
    'pandas',
    'numpy',
    'scipy',
    'matplotlib',
    'pyvisa',
    'mcculw',
]

intersphinx_mapping = {
    'python': ('https://docs.python.org/3/', None),
    'sphinx': ('https://www.sphinx-doc.org/en/master/', None),
}
intersphinx_disabled_domains = ['std']

templates_path = ['_templates']

# Exclude old files that have been superseded by the new structure
exclude_patterns = [
    'getting_started.rst',
    'installation_guide.rst',
    'gui_guide.rst',
    'notebook_examples.rst',
    'measurements_overview.rst',
    'source_code_overview.rst',
    'authors.rst',
    'licence.rst',
    'measurements/drivers_overview.rst',
    'measurements/discrete_waveforms_general.rst',
]

# -- Napoleon settings (Google/NumPy style docstrings)

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True

# -- Autosummary

autosummary_generate = True

# -- HTML output

html_theme = 'sphinx_rtd_theme'

# -- EPUB output

epub_show_urls = 'footnote'