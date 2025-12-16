# ALBATROSS
**A**utomated **L**i-ion **BA**ttery **T**esting **RO**bot **S**y**S**tem (**ALBATROSS**)

ALBATROSS uses PLC (NX102-9000, Omron) for integration of devices. <br>
Main PC communicates with PLC by using OPC-UA communication protocol. <br>
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
```

## Communication environment
<img width="1914" height="1045" alt="Image" src="https://github.com/user-attachments/assets/01253eb2-7471-453c-8768-3564dce428d9" />
To parallelly activate the modules, PLC was used, which can support various types of communication simultaneously. The liquid handler and potentiostat have their own communication method, so they communicate with the main PC directly.
