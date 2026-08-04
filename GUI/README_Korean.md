# ALBATROSS GUI

주피터 노트북으로 셀 단위 실행하던 EIS 자동화를 PyQt6 GUI 로 옮긴 것.
기존 PLC(Sysmac) 프로그램과 OPC UA 설정은 **건드리지 않고**, 게이트웨이를 통해
같은 글로벌 변수를 읽고/쓴다.

## 연결 구조
```
PyQt GUI ──(opcua client)──> Gateway :4841 ──(1 슬롯)──> Omron PLC :4840 (ns=4)
                              ├ ns=2  Run/Cell/Control/Biologic (조정)
                              ├ ns=3  PLC.* 상태 미러   (읽기)   예: DataJig.Gantry
                              └ ns=4  Cmd.* 명령        (쓰기)   예: JOB, fbMotorN.*, *_csv
```
PLC 의 OPC UA 슬롯이 꽉 차서 GUI 는 PLC 에 직접 못 붙고 **게이트웨이만** 본다.

## 구조
```
ALBATROSS_GUI/
├── main.py                  # GUI 진입점
├── gateway.py               # ★ OPC UA 집계 게이트웨이 (PLC 슬롯 1개 사용)
├── config.yaml              # IP/노드/시뮬레이션 + gateway 섹션
├── requirements.txt
└── albatross/
    ├── drivers/  neware.py · plc.py · biologic.py   # 노트북 로직 그대로
    ├── workers/  base.py · poller.py · automation.py # QThread (GUI 멈춤 방지)
    └── ui/       main_window.py · tabs/              # 연결/지그/Neware/EIS/자동화
```

## 실행 순서
1) 게이트웨이 (PLC 와 통신 가능한 PC 에서):
```
pip install asyncua
python gateway.py
```
2) GUI:
```
pip install -r requirements.txt
python main.py
```
- 처음엔 `config.yaml` 의 `app.simulation: true` 라 **장비/게이트웨이 없이도** 창이 뜬다.
- 실제 사용: `app.simulation: false` 로 바꾸고, `gateway.url` 을 게이트웨이 PC 주소로
  맞춘다 (같은 PC 면 `opc.tcp://127.0.0.1:4841/gateway/`).

## 주피터에서 쓰기 (GUI 없이 트리거만)
GUI(`python main.py`)는 터미널에서 실행하세요. 주피터에서는 **GUI 대신 Controller** 를 import 해서
셀별로 트리거만 호출하면 됩니다 (예전 노트북 방식과 동일, 코드만 깔끔).

```python
import sys, os; sys.path.insert(0, os.path.abspath("."))   # ALBATROSS_GUI 에서 실행
from albatross.config import load_config
from albatross.controller import Controller

ctrl = Controller.build(load_config()); ctrl.connect_all()
ctrl.jig_retrieve(12)                              # 지그
ctrl.measure_eis("C:/EIS/test.csv", channel=1)     # EIS
ctrl.start_cycling(range(0,6), "proto.xml", "C:/NewareData/")  # 충방전
ctrl.run_automation("C:/EIS/", check_ch=range(48)) # 자동화 (블로킹; 멈추려면 커널 인터럽트)
```
바로 쓸 수 있는 노트북: `examples/albatross_jupyter.ipynb`.
스크립트 버전: `examples/run_triggers.py` (`python examples/run_triggers.py`).

## GUI 가 쓰는 OPC UA 노드 (게이트웨이 경유)
- 쓰기(ns=4 Cmd): `JOB`(지그 이동), `fbMotor1~4.*`(모터), `Jigmove_csv`/`EISmove_csv`(좌표)
- 읽기(ns=3 미러): `DataJig.Gantry` 등 상태
- 조정(ns=2 self): `Control.StopRequest` / `Control.Emergency` (비상정지 버튼이 사용)

## gateway.py 에 적용한 변경 (기존 기능은 유지)
- **명령 노드 추가**: `JOB`(String 배열), 모터 24개, `Jigmove_csv`/`EISmove_csv`(2D)를
  별도 `ns=4`(Cmd) 에 생성 → 기존 상태 미러(ns=3)와 충돌 없음. write-through 로 PLC 전달.
- **중복 노드 방어**: `PLC_MIRROR_NODES` 에 `bPlate_aligncheck` 가 두 번 있어 시작 시
  크래시하던 것을 중복 skip 으로 수정.
- 명령 노드는 PLC 미연결 상태에서도 생성된다(GUI/게이트웨이만으로 테스트 가능).

## 안전
- 상단 **비상 정지**: 자동화 중단 + `Control.Emergency`/`StopRequest` 설정 + 모터 전원 차단 시도.
- 자동화 루프는 매 주기 `Control.StopRequest` 를 확인해 외부에서도 멈출 수 있다.
- 모든 장비 동작은 백그라운드 스레드 → 측정/이동 중에도 창이 멈추지 않음.
