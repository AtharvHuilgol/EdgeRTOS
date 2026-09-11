# EdgeRTOS: Confidence-Aware Real-Time Scheduling for Edge AI

**EdgeRTOS** is an embedded-style Real-Time Operating System (RTOS) scheduling layer written in Python, engineered for edge devices such as the **Raspberry Pi 4 / 5 running Ubuntu 22.04 Desktop**.

It bridges on-device neural network uncertainty with real-time OS scheduling, allowing an AI model's output confidence to dynamically adapt inference sampling period and task priority while formally guaranteeing that safety-critical real-time tasks (like frame capture and actuation) are never starved.

---

## 🚀 Key Features

- **Embedded RTOS Primitives**:
  - Task Control Block (`Task`, `TaskStats`, `TaskState`: `READY`, `RUNNING`, `BLOCKED`, `SUSPENDED`, `TERMINATED`)
  - Numeric Priority Scale (`0` = Idle up to `99` = Max Real-Time)
  - Drift-Free Periodic Timing: `delay_until` (`vTaskDelayUntil`) with high-resolution monotonic timekeeping
  - Inter-Task Communication (IPC): Thread-safe `Queue` (`xQueueSend` / `xQueueReceive`) with overwrite mode for camera buffers, `EventGroup` flag synchronization, `Mutex`, and `Semaphore`
- **POSIX Real-Time Scheduling on Linux / Raspberry Pi**:
  - Automatically sets `SCHED_FIFO` / `SCHED_RR` native thread scheduling via POSIX `pthread_setschedparam` when running with `sudo` or `CAP_SYS_NICE` on Ubuntu 22.04.
  - Seamless fallback on Windows / macOS for local development and testing.
- **Formal Schedulability Analysis**:
  - Rate-Monotonic (RM) Liu & Layland bound: $U \le n(2^{1/n} - 1)$
  - Exact Response-Time Analysis (RTA): $R_i^{(k+1)} = C_i + \sum_{j \in hp(i)} \left\lceil \frac{R_i^{(k)}}{T_j} \right\rceil C_j$
  - Earliest Deadline First (EDF) bound: $U \le 1.0$
  - **Dynamic Admission Guard**: Mathematically verifies that any runtime period shrink or priority boost will never cause safety-critical tasks to miss their hard deadlines.
- **Novel Confidence-Aware Dynamic Scheduler**:
  - Softmax max-probability ($P_{\max}$) and Shannon predictive entropy ($H(p) = -\sum p_i \log_2 p_i$) tracking across a sliding window.
  - **High & Stable Confidence**: Stretches $T_{\text{infer}}$ period (up to 250–300 ms) and lowers priority to dramatically cut CPU utilization and battery power.
  - **Low / Oscillating Confidence**: Shrinks $T_{\text{infer}}$ period (down to 50 ms), boosts priority, and escalates secondary sensor verification ($T_{\text{sensor\_check}}$) for rapid, safety-first responsiveness.
- **Telemetry & Logging**:
  - Tracks cycle-by-cycle execution latency, jitter, CPU % (via `psutil`), and deadline hits/misses.
  - Exports directly to `edgertos_metrics_log.csv` for conference paper / project report charts.

---

## 📁 Repository Structure

```
d:\Projects\EdgeRTOS\RTOS code\
├── edgertos.py            # Core RTOS scheduling layer and confidence engine
├── rtos.py                # Compatibility module (allows `import rtos`)
├── main_example.py        # Complete 5-task demo pipeline (Capture, Infer, Monitor, Sensor, Actuate)
├── test_edgertos.py       # Comprehensive unit & integration test suite (10/10 PASS)
├── edgertos_metrics_log.csv # Generated cycle-by-cycle benchmark telemetry
└── README.md              # Documentation and usage guide
```

---

## 💻 Quick Start & Testing

### 1. Running the Test Suite (Windows or Linux)
```bash
python -m unittest test_edgertos.py
```

### 2. Running the Complete 5-Task Demo
```bash
python main_example.py
```
This runs a 15-second simulation showing:
- **Phase 1 (0–7s)**: Confident & stable inferences $\to$ Period stretches from 100ms up to 250ms, priority decreases, CPU conserved.
- **Phase 2 (7–14s)**: Ambiguous / occluded inputs $\to$ Period shrinks to 50ms, priority rises to 70, sensor check escalated.
- **Phase 3 (14–21s)**: Recovery back to confident baseline $\to$ Period stretches back to save power.

---

## 🛠️ How to Use in Your Own `main.py`

```python
import edgertos as rtos
from edgertos import Priority, Task, Queue, EventGroup, ConfidenceScheduler

# 1. Initialize the RTOS Scheduler
scheduler = rtos.RTOSScheduler("MyEdgeSystem")

# 2. Create RTOS Queues and Events
frame_queue = rtos.Queue(maxsize=2)
events = rtos.EventGroup()

# 3. Define Task Functions
def task_camera():
    # Read camera frame
    frame = get_camera_frame()
    frame_queue.send_overwrite(frame)

def task_ai_infer():
    frame = frame_queue.receive(timeout_ms=5)
    if frame is not None:
        probs = run_tflite_model(frame)
        # Notify confidence scheduler
        conf_scheduler.push_inference_result(probs, predicted_class="person")

# 4. Register Tasks with Priorities and Periods
t_cam = scheduler.create_task(
    name="T_capture",
    func=task_camera,
    priority=Priority.HIGH,     # Priority 70
    period_ms=100.0,            # Run every 100ms
    wcet_ms=5.0,
    is_hard_realtime=True       # Hard bound: never starved
)

t_infer = scheduler.create_task(
    name="T_infer",
    func=task_ai_infer,
    priority=Priority.MEDIUM,   # Adapted at runtime
    period_ms=100.0,            # Adapted between 50ms and 250ms
    wcet_ms=25.0
)

# 5. Attach Confidence Adaptation Engine
conf_scheduler = ConfidenceScheduler(
    target_task_name="T_infer",
    min_period_ms=50.0,
    max_period_ms=250.0,
    nominal_period_ms=100.0
)
scheduler.attach_confidence_scheduler(conf_scheduler)

# 6. Verify Formal Schedulability & Start
tasks = scheduler.get_all_tasks()
is_schedulable, u, bound = rtos.SchedulabilityAnalyzer.is_rm_schedulable_bound(tasks)
print(f"RM Schedulability: {is_schedulable} (U={u:.2f} <= {bound:.2f})")

scheduler.start()

# Let it run
try:
    while True:
        rtos.delay_ms(1000)
except KeyboardInterrupt:
    scheduler.stop()
```

---

## 🍓 Deploying to Raspberry Pi (Ubuntu 22.04)

### Enabling Real-Time Capabilities
To enable native Linux `SCHED_FIFO` real-time scheduling for true microsecond priority preemption:
```bash
# Run with root privileges to grant CAP_SYS_NICE:
sudo python3 main_example.py
```
Or grant `cap_sys_nice` to python3:
```bash
sudo setcap cap_sys_nice=eip $(which python3)
```

### Wiring Real Hardware in `main_example.py`
In `main_example.py`:
1. **Camera**: Replace `task_capture` dummy frame with `cv2.VideoCapture(0)` or `libcamera` / `picamera2`.
2. **AI Inference**: Load your `.tflite` model:
   ```python
   from tflite_runtime.interpreter import Interpreter
   interpreter = Interpreter(model_path="mobilenet_v2.tflite")
   interpreter.allocate_tensors()
   ```
3. **Buzzer / Actuator**: In `task_actuate`:
   ```python
   import RPi.GPIO as GPIO
   GPIO.setmode(GPIO.BCM)
   GPIO.setup(18, GPIO.OUT)
   GPIO.output(18, GPIO.HIGH)
   ```
4. **Ultrasonic (HC-SR04)**: In `task_sensor_check` for secondary distance confirmation.
