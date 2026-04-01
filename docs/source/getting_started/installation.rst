Installation
============

Installing PIEC
---------------

Install PIEC using pip:

.. code-block:: console

   pip install piec

Driver Dependencies
-------------------

Depending on your instruments and how you connect to them, you may need additional drivers
installed on your system. PIEC itself will install fine without them, but communication with
specific hardware will fail if the required driver is missing.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Dependency
     - When you need it
   * - `NI 488.2 (GPIB) <https://www.ni.com/en/support/downloads/drivers/download.ni-488-2.html#544048>`_
     - Communicating with any instrument over a GPIB interface
   * - `MCC Universal Library (UL) <http://www.mccdaq.com/swdownload>`_
     - Using Digilent / MCC DAQ devices (e.g., ``MCCDig``)

