# ALBATROSS
**A**utomated **L**i-ion **BA**ttery **T**esting **RO**bot **S**y**S**tem (**ALBATROSS**)

ALBATROSS uses PLC (NX102-9000, Omron) for integration of devices. <br>
Main PC communicates with PLC by using OPC-UA communication protocol. <br>
Communication protocols for OT2 and potentiostat are not supported by PLC, so they are directly communicate with PC. <br>
See [the manuscript in Arxiv](http://arxiv.org/abs/2512.13198)

## Information
codes <br>
├── 251215_ALBATROSS.smc2: code for PLC (sysmac) <br>
├── 251113_demo_cell_assembly.ipynb: cell-assembly process code for PC (jupyter notebook) <br>
└── 250616_EIS automation.ipynb: Cycling channel status checking and EIS automation process code for PC (jupyter notebook) <br>
<br>
data <br>
├── EIS <br>
│   └── 0.5C <br>
│       ├── example.csv: data with respect to time, voltage, current, phase, modulus, frequency <br>
│       └── example_Result.csv: data of fitted data with R1, R2, R3, R4, Q1, Q2, Q3, Q4, s <br>
│   ├── 1C <br>
│   ├── 2C <br>
│   └── 3C <br>
└── cycling <br>
    ├── EIS: cycling results for EIS test cells <br>
    ├── repeatability_albatross: cycling results for repeatability test for albatross <br>
    └── repeatability_manual: cycling results for repeatability test for manual assembly <br>

## Communication environment
<img width="1914" height="1045" alt="Image" src="https://github.com/user-attachments/assets/01253eb2-7471-453c-8768-3564dce428d9" />

├── dobbie_grip.py
│   └── dobot_class.py
│       ├── coordinate_funcs.py
│       └── dobot_api_v2.py
├── dobbie_crimp.py
│   └── dobot_class.py
│       ├── coordinate_funcs.py
│       └── dobot_api_v2.py
├── background_processes.py
│   ├── server_connection.py
│   ├── odacell_states.py
│   └── database_functions.py
│       └── qt_ui.py
├── OT2_class.py
└── camera.py

server.py
├── data_analyzer.py
├── neware_api.py
└── interface.py
