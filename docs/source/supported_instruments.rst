Supported Instruments
=====================

Universal Requirements
----------------------

* **NI-VISA**: Required for all standard VISA-based instruments.
* **NI-488.2**: Required for physical GPIB cards from National Instruments.

Verified Versions
-----------------

* **Python**: 3.8+
* **NI-VISA**: 2024+
* **OS**: Windows (Primary support)

Category Overview
-----------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Category
     - Description
   * - :ref:`Awg <awg>`
     - 6 supported models
   * - :ref:`Daq <daq>`
     - 1 supported model
   * - :ref:`Dc Callibrator <dc-callibrator>`
     - 1 supported model
   * - :ref:`Dmm <dmm>`
     - 3 supported models
   * - :ref:`Lockin <lockin>`
     - 2 supported models
   * - :ref:`Oscilloscope <oscilloscope>`
     - 6 supported models
   * - :ref:`Pulser <pulser>`
     - 1 supported model
   * - :ref:`Sourcemeter <sourcemeter>`
     - 1 supported model
   * - :ref:`Stepper Motor <stepper-motor>`
     - 1 supported model

.. _awg:

Awg
---

.. dropdown:: Click to view supported Awg models
   :color: primary
   :icon: device-desktop

   .. list-table::
      :header-rows: 1
      :widths: 30 25 20 25

      * - Model / Description
        - Driver Class
        - Protocol
        - Requirements
      * - Agilent 33220A Arbitrary Waveform Generator
        - :py:class:`~piec.drivers.awg.agilent_33220a.Agilent33220A`
        - SCPI
        - NI-VISA
      * - Agilent 33500 Series Arbitrary Waveform Generators
        - :py:class:`~piec.drivers.awg.agilent_33500.Agilent33500`
        - SCPI
        - NI-VISA
      * - Keysight 81150A Arbitrary Waveform Generator
        - :py:class:`~piec.drivers.awg.k_81150a.Keysight81150a`
        - SCPI
        - NI-VISA
      * - Rigol DG1000 Series Arbitrary Waveform Generators
        - :py:class:`~piec.drivers.awg.rigol_dg1000.RigolDG1000`
        - SCPI
        - NI-VISA
      * - Rigol DG4000 Series Arbitrary Waveform Generators
        - :py:class:`~piec.drivers.awg.rigol_dg4000.RigolDG4000`
        - SCPI
        - NI-VISA
      * - Siglent SDG2000X Series Arbitrary Waveform Generator
        - :py:class:`~piec.drivers.awg.sdg2000.SDG2000X`
        - SCPI
        - NI-VISA

.. _daq:

Daq
---

.. dropdown:: Click to view supported Daq models
   :color: primary
   :icon: device-desktop

   .. list-table::
      :header-rows: 1
      :widths: 30 25 20 25

      * - Model / Description
        - Driver Class
        - Protocol
        - Requirements
      * - MCC USB-231 DAQ device
        - :py:class:`~piec.drivers.daq.usb231.USB231`
        - Digilent VBS
        - Requires mcculw

.. _dc-callibrator:

Dc Callibrator
--------------

.. dropdown:: Click to view supported Dc Callibrator models
   :color: primary
   :icon: device-desktop

   .. list-table::
      :header-rows: 1
      :widths: 30 25 20 25

      * - Model / Description
        - Driver Class
        - Protocol
        - Requirements
      * - EDC Model 522 DC Calibrator. Supporting voltage and current sourcing
        - :py:class:`~piec.drivers.dc_callibrator.edc522.EDC522`
        - Custom Serial/Vendor
        - NI-VISA

.. _dmm:

Dmm
---

.. dropdown:: Click to view supported Dmm models
   :color: primary
   :icon: device-desktop

   .. list-table::
      :header-rows: 1
      :widths: 30 25 20 25

      * - Model / Description
        - Driver Class
        - Protocol
        - Requirements
      * - Agilent 34410A Digital Multimeter
        - :py:class:`~piec.drivers.dmm.agilent_34410a.Agilent34410A`
        - SCPI
        - NI-VISA
      * - Keithley 193A Digital Multimeter
        - :py:class:`~piec.drivers.dmm.keithley193a.Keithley193a`
        - Custom Serial/Vendor
        - NI-VISA
      * - Keithley 2000 Digital Multimeter
        - :py:class:`~piec.drivers.dmm.keithley_2000.Keithley2000`
        - SCPI
        - NI-VISA

.. _lockin:

Lockin
------

.. dropdown:: Click to view supported Lockin models
   :color: primary
   :icon: device-desktop

   .. list-table::
      :header-rows: 1
      :widths: 30 25 20 25

      * - Model / Description
        - Driver Class
        - Protocol
        - Requirements
      * - SRS 830 Lock-In Amplifier
        - :py:class:`~piec.drivers.lockin.srs830.SRS830`
        - SCPI
        - NI-VISA
      * - Stanford Research Systems SR830 Lock-In Amplifier
        - :py:class:`~piec.drivers.lockin.srs830_old.SRS830`
        - SCPI
        - NI-VISA

.. _oscilloscope:

Oscilloscope
------------

.. dropdown:: Click to view supported Oscilloscope models
   :color: primary
   :icon: device-desktop

   .. list-table::
      :header-rows: 1
      :widths: 30 25 20 25

      * - Model / Description
        - Driver Class
        - Protocol
        - Requirements
      * - Agilent/Keysight InfiniVision 5000 X-Series Oscilloscope
        - :py:class:`~piec.drivers.oscilloscope.agilent_dsox5000.AgilentDSOX5000`
        - SCPI
        - NI-VISA
      * - Keysight DSOX3024A Oscilloscope
        - :py:class:`~piec.drivers.oscilloscope.k_dsox3024a.KeysightDSOX3024a`
        - SCPI
        - NI-VISA
      * - Rigol DS1000Z Series Oscilloscope
        - :py:class:`~piec.drivers.oscilloscope.rigol_ds1000z.RigolDS1000Z`
        - SCPI
        - NI-VISA
      * - Tektronix TDS 2000 Series Oscilloscope
        - :py:class:`~piec.drivers.oscilloscope.tektronix_tds2000.TektronixTDS2000`
        - SCPI
        - NI-VISA
      * - Tektronix TDS 6604 Oscilloscope
        - :py:class:`~piec.drivers.oscilloscope.tektronix_tds6604.TDS6604`
        - SCPI
        - NI-VISA
      * - Teledyne LeCroy SDA 6020 Oscilloscope
        - :py:class:`~piec.drivers.oscilloscope.lecroy_sda6020.LeCroySDA6020`
        - SCPI
        - NI-VISA

.. _pulser:

Pulser
------

.. dropdown:: Click to view supported Pulser models
   :color: primary
   :icon: device-desktop

   .. list-table::
      :header-rows: 1
      :widths: 30 25 20 25

      * - Model / Description
        - Driver Class
        - Protocol
        - Requirements
      * - Berkeley Nucleonics 765 Pulse Generator
        - :py:class:`~piec.drivers.pulser.bnc765.BNC765`
        - SCPI
        - NI-VISA

.. _sourcemeter:

Sourcemeter
-----------

.. dropdown:: Click to view supported Sourcemeter models
   :color: primary
   :icon: device-desktop

   .. list-table::
      :header-rows: 1
      :widths: 30 25 20 25

      * - Model / Description
        - Driver Class
        - Protocol
        - Requirements
      * - Keithley 2400 Sourcemeter
        - :py:class:`~piec.drivers.sourcemeter.keithley2400.Keithley2400`
        - SCPI
        - NI-VISA

.. _stepper-motor:

Stepper Motor
-------------

.. dropdown:: Click to view supported Stepper Motor models
   :color: primary
   :icon: device-desktop

   .. list-table::
      :header-rows: 1
      :widths: 30 25 20 25

      * - Model / Description
        - Driver Class
        - Protocol
        - Requirements
      * - Arduino Stepper. Requires motor_control_serial_piec.ino from the motor_control_serial_piec directory
        - :py:class:`~piec.drivers.stepper_motor.arduino_stepper.Geos_Stepper`
        - Custom Serial/Vendor
        - NI-VISA
