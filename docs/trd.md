# Technical Requirements Document (TRD)

## Project Title
**Confidence-Aware Real-Time Scheduling for Edge AI Inference**

**Academic Supervision:** Prof. Archana Bhamare  
**Authors:** Atharv Huilgol, Vibhuti Sahu, Chinmayi Pethkar  

---

## 1. Executive Summary & Objective
Modern edge computing and autonomous embedded systems (robotics, smart cameras, IoT) traditionally schedule neural network inference as an invariant, fixed-period, fixed-priority task ($T_{\text{infer}}$). This design suffers from two fundamental limitations:
1. **Resource Waste:** Invariant high-rate inference on straightforward, predictable inputs burns unnecessary CPU cycles and power.
2. **Delayed Response in Ambiguity:** When predictions become uncertain, occluded, or unstable, fixed-rate scheduling fails to compress sampling intervals to escalate attention.

**EdgeRTOS** addresses this gap by creating a closed-loop feedback mechanism: an on-device neural network's own output prediction-confidence vector is fed back into the RTOS scheduler as a first-class input. The scheduler dynamically adapts $T_{\text{infer}}$'s execution priority and release period while mathematically proving that hard safety-critical tasks ($T_{\text{ir\_read}}$, $T_{\text{motor\_control}}$, $T_{\text{capture}}$) will never miss deadlines.

---

## 2. System Task Architecture & Timing Model

| Task Name | Semantics | Type | Priority ($P_i$) | Period ($T_i$) | Deadline ($D_i$) | WCET ($C_i$) | Criticality |
|---|---|---|---|---|---|---|---|
| `T_ir_read` | 5-channel IR sensor scan & path estimation | Periodic | 99 (Fixed) | 25 ms | 25 ms | 2.0 ms | **Hard Real-Time** |
| `T_motor_control` | Steering fusion & motor PWM actuation | Periodic | 90 (Fixed) | 25 ms | 25 ms | 3.0 ms | **Hard Real-Time** |
| `T_capture` | Hardware camera buffer grabber | Periodic | 70 (Fixed) | 60 ms | 60 ms | 4.0 ms | **Hard Real-Time** |
| `T_sched_monitor` | Uncertainty analyzer & dynamic adaptation | Periodic/Event | 80 (Fixed) | 40 ms | 40 ms | 2.0 ms | **Hard Real-Time** |
| `T_infer` | Quantized CNN path / obstacle inference | Adaptive | 30–70 (Dynamic) | 60–250 ms (Dynamic) | $D_i = T_i$ | 20.0 ms | **Firm / Soft RT** |
| `T_logger` | Telemetry & power consumption commit | Periodic | 20 (Fixed) | 100 ms | 100 ms | 2.0 ms | **Non-Critical** |

---

## 3. Mathematical Formulations

### 3.1 Uncertainty & Confidence Metrics
For a softmax output probability vector $\mathbf{p} = [p_1, p_2, \dots, p_K]$ produced by $T_{\text{infer}}$:
1. **Max Probability Metric:**
   $$P_{\max} = \max_{k \in \{1, \dots, K\}} p_k$$
2. **Shannon Predictive Entropy:**
   $$H(\mathbf{p}) = -\sum_{k=1}^K p_k \log_2(p_k + \epsilon)$$
   where $\epsilon = 10^{-7}$ prevents $\log(0)$.
3. **Sliding Window Statistics:**
   Across a sliding window of $W$ inferences:
   $$\bar{P} = \frac{1}{W}\sum_{j=1}^W P_{\max}^{(j)}, \quad \sigma_P^2 = \frac{1}{W}\sum_{j=1}^W (P_{\max}^{(j)} - \bar{P})^2$$
   $$\text{FlipRate} = \frac{1}{W-1} \sum_{j=2}^W \mathbb{I}\left(\hat{y}^{(j)} \ne \hat{y}^{(j-1)}\right)$$

### 3.2 Formal Schedulability & Safety Bounds
1. **Rate-Monotonic (RM) Utilization Bound (Liu & Layland):**
   $$U = \sum_{i=1}^n \frac{C_i}{T_i} \le n \left(2^{1/n} - 1\right)$$
2. **Exact Response-Time Analysis (RTA):**
   For each task $i$, its worst-case response time $R_i$ is computed iteratively:
   $$R_i^{(0)} = C_i, \quad R_i^{(k+1)} = C_i + \sum_{j \in hp(i)} \left\lceil \frac{R_i^{(k)}}{T_j} \right\rceil C_j$$
   Schedulability holds iff $\forall i, R_i \le D_i$.
3. **Online Schedulability Admission Guard:**
   Before applying any period reduction $T_{\text{infer}} \leftarrow T_{\text{infer}} - \Delta T$, the scheduler tests:
   $$U_{\text{candidate}} \le U_{\max} \quad \wedge \quad \forall t \in \text{HardTasks}, R_t \le D_t$$
   If the check fails, the adaptation is clamped to the minimum safe period $T_{\text{safe}}$.

---

## 4. Hardware & Software Requirements

- **Compute:** Raspberry Pi 4 Model B (4GB/8GB) or Raspberry Pi 5.
- **Operating System:** Ubuntu 22.04 LTS Desktop with standard POSIX priority (`SCHED_FIFO`) or PREEMPT_RT kernel.
- **Vision:** Raspberry Pi Camera Module v2 / v3 or USB UVC Webcam.
- **Sensors & Actuators:** 5-Channel TCRT5000 IR sensor array, L298N/TB6612FNG Dual DC Motor Driver, HC-SR04 Ultrasonic sensor.
- **Runtime:** Python 3.10+, NumPy, TensorFlow Lite Runtime (`tflite_runtime`), PSUtil.
