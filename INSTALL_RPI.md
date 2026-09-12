# EdgeRTOS — Raspberry Pi 4 Model B + Ubuntu Setup Guide

This guide covers everything needed to run **EdgeRTOS** on a Raspberry Pi 4 Model B running **Ubuntu 22.04 LTS** or **Ubuntu 24.04 LTS** (arm64).

---

## 1. Flash Ubuntu to Your RPi4

Download the **64-bit (arm64) Ubuntu Server** image from:
https://ubuntu.com/download/raspberry-pi

Flash to a microSD (≥ 16 GB) using [Raspberry Pi Imager](https://www.raspberrypi.com/software/) or `dd`.

> [!NOTE]
> Ubuntu 22.04 arm64 is the recommended target. Ubuntu 24.04 works too.
> Do **not** use the 32-bit (armhf) image — TFLite arm64 wheels are 64-bit only.

---

## 2. First Boot & System Update

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y git python3 python3-pip python3-dev build-essential
```

---

## 3. Enable Required Interfaces

### I²C (for INA219 power sensor)
```bash
sudo apt-get install -y i2c-tools python3-smbus
sudo raspi-config
# → Interface Options → I2C → Enable
# (or manually add "dtparam=i2c_arm=on" to /boot/firmware/config.txt)
```

### Camera (if using PiCamera2)
```bash
sudo apt-get install -y python3-picamera2
sudo raspi-config
# → Interface Options → Camera → Enable
```

---

## 4. Install GPIO Support (Ubuntu-specific)

Ubuntu on RPi4 does **not** ship with `pigpio` or the legacy `/dev/gpiomem` interface.
You need `lgpio`, which is the modern GPIO backend for Ubuntu:

```bash
sudo apt-get install -y lgpio libgpiod-dev libgpiod2
```

> [!IMPORTANT]
> Without `lgpio`, `RPi.GPIO` will fail to open `/dev/gpiochip0`.
> If you see `RuntimeError: Cannot determine SOC peripheral base address`, lgpio is missing.

---

## 5. Clone the Repository

```bash
git clone https://github.com/AtharvHuilgol/EdgeRTOS.git
cd EdgeRTOS
```

---

## 6. Install Python Dependencies

### Core (simulation / all platforms)
```bash
pip install -r requirements.txt
```

### Raspberry Pi hardware extras
```bash
pip install -r requirements-rpi.txt
```

This installs:
| Package | Purpose |
|---|---|
| `RPi.GPIO` | GPIO control (IR sensors, motors, buzzer, LED) |
| `smbus2` | I²C bus access |
| `pi-ina219` | INA219 power sensor driver |
| `ai-edge-litert` | Google TFLite runtime (replaces deprecated `tflite-runtime`) |

### (Optional) Install EdgeRTOS as a package
```bash
pip install -e .
```
This allows importing `EdgeRTOS` from any directory without `sys.path` hacks.

---

## 7. Real-Time Scheduling Permissions (SCHED_FIFO)

EdgeRTOS uses `SCHED_FIFO` via `pthread_setschedparam` for hard real-time threads.
On Ubuntu, non-root users need an elevated `rtprio` limit.

### Option A — Run as root (simple, for testing)
```bash
sudo python examples/edge_ai_pipeline.py
```

### Option B — Grant rtprio to your user (recommended for production)
```bash
sudo nano /etc/security/limits.d/99-rtprio.conf
```
Add:
```
# Allow <your-username> to use real-time priorities
ubuntu    -    rtprio    99
ubuntu    -    nice     -20
ubuntu    -    memlock   unlimited
```
Log out and back in. Verify with:
```bash
ulimit -r   # should print 99
```

> [!TIP]
> If SCHED_FIFO priority assignment fails, EdgeRTOS silently falls back to
> normal `SCHED_OTHER` scheduling — the system still works, just with lower
> determinism.

---

## 8. Hardware Wiring

### 5-Channel IR Sensor Array (BCM pin numbers)

| Sensor | BCM Pin | Physical Pin |
|---|---|---|
| IR_L2 (far left) | GPIO 17 | Pin 11 |
| IR_L1 (left) | GPIO 27 | Pin 13 |
| IR_MID (centre) | GPIO 22 | Pin 15 |
| IR_R1 (right) | GPIO 23 | Pin 16 |
| IR_R2 (far right) | GPIO 24 | Pin 18 |

### L298N Motor Driver

| Signal | BCM Pin | Physical Pin |
|---|---|---|
| LEFT_EN (PWM) | GPIO 12 | Pin 32 |
| LEFT_IN1 | GPIO 5 | Pin 29 |
| LEFT_IN2 | GPIO 6 | Pin 31 |
| RIGHT_EN (PWM) | GPIO 13 | Pin 33 |
| RIGHT_IN1 | GPIO 20 | Pin 38 |
| RIGHT_IN2 | GPIO 21 | Pin 40 |

### Actuator / Indicators

| Device | BCM Pin | Physical Pin | Notes |
|---|---|---|---|
| Buzzer | GPIO 18 | Pin 12 | Active buzzer or PWM |
| LED | GPIO 25 | Pin 22 | 330 Ω resistor to GND |
| HC-SR04 TRIG | GPIO 23 | Pin 16 | Shared with IR_R1 — reassign if needed |
| HC-SR04 ECHO | GPIO 24 | Pin 18 | Use 5 V → 3.3 V voltage divider! |

### INA219 Power Sensor (I²C)

| INA219 Pin | RPi4 Pin | Physical Pin |
|---|---|---|
| VCC | 3.3 V | Pin 1 |
| GND | GND | Pin 6 |
| SDA | GPIO 2 | Pin 3 |
| SCL | GPIO 3 | Pin 5 |

---

## 9. Running the Demo

### Simulation (works on any platform)
```bash
python examples/edge_ai_pipeline.py
```

### With Real Hardware on RPi4
```bash
sudo python examples/edge_ai_pipeline.py
# or with rtprio configured:
python examples/edge_ai_pipeline.py
```

### Line Following Robot

```bash
# Static baseline (fixed priority, no adaptation)
python -m Line_Following_Robot.robot.experiments.run_baseline

# Confidence-adaptive mode (EdgeRTOS closed-loop)
python -m Line_Following_Robot.robot.experiments.run_adaptive
```

### Run Tests
```bash
python -m pytest tests/ -v
```

---

## 10. Placing Your TFLite Models

Put model binaries here:
```
Line_Following_Robot/ai/models/
├── line_classifier.tflite      ← lane classification CNN
└── object_detector.tflite      ← obstacle detection model
```

Without models, all AI inference runs in transparent simulation mode.
Models must be quantised (INT8 or FLOAT16) for best performance on RPi4.

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `RuntimeError: Cannot determine SOC` | `sudo apt install lgpio` |
| `ImportError: RPi.GPIO` | `pip install RPi.GPIO` |
| `ImportError: ai_edge_litert` | `pip install ai-edge-litert` |
| `PermissionError: /dev/gpiochip0` | Run with `sudo`, or add user to `gpio` group: `sudo usermod -aG gpio $USER` |
| `pthread_setschedparam: EPERM` | Set rtprio limit (see §7) or run with `sudo` |
| INA219 not found at 0x40 | Check I²C with `i2cdetect -y 1`; verify `dtparam=i2c_arm=on` in config |
| `ai_edge_litert` not available for Python version | Use Python 3.9–3.11 (check `python3 --version`) |
