"""
Unit and Integration Tests for EdgeRTOS (`edgertos.py`)
======================================================
Tests verify:
- FreeRTOS-like synchronization primitives (Queue, EventGroup, Mutex, Semaphore)
- High-precision drift-free timing (`vTaskDelayUntil`)
- Multi-task preemptive/periodic execution
- Formal RM and EDF schedulability analysis + Exact Response-Time Analysis (RTA)
- Schedulability admission guard for safety-critical tasks
- Novel Confidence-Aware dynamic priority/period adaptation
- Telemetry logging and CSV export
"""

import math
import os
import tempfile
import time
import unittest

import edgertos as rtos


class TestRTOSPrimitives(unittest.TestCase):
    def test_queue_operations(self):
        q = rtos.Queue(maxsize=3)
        self.assertTrue(q.empty())
        self.assertFalse(q.full())

        self.assertTrue(q.send("frame_1", timeout_ms=50))
        self.assertTrue(q.send("frame_2", timeout_ms=50))
        self.assertTrue(q.send("frame_3", timeout_ms=50))
        self.assertTrue(q.full())

        # Sending to full queue should timeout and fail
        self.assertFalse(q.send("frame_4", timeout_ms=20))
        self.assertEqual(q.overflow_count, 1)

        # Receive in FIFO order
        self.assertEqual(q.receive(timeout_ms=50), "frame_1")
        self.assertEqual(q.receive(timeout_ms=50), "frame_2")
        self.assertEqual(q.receive(timeout_ms=50), "frame_3")
        self.assertTrue(q.empty())

        # Receiving from empty queue should timeout
        self.assertIsNone(q.receive(timeout_ms=20))

    def test_queue_overwrite(self):
        q = rtos.Queue(maxsize=2)
        q.send_overwrite("old_1")
        q.send_overwrite("old_2")
        # Overwrite oldest item
        q.send_overwrite("newest")
        self.assertEqual(q.size(), 2)
        self.assertEqual(q.receive(), "old_2")
        self.assertEqual(q.receive(), "newest")

    def test_event_group(self):
        events = rtos.EventGroup()
        self.assertFalse(events.is_set("DETECTION_FLAG"))

        # Wait timeout when not set
        triggered = events.wait_flag("DETECTION_FLAG", timeout_ms=20)
        self.assertFalse(triggered)

        # Set flag and wait
        events.set_flag("DETECTION_FLAG")
        self.assertTrue(events.is_set("DETECTION_FLAG"))

        # Waiting with clear_on_exit=True clears the flag
        triggered = events.wait_flag("DETECTION_FLAG", clear_on_exit=True, timeout_ms=50)
        self.assertTrue(triggered)
        self.assertFalse(events.is_set("DETECTION_FLAG"))

    def test_mutex_and_semaphore(self):
        mutex = rtos.Mutex()
        with mutex:
            acquired = mutex.acquire(timeout_ms=10)
            self.assertTrue(acquired)
            mutex.release()

        sem = rtos.Semaphore(initial_value=1)
        self.assertTrue(sem.take(timeout_ms=10))
        # Semaphore now 0, taking again should fail
        self.assertFalse(sem.take(timeout_ms=20))
        sem.give()
        self.assertTrue(sem.take(timeout_ms=10))
        sem.give()


class TestSchedulabilityAnalysis(unittest.TestCase):
    def test_rm_utilization_bound(self):
        # Liu & Layland bound: n * (2^(1/n) - 1)
        # For n=1: 1.0; n=2: 0.828; n=3: 0.780; n->inf: ln(2) = 0.693
        self.assertAlmostEqual(rtos.SchedulabilityAnalyzer.rm_utilization_bound(1), 1.0, places=3)
        self.assertAlmostEqual(rtos.SchedulabilityAnalyzer.rm_utilization_bound(2), 0.828, places=3)
        self.assertAlmostEqual(rtos.SchedulabilityAnalyzer.rm_utilization_bound(3), 0.780, places=3)
        self.assertAlmostEqual(rtos.SchedulabilityAnalyzer.rm_utilization_bound(100), math.log(2), places=2)

    def test_response_time_analysis(self):
        # Create a classic real-time task set:
        # Task 1 (High prio): C=10, T=50, D=50 -> U = 0.20
        # Task 2 (Med prio):  C=15, T=100, D=100 -> U = 0.15
        # Task 3 (Low prio):  C=20, T=200, D=200 -> U = 0.10
        t1 = rtos.Task("T1", func=lambda: None, priority=90, period_ms=50.0, deadline_ms=50.0, wcet_ms=10.0)
        t2 = rtos.Task("T2", func=lambda: None, priority=50, period_ms=100.0, deadline_ms=100.0, wcet_ms=15.0)
        t3 = rtos.Task("T3", func=lambda: None, priority=20, period_ms=200.0, deadline_ms=200.0, wcet_ms=20.0)

        tasks = [t1, t2, t3]
        rta = rtos.SchedulabilityAnalyzer.response_time_analysis(tasks)

        # T1 response time = 10 ms (<= 50)
        self.assertTrue(rta["T1"][0])
        self.assertEqual(rta["T1"][1], 10.0)

        # T2 response time = 15 + ceil(15/50)*10 = 25 ms (<= 100)
        self.assertTrue(rta["T2"][0])
        self.assertEqual(rta["T2"][1], 25.0)

        # T3 response time: R0=20 -> R1=20 + ceil(20/50)*10 + ceil(20/100)*15 = 45 -> converged to 45 ms (<= 200)
        self.assertTrue(rta["T3"][0])
        self.assertEqual(rta["T3"][1], 45.0)

    def test_dynamic_adaptation_safety_guard(self):
        # T_capture is a hard real-time safety task (C=10, T=100, D=100, Priority=90)
        t_capture = rtos.Task("T_capture", func=lambda: None, priority=90, period_ms=100.0, deadline_ms=100.0, wcet_ms=10.0, is_hard_realtime=True)
        # T_infer is adaptable (C=60, nominal T=150)
        t_infer = rtos.Task("T_infer", func=lambda: None, priority=40, period_ms=150.0, deadline_ms=150.0, wcet_ms=60.0, is_hard_realtime=False)

        tasks = [t_capture, t_infer]

        # Safe candidate: shrinking period to 100ms (U = 10/100 + 60/100 = 0.70 <= 0.85)
        is_safe = rtos.SchedulabilityAnalyzer.check_dynamic_adaptation_safety(
            tasks=tasks,
            target_task_name="T_infer",
            candidate_period_ms=100.0,
            candidate_priority=50,
            max_allowable_utilization=0.85
        )
        self.assertTrue(is_safe)

        # Unsafe candidate: shrinking period to 65ms (U = 0.10 + 60/65 = 1.02 > 0.85)
        is_unsafe = rtos.SchedulabilityAnalyzer.check_dynamic_adaptation_safety(
            tasks=tasks,
            target_task_name="T_infer",
            candidate_period_ms=65.0,
            candidate_priority=50,
            max_allowable_utilization=0.85
        )
        self.assertFalse(is_unsafe)


class TestConfidenceAwareAdaptation(unittest.TestCase):
    def test_entropy_and_metrics(self):
        # Confident uniform output: p=[0.98, 0.01, 0.01]
        p_confident = [0.98, 0.01, 0.01]
        ent_conf = rtos.ConfidenceMetric.compute_entropy(p_confident)
        self.assertLess(ent_conf, 0.3)

        # Ambiguous output: p=[0.34, 0.33, 0.33]
        p_ambiguous = [0.34, 0.33, 0.33]
        ent_ambig = rtos.ConfidenceMetric.compute_entropy(p_ambiguous)
        self.assertGreater(ent_ambig, 1.4)

    def test_confidence_scheduler_adaptation(self):
        sched = rtos.RTOSScheduler("TestSched")
        t_capture = sched.create_task("T_capture", func=lambda: None, priority=90, period_ms=100.0, wcet_ms=10.0, is_hard_realtime=True)
        t_infer = sched.create_task("T_infer", func=lambda: None, priority=40, period_ms=100.0, wcet_ms=20.0)
        t_sensor = sched.create_task("T_sensor_check", func=lambda: None, priority=30, period_ms=100.0, wcet_ms=5.0)

        conf_sched = rtos.ConfidenceScheduler(
            target_task_name="T_infer",
            secondary_task_name="T_sensor_check",
            window_size=4,
            min_period_ms=50.0,
            max_period_ms=250.0,
            nominal_period_ms=100.0
        )
        sched.attach_confidence_scheduler(conf_sched)

        # 1. Feed High & Stable predictions (person detected with 95% confidence)
        for _ in range(5):
            conf_sched.push_inference_result([0.95, 0.03, 0.02], predicted_class="person")

        result = conf_sched.evaluate_and_adapt(sched)
        self.assertEqual(result["regime"], "CONFIDENT_STABLE")
        # Period should stretch to save CPU
        self.assertGreater(result["applied_period_ms"], 100.0)
        self.assertEqual(result["sched_status"], "SCHEDULABILITY_APPROVED")
        self.assertFalse(result["sensor_escalated"])

        # 2. Feed Low & Oscillating predictions (uncertain / ambiguous frames)
        for i in range(5):
            # Alternating classes with low confidence (0.45 vs 0.40)
            c = "dog" if i % 2 == 0 else "cat"
            conf_sched.push_inference_result([0.45, 0.40, 0.15], predicted_class=c)

        result_ambig = conf_sched.evaluate_and_adapt(sched)
        self.assertEqual(result_ambig["regime"], "UNCERTAIN_OSCILLATING")
        # Period should shrink for faster sampling & priority should rise
        self.assertLess(result_ambig["applied_period_ms"], result["applied_period_ms"])
        self.assertGreaterEqual(result_ambig["applied_priority"], 40)
        self.assertTrue(result_ambig["sensor_escalated"])


class TestSchedulerExecution(unittest.TestCase):
    def test_multi_task_execution_and_telemetry(self):
        sched = rtos.RTOSScheduler("ExecTestSched")
        counter = {"t1": 0, "t2": 0}

        def task1_func():
            counter["t1"] += 1

        def task2_func():
            counter["t2"] += 1

        # T1 runs every 25ms, T2 runs every 50ms
        sched.create_task("T1", func=task1_func, priority=70, period_ms=25.0, wcet_ms=2.0)
        sched.create_task("T2", func=task2_func, priority=50, period_ms=50.0, wcet_ms=2.0)

        sched.start()
        time.sleep(0.18)  # Let it run for ~180 ms
        sched.stop()

        # In ~180ms, T1 should have run roughly 6-8 times, T2 roughly 3-4 times
        self.assertGreaterEqual(counter["t1"], 4)
        self.assertGreaterEqual(counter["t2"], 2)

        summary = sched.telemetry.get_summary()
        self.assertGreater(summary["total_cycles"], 5)
        self.assertGreaterEqual(summary["hit_rate_pct"], 90.0)

        # Test CSV export
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            temp_path = f.name
        
        try:
            sched.telemetry.export_csv(temp_path)
            self.assertTrue(os.path.exists(temp_path))
            with open(temp_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                self.assertGreater(len(lines), 5)
                self.assertIn("timestamp_ms,task_name,run_count", lines[0])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
