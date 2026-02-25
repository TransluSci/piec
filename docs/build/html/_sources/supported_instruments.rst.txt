Supported Instruments
=====================

The table below lists all instruments with drivers currently included in piec. Each row gives
the driver class name, instrument category, connection type, and a link to the API
documentation for that driver.

.. list-table::
   :header-rows: 1
   :widths: 30 20 15 35

   * - Driver class
     - Category
     - Connection
     - Notes
   * - ``Keysight81150a``
     - AWG
     - GPIB
     - Dual-channel pulse/function generator
   * - ``KeysightDSOX3024A``
     - Oscilloscope
     - GPIB / USB
     - 4-channel mixed-signal oscilloscope
   * - ``SR830``
     - Lock-in amplifier
     - GPIB
     - Stanford Research Systems lock-in
   * - ``EDC522``
     - DC calibrator
     - GPIB
     - Voltage/current source used for field control
   * - ``Keithley193A``
     - DMM
     - GPIB
     - Digital multimeter for DC resistance / voltage
   * - ``Arduino``
     - Stepper motor controller
     - Serial (USB)
     - Used for rotating sample stages
   * - ``MCCDig``
     - DAQ
     - USB
     - Digilent / MCC data acquisition device


Driver categories
-----------------

Drivers are grouped by instrument category in ``piec.drivers``. Each category defines a
common interface (Level 3 in the driver hierarchy) that specific model drivers implement.
See :doc:`user_guide/the_driver` for a description of the hierarchy.

**Arbitrary waveform generators (AWG)**
   Output arbitrary voltage waveforms. Used by hysteresis and PUND measurements.

**Oscilloscopes**
   Capture time-domain voltage traces. Used as the response measurement instrument in
   waveform-based experiments.

**Lock-in amplifiers**
   Narrow-band AC measurement. Used in AMR and other low-signal transport measurements.

**DMMs**
   DC voltage and resistance measurement.

**DC calibrators / source meters**
   Precision voltage/current sources used for field control or biasing.

**Stepper motor controllers**
   Control sample rotation stages for angle-dependent measurements (e.g., AMR).

**DAQ devices**
   General-purpose data acquisition.

For the auto-generated API documentation for all drivers, see :doc:`api_reference`.