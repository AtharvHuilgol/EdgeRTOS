# EdgeRTOS User & Deployment Manual

This manual guides you through installing, configuring, running, and benchmarking **EdgeRTOS** on your development PC and Raspberry Pi (Ubuntu 22.04 LTS).

---

## 1. Quick Setup on Development Machine (Windows / Linux / macOS)

### Prerequisites
- Python 3.10 or higher
- Git

### Installation
Clone the repository and install in editable development mode:
```bash
git clone https://github.com/AtharvHuilgol/EdgeRTOS.git
cd EdgeRTOS
pip install -e .
```

### Running the Test Suite
Verify that all RTOS primitives, schedulability checks, and confidence adaptation policies pass:
```bash
python -m unittest discover tests
```

---

## 2. Running Runnable Examples

### 2.1 Basic Multi-Task RTOS Demo
```bash
python examples/basic_rtos_demo.py
```
Demonstrates a 50ms producer and 100ms consumer exchanging messages over a bounded queue with jitter tracking.

### 2.2 Complete 5-Task Edge AI Pipeline
```bash
python examples/edge_ai_pipeline.py
# or
python main_example.py
```
Simulates the full confidence-adaptive edge AI vision pipeline across confident and ambiguous phases with a live terminal dashboard.

---

## 3. Running Line-Following Robot Experiments

### 3.1 Step 1: Establish the Fixed-Rate Baseline
```bash
python -m Line_Following_Robot.experiments.run_baseline
```
Runs the line follower at a fixed 100ms inference period and writes baseline metrics to `benchmarks/benchmark_baseline.csv`.

### 3.2 Step 2: Execute the Dynamic Adaptive Driver
```bash
python -m Line_Following_Robot.experiments.run_adaptive
```
Runs the line follower governed by on-device model confidence and writes adaptive metrics to `benchmarks/benchmark_adaptive.csv`.

### 3.3 Step 3: Generate Comparative Performance Analysis
```bash
python -m Line_Following_Robot.experiments.analysis
```
Parses both CSV runs and displays comparative diagnostics:
- System CPU % savings
- Deadline hit rate compliance
- Inference sampling period range and responsiveness

---

## 4. Deploying to Raspberry Pi (Ubuntu 22.04 LTS Desktop)

### 4.1 System Dependencies
```bash
sudo apt update
sudo apt install -y python3-pip python3-dev libcamera-dev python3-picamera2
pip install numpy psutil
```

### 4.2 Enabling POSIX Real-Time Priorities (`SCHED_FIFO`)
To allow `EdgeRTOS` to set kernel-level real-time thread priorities:
```bash
# Option A: Run scripts with sudo
sudo python3 -m Line_Following_Robot.experiments.run_adaptive

# Option B: Grant CAP_SYS_NICE privilege to Python binary
sudo setcap cap_sys_nice=eip $(readlink -f $(which python3))
```

### 4.3 Connecting Physical Hardware
| Component | Raspberry Pi Pin (BCM) | Function |
|---|---|---|
| IR Sensor Left-2 | GPIO 17 | Far-left track detection |
| IR Sensor Left-1 | GPIO 27 | Left track detection |
| IR Sensor Center | GPIO 22 | Center line detection |
| IR Sensor Right-1 | GPIO 23 | Right track detection |
| IR Sensor Right-2 | GPIO 24 | Far-right track detection |
| Motor Driver IN1 / IN2 | GPIO 5 / GPIO 6 | Left Motor Direction |
| Motor Driver IN3 / IN4 | GPIO 13 / GPIO 19 | Right Motor Direction |
| Motor Driver ENA / ENB | GPIO 12 / GPIO 18 | PWM Speed Control (Hardware PWM) |
| Buzzer / LED Actuator | GPIO 25 | Active Buzzer trigger |
