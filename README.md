# ALBATROSS
**A**utomated **L**i-ion **BA**ttery **T**esting **RO**bot **S**y**S**tem (**ALBATROSS**)

ALBATROSS is an automated platform that integrates electrolyte formulation, coin-cell assembly, cycling, and impedance evaluation. <br>
The system is designed to enable high-throughput electrolyte screening with the objective of acquiring large volumes of reliable experimental data. <br>
It is installed inside a glovebox equipped with temperature monitoring and control, thereby allowing systematic exploration of organic electrolytes that are sensitive to ambient environmental conditions. <br>

## Hardware Setup
a 6-axis robot arm (xArm6, UFactory) with electric gripper (xArm Gripper, UFactory)
a liquid handler (OT-2, Opentrons) with 300 ul and 1000 ul micropipette (P300, P1000)
an automated coin cell crimper (MSK-160E, MTI)
linear actuators with different stroke (12LF-12F-27 and 12LF-17F-40, Mightyzap)
stepper motors (C-42STM03, Misumi), and photo sensors (C-MSX674N, Misumi)
48 channels of potentiostat (CT-4008T-5V50mA, Neware)
2 channels of impedence measurement device (SP-150e, Biologics)

## OS Setup
ALBATROSS uses programmable logic controller (PLC; NX102-9000, Omron) for integration of devices. <br>
The PLC interprets the parameters transmitted from the main PC, manages system-level corrdination, monitors device status, and sends commend to the connected devices. <br>
Main PC communicates with PLC by using OPC UA communication protocol. <br>
To do so, two jupyter notebook codes are utilized. <br>
 1. Cell_assembly.ipynb
 2. EIS_automation.ipynb 
Communication protocols for OT2 and potentiostat are not supported by PLC, so they are directly communicate with PC. <br>

See [the manuscript in Arxiv](http://arxiv.org/abs/2512.13198)

## Information
```
codes
├── 251215_ALBATROSS.smc2: code for PLC (sysmac)
├── 251113_demo_cell_assembly.ipynb: cell-assembly process code for PC (jupyter notebook)
└── 250616_EIS automation.ipynb: Cycling channel status checking and EIS automation process code for PC (jupyter notebook)

data
├── EIS
│   ├── 0.5C
│   │   ├── example.csv: data with respect to time, voltage, current, phase, modulus, frequency
│   │   └── example_Result.csv: data of fitted data with R1, R2, R3, R4, Q1, Q2, Q3, Q4, s
│   ├── 1C
│   ├── 2C
│   └── 3C
└── cycling
    ├── EIS: cycling results for EIS test cells
    ├── repeatability_albatross: cycling results for repeatability test for albatross
    └── repeatability_manual: cycling results for repeatability test for manual assembly

ALBATROSS.mp4: a video demonstrating albatross system
```

## Communication environment
<img width="1914" height="1045" alt="Image" src="https://github.com/user-attachments/assets/01253eb2-7471-453c-8768-3564dce428d9" />
To parallelly activate the modules, PLC was used, which can support various types of communication simultaneously. The liquid handler and potentiostat have their own communication method, so they communicate with the main PC directly.
