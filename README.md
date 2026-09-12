# Confidence-Aware RTOS Line-Following Robot

An embedded real-time operating system architecture implemented on a Raspberry Pi that feeds an on-device AI model's prediction-confidence score back into the RTOS scheduler as a first-class input. The system dynamically scales task priorities and inference rates to optimize power on predictable path segments while guaranteeing deterministic, safety-critical execution during complex track maneuvers.

---

## 📁 Project Directory Structure

```text
EdgeRTOS/                          ← RTOS core library
├── __init__.py
├── task.py
├── scheduler.py
├── metrics.py
└── schedulability.py
Line_Following_Robot/              ← Robot application
│
├── motor_control/                 ← Hardware HAL layer
│   └── sensor_interface.py        (IR sensors, motors, camera)
│
├── ai/                            ← AI inference layer
│   ├── object_detection_app.py    (obstacle detection task)
│   └── models/                    (TFLite model binaries)
│       ├── line_classifier.tflite
│       └── object_detector.tflite
│
└── robot/                         ← High-level robot logic
    ├── line_follower_app.py        (fixed-rate baseline)
    ├── line_follower_adaptive.py   (confidence-adaptive)
    └── experiments/
        ├── run_baseline.py
        ├── run_adaptive.py
        ├── data_collection.py
        └── analysis.py
examples/                          ← Generic EdgeRTOS demos
tests/                             ← Unit test suite
docs/                              ← Design documents
```

---

## 🛠️ System Architecture & Task Design

The application runs deterministically under Linux utilizing `PREEMPT_RT` patch real-time mechanics (with an active fallback to `SCHED_FIFO` priorities under standard Raspberry Pi OS flags if required).

### Real-Time Task Framework

The engine isolates execution responsibilities into distinct periodic tasks with the following hard-coded and dynamic constraints:

| Task | Function | Priority | Period / Deadline |
| --- | --- | --- | --- |
| `T_ir_read` | Reads the 5-channel physical IR array; computes backup path estimate | **Highest (Fixed)** | 20–30 ms (Tight loop) |
| `T_motor_control` | Fuses AI steering directives or safely commands IR fallback outputs | **Highest (Fixed)** | 20–30 ms (Tight loop) |
| `T_capture` | Captures incoming hardware camera frames from the pipeline buffer | **High (Fixed)** | 50–80 ms |
| `T_sched_monitor` | Computes semantic confidence trends and dynamically updates `T_infer` parameters | **High (Fixed)** | Triggered instantly upon `T_infer` exit |
| `T_infer` | Executes quantized TFLite CNN inference to produce classification scores | **Variable (Adaptive)** | Dynamic window: 60–250 ms |
| `T_logger` | Commits hardware power metrics, execution latencies, and state flags to disk | **Low (Fixed)** | 100 ms |

### The Closed-Loop Adaptation Policy

* 🚀 **High Confidence (Straight Paths):** When the AI model yields high, stable softmax confidence vectors, `T_sched_monitor` stretches the sampling period of `T_infer` and drops its priority. This immediately scales back CPU cycles and throttles overall energy usage while safely maintaining cruise velocities.


* ⚠️ **Low/Oscillating Confidence (Curves/Intersections):** When faced with faded markings, occlusions, or complex junctions, `T_infer`'s priority is elevated instantly and its period is compressed. This forces rapid vision sampling for finer trajectory adjustments.


* 🛡️ **Hard Safety Bounds:** The dynamic priority modifications are mathematically bounded using strict Rate-Monotonic (RM) / Earliest-Deadline-First (EDF) feasibility profiles. `T_infer` can never preempt or starve `T_ir_read` or `T_motor_control`. If `T_infer` suffers a deadline miss, the monitor instantly sets an explicit fallback flag, causing `T_motor_control` to calculate steering using the hardwired IR array.



---

## 🚀 Getting Started

> **Raspberry Pi 4 / Ubuntu users:** See **[INSTALL_RPI.md](INSTALL_RPI.md)** for the full step-by-step hardware setup, GPIO wiring, and real-time scheduling configuration.

### Prerequisites

1. **Hardware Assembly:** Wire your Raspberry Pi 4 Model B to:
   - Pi Camera Module (downward-facing)
   - 5-channel IR sensor array (BCM 17, 27, 22, 23, 24)
   - L298N / TB6612FNG motor driver (BCM 12, 5, 6, 13, 20, 21)
   - INA219 power monitor breakout (I²C: SDA=GPIO2, SCL=GPIO3)
   - Active buzzer on BCM 18, LED on BCM 25

2. **Real-Time Environment (Ubuntu):** Install `lgpio` for GPIO access, then grant real-time scheduling permission:
   ```bash
   sudo apt-get install -y lgpio libgpiod2
   # Grant rtprio (see INSTALL_RPI.md §7 for details):
   sudo sh -c 'echo "ubuntu - rtprio 99" >> /etc/security/limits.d/99-rtprio.conf'
   ```

3. **Dependencies:** Clone the repo and install:
   ```bash
   git clone https://github.com/AtharvHuilgol/EdgeRTOS.git
   cd EdgeRTOS

   # All platforms (simulation + testing):
   pip install -r requirements.txt

   # Raspberry Pi 4/5 hardware extras:
   pip install -r requirements-rpi.txt

   # Optional: install EdgeRTOS as a proper Python package
   pip install -e .
   ```

   Key packages installed on RPi:
   | Package | Purpose |
   |---|---|
   | `psutil` | CPU monitoring |
   | `RPi.GPIO` | GPIO / motor / sensor control |
   | `smbus2`, `pi-ina219` | INA219 I²C power sensor |
   | `ai-edge-litert` | TFLite runtime for CNN inference (replaces deprecated `tflite-runtime`) |
   | `numpy` | Experiment analysis |
   | `pytest` | Test suite |

### Quick Start (Simulation — works on any OS)

```bash
# Basic RTOS demo
python examples/basic_rtos_demo.py

# Full AI pipeline simulation (no hardware needed)
python examples/edge_ai_pipeline.py

# Run unit tests
python -m pytest tests/ -v
```

### Running the Experiments

To evaluate the efficiency gains of the confidence-aware scheduler vs a traditional static-rate loop:

1. **Static Baseline Profile** — fixed priority, no adaptation:
   ```bash
   python -m Line_Following_Robot.robot.experiments.run_baseline
   ```

2. **Confidence-Adaptive Mode** — EdgeRTOS closed-loop scheduler:
   ```bash
   python -m Line_Following_Robot.robot.experiments.run_adaptive
   ```

3. **Analysis & Performance Metrics** — CPU curves, jitter, deadline hit/miss ratios:
   ```bash
   python -m Line_Following_Robot.robot.experiments.analysis
   ```



---

## 👥 Project Team & Credits

Developed as an **RTOS Course Mini Project** under the academic guidance of **Prof. Archana Bhamare**.

* **Atharv Huilgol** – Core RTOS Architecture, Task Schedulability, & Adaptive Monitor Design


* **Vibhuti Sahu** – Hardware Integration, Low-level Sensor Driver Frameworks, & Logging Infrastructure


* **Chinmayi Pethkar** – Deep Learning Quantization, Edge AI Deployment, & Confidence Metric Synthesis
