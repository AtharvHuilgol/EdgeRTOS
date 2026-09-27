/*
 * ESP32 Motor Controller — UART Receiver + L298N Driver (4-Motor)
 * ================================================================
 * Receives motor commands from Raspberry Pi over UART (Serial0 / RX0+TX0)
 * and drives FOUR DC motors through an L298N H-bridge.
 *
 * Motor Layout:
 *   Channel A (ENA / IN1 / IN2) → LEFT  side motors (2 motors in parallel)
 *   Channel B (ENB / IN3 / IN4) → RIGHT side motors (2 motors in parallel)
 *
 * Pin Mapping:
 *   L298N Signal   ESP32 GPIO
 *   ────────────   ──────────
 *   ENA (PWM)      GPIO 14
 *   IN1            GPIO 27
 *   IN2            GPIO 26
 *   IN3            GPIO 25
 *   IN4            GPIO 33
 *   ENB (PWM)      GPIO 32
 *
 * UART Wiring:
 *   RPi GPIO14 (TXD0)  →  ESP32 RX0 (GPIO3)
 *   RPi GPIO15 (RXD0)  ←  ESP32 TX0 (GPIO1)
 *   Common GND
 *
 * Protocol (ASCII, line-terminated):
 *   CMD:<left_pwm>,<right_pwm>,<base_speed>\n   → drive motors
 *   HBT\n                                        → heartbeat keepalive
 *   STP\n                                        → emergency stop
 *   RST\n                                        → reset e-stop latch
 *
 * Compatibility:
 *   ESP32 Arduino Core v2.x  (uses ledcSetup / ledcAttachPin / ledcWrite)
 *   Board: "ESP32 Dev Module" in Arduino IDE
 *   Baud:  115200
 *
 * Authors: Atharv Huilgol, Vibhuti Sahu, Chinmayi Pethkar
 */

// ═══════════════════════════════════════════════════════════════════════════════
// PIN DEFINITIONS
// ═══════════════════════════════════════════════════════════════════════════════
#define LEFT_EN   14   // ENA — PWM speed control, left motors
#define LEFT_IN1  27   // IN1 — left motor direction
#define LEFT_IN2  26   // IN2 — left motor direction
#define RIGHT_IN3 25   // IN3 — right motor direction
#define RIGHT_IN4 33   // IN4 — right motor direction
#define RIGHT_EN  32   // ENB — PWM speed control, right motors

// ═══════════════════════════════════════════════════════════════════════════════
// PWM CONFIGURATION — ESP32 Arduino Core v2.x API
//   ledcSetup(channel, freq, resolution)
//   ledcAttachPin(pin, channel)
//   ledcWrite(channel, duty)
// ═══════════════════════════════════════════════════════════════════════════════
#define PWM_FREQ        1000   // 1 kHz
#define PWM_RESOLUTION     8   // 8-bit → duty range 0–255
#define PWM_CH_LEFT        0   // LEDC channel 0 for left motors
#define PWM_CH_RIGHT       1   // LEDC channel 1 for right motors

// ═══════════════════════════════════════════════════════════════════════════════
// UART & PROTOCOL
// ═══════════════════════════════════════════════════════════════════════════════
#define UART_BAUD        115200
#define MAX_LINE_LEN        64
#define WATCHDOG_TIMEOUT  1500   // ms — stop motors if no message received

// ═══════════════════════════════════════════════════════════════════════════════
// STATUS LED
// ═══════════════════════════════════════════════════════════════════════════════
#define LED_PIN 2   // Onboard LED on most ESP32 dev boards

// ═══════════════════════════════════════════════════════════════════════════════
// GLOBAL STATE
// ═══════════════════════════════════════════════════════════════════════════════
char rxBuffer[MAX_LINE_LEN];
int  rxIndex = 0;

unsigned long lastMessageTime = 0;
bool motorsActive   = false;
bool estopTriggered = false;

// Telemetry counters
unsigned long cmdCount = 0;
unsigned long hbtCount = 0;
unsigned long errCount = 0;


// ═══════════════════════════════════════════════════════════════════════════════
// MOTOR CONTROL
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Initialise direction pins and LEDC PWM channels.
 * Uses Core v2.x API: ledcSetup() + ledcAttachPin()
 */
void motorSetup() {
    // Direction pins — all LOW initially
    pinMode(LEFT_IN1,  OUTPUT);  digitalWrite(LEFT_IN1,  LOW);
    pinMode(LEFT_IN2,  OUTPUT);  digitalWrite(LEFT_IN2,  LOW);
    pinMode(RIGHT_IN3, OUTPUT);  digitalWrite(RIGHT_IN3, LOW);
    pinMode(RIGHT_IN4, OUTPUT);  digitalWrite(RIGHT_IN4, LOW);

    // Configure LEDC channels (Core v2.x API)
    ledcSetup(PWM_CH_LEFT,  PWM_FREQ, PWM_RESOLUTION);
    ledcSetup(PWM_CH_RIGHT, PWM_FREQ, PWM_RESOLUTION);

    // Attach enable pins to their LEDC channels
    ledcAttachPin(LEFT_EN,  PWM_CH_LEFT);
    ledcAttachPin(RIGHT_EN, PWM_CH_RIGHT);

    // Start with motors off
    ledcWrite(PWM_CH_LEFT,  0);
    ledcWrite(PWM_CH_RIGHT, 0);

    Serial.println("[MOTOR] Pins and PWM channels initialized (Core v2.x API)");
}

/**
 * Drive a single motor channel.
 *
 * @param in1Pin   Direction pin 1
 * @param in2Pin   Direction pin 2
 * @param pwmChan  LEDC channel number
 * @param speed    -100.0 (full reverse) to +100.0 (full forward)
 */
void driveChannel(int in1Pin, int in2Pin, int pwmChan, float speed) {
    // Clamp
    if (speed >  100.0f) speed =  100.0f;
    if (speed < -100.0f) speed = -100.0f;

    // Direction
    if (speed >= 0.0f) {
        digitalWrite(in1Pin, HIGH);
        digitalWrite(in2Pin, LOW);
    } else {
        digitalWrite(in1Pin, LOW);
        digitalWrite(in2Pin, HIGH);
    }

    // PWM duty: percentage → 0-255
    uint8_t duty = (uint8_t)(fabsf(speed) * 255.0f / 100.0f);
    ledcWrite(pwmChan, duty);
}

/**
 * Set both motor channels simultaneously.
 * Channel A drives 2 left-side motors in parallel.
 * Channel B drives 2 right-side motors in parallel.
 *
 * @param leftPWM   Left motor speed  (-100 to +100)
 * @param rightPWM  Right motor speed (-100 to +100)
 */
void setMotorSpeeds(float leftPWM, float rightPWM) {
    driveChannel(LEFT_IN1,  LEFT_IN2,  PWM_CH_LEFT,  leftPWM);
    driveChannel(RIGHT_IN3, RIGHT_IN4, PWM_CH_RIGHT, rightPWM);
    motorsActive = true;
}

/**
 * Emergency stop — immediately cut all motor drive.
 */
void emergencyStop() {
    // Zero PWM first (immediate)
    ledcWrite(PWM_CH_LEFT,  0);
    ledcWrite(PWM_CH_RIGHT, 0);

    // Pull all direction pins LOW (brake mode)
    digitalWrite(LEFT_IN1,  LOW);
    digitalWrite(LEFT_IN2,  LOW);
    digitalWrite(RIGHT_IN3, LOW);
    digitalWrite(RIGHT_IN4, LOW);

    motorsActive = false;
    Serial.println("[MOTOR] EMERGENCY STOP — all channels off");
}


// ═══════════════════════════════════════════════════════════════════════════════
// PROTOCOL PARSER
// ═══════════════════════════════════════════════════════════════════════════════

void processLine(const char* line) {
    lastMessageTime = millis();

    // ── Emergency Stop ──────────────────────────────────────────────────────
    if (strncmp(line, "STP", 3) == 0) {
        emergencyStop();
        estopTriggered = true;
        Serial.println("ACK:ESTOP");
        return;
    }

    // ── Reset E-Stop latch ──────────────────────────────────────────────────
    if (strncmp(line, "RST", 3) == 0) {
        estopTriggered = false;
        Serial.println("ACK:OK_RESET");
        return;
    }

    // ── Heartbeat ───────────────────────────────────────────────────────────
    if (strncmp(line, "HBT", 3) == 0) {
        hbtCount++;
        // Quick LED blink to show connection is alive
        digitalWrite(LED_PIN, HIGH);
        delayMicroseconds(500);
        digitalWrite(LED_PIN, LOW);
        return;
    }

    // ── Motor Command: CMD:<left>,<right>,<base> ────────────────────────────
    if (strncmp(line, "CMD:", 4) == 0) {
        if (estopTriggered) {
            Serial.println("ACK:ERR_ESTOP");
            return;
        }

        const char* payload = line + 4;
        char* endPtr;

        float leftPWM  = strtof(payload,    &endPtr);
        if (*endPtr != ',') { errCount++; Serial.println("ACK:ERR_PARSE"); return; }

        float rightPWM = strtof(endPtr + 1, &endPtr);
        if (*endPtr != ',') { errCount++; Serial.println("ACK:ERR_PARSE"); return; }

        float baseSpeed = strtof(endPtr + 1, &endPtr);
        (void)baseSpeed;  // Informational only

        setMotorSpeeds(leftPWM, rightPWM);
        cmdCount++;
        // Uncomment next line to enable per-command ACK (adds ~1ms latency):
        // Serial.println("ACK:OK");
        return;
    }

    // ── Unknown ─────────────────────────────────────────────────────────────
    errCount++;
    Serial.print("ACK:ERR_UNKNOWN:");
    Serial.println(line);
}


// ═══════════════════════════════════════════════════════════════════════════════
// WATCHDOG — Safety timeout
// ═══════════════════════════════════════════════════════════════════════════════

void checkWatchdog() {
    if (!motorsActive) return;
    if ((millis() - lastMessageTime) > WATCHDOG_TIMEOUT) {
        Serial.println("[WATCHDOG] Timeout — stopping motors");
        emergencyStop();
    }
}


// ═══════════════════════════════════════════════════════════════════════════════
// PERIODIC STATUS
// ═══════════════════════════════════════════════════════════════════════════════

unsigned long lastStatusTime = 0;

void printStatus() {
    if ((millis() - lastStatusTime) < 2000) return;
    lastStatusTime = millis();

    Serial.print("[STATUS] cmds=");  Serial.print(cmdCount);
    Serial.print(" hbt=");           Serial.print(hbtCount);
    Serial.print(" err=");           Serial.print(errCount);
    Serial.print(" motors=");        Serial.print(motorsActive ? "ON" : "OFF");
    Serial.print(" estop=");         Serial.println(estopTriggered ? "YES" : "NO");
}


// ═══════════════════════════════════════════════════════════════════════════════
// SETUP & LOOP
// ═══════════════════════════════════════════════════════════════════════════════

void setup() {
    // UART0 — RPi communication (RX0=GPIO3, TX0=GPIO1)
    Serial.begin(UART_BAUD);
    while (!Serial) { delay(10); }

    Serial.println();
    Serial.println("=================================================");
    Serial.println("  ESP32 Motor Controller (4-Motor / L298N)");
    Serial.println("  Core v2.x | ENA=14 IN1=27 IN2=26");
    Serial.println("            | ENB=32 IN3=25 IN4=33");
    Serial.println("  Waiting for RPi commands on UART0...");
    Serial.println("=================================================");

    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);

    motorSetup();

    lastMessageTime = millis();

    // Startup blink (3×)
    for (int i = 0; i < 3; i++) {
        digitalWrite(LED_PIN, HIGH); delay(120);
        digitalWrite(LED_PIN, LOW);  delay(120);
    }

    Serial.println("[READY] Listening @ 115200 baud");
}


void loop() {
    // ── Read UART byte-by-byte ──────────────────────────────────────────────
    while (Serial.available()) {
        char c = (char)Serial.read();

        if (c == '\n' || c == '\r') {
            if (rxIndex > 0) {
                rxBuffer[rxIndex] = '\0';
                processLine(rxBuffer);
                rxIndex = 0;
            }
        } else {
            if (rxIndex < MAX_LINE_LEN - 1) {
                rxBuffer[rxIndex++] = c;
            } else {
                // Buffer overflow — discard line
                rxIndex = 0;
                errCount++;
            }
        }
    }

    checkWatchdog();
    printStatus();
    delay(1);
}
