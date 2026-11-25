/*
  ============================================================================
  SENSOR NODE FIRMWARE (ESP32 + LoRa SX1278 + JSN-SR04T)
  Skala Prototipe Ember 71cm -> Digital Twin Ciliwung 1000cm
  (Output serial dikembalikan identik dengan firmware original)
  ============================================================================
*/

#include <Arduino.h>
#include <SPI.h>
#include <LoRa.h>

#define NODE_ID 102 // Sesuaikan dengan ID node fisik Anda

// ---------------- KONFIGURASI EMBER 71 CM ----------------
#define SENSOR_HEIGHT 71 // cm; Jarak sensor ke dasar ember
#define DEADZONE_CM   21 // cm; Jarak buta JSN-SR04T
#define MAX_WATER_CM  50 // cm; (71 - 21)

// Batas Siaga pada skala Ember (dalam cm)
#define SIAGA1_CM 48
#define SIAGA2_CM 43
#define SIAGA3_CM 38

// ---------------- PIN SENSOR ULTRASONIK ----------------
#define TRIG_PIN 13 // RX
#define ECHO_PIN 34 // TX; Gunakan voltage divider 5V -> ~3.3V ke ESP32

// ---------------- PIN LORA SX1278 ----------------
#define NSS 5
#define RST 14
#define DIO0 26
#define LORA_FREQ 433E6
#define LORA_SF 9      // <-- HARUS sama dengan gateway (lihat catatan di bawah)
#define LORA_BW 125E3
#define LORA_CR 5
#define LORA_SYNC 0xA5

// ---------------- PARAMETER WAKTU (ADAPTIF 15 MENIT) ----------------
const unsigned long DETECT_NORMAL_MS = 10000UL;
const unsigned long DETECT_SIAGA1_MS = 5000UL;

const unsigned long SEND_NORMAL_MS = 30000UL;
const unsigned long SEND_SIAGA2_MS = 20000UL;
const unsigned long SEND_SIAGA1_MS = 10000UL;

// ---------------- VARIABEL GLOBAL ----------------
unsigned long lastReadMs = 0;
unsigned long lastSendMs = 0;
uint32_t sequence = 0;    // mulai dari 0 (sesuai original)
int lastStatus = 4;       // 4 = Normal
int errorCount = 0;

float lastDistance = -1;  // -1 = belum/ gagal baca (sesuai original)
int lastLevelEmber = 0;   // Tinggi air sesungguhnya di ember (cm)
int lastLevel = -1;       // Tinggi air mapping (0-1000cm) untuk dikirim ke CupCarbon

const float SOUND_SPEED = 0.0343; // Kecepatan suara cm/us

// Function Prototypes
float distanceMedian();
int warningStatus(int level_ember);
unsigned long detectInterval(int status);
unsigned long sendInterval(int status);
void doRead();
void doSend();

// ============================================================================
// FUNGSI: PENENTU STATUS SIAGA
// ============================================================================
int warningStatus(int level_ember) {
  if (level_ember >= SIAGA1_CM) return 1;
  if (level_ember >= SIAGA2_CM) return 2;
  if (level_ember >= SIAGA3_CM) return 3;
  return 4; // Normal
}

unsigned long detectInterval(int status) {
  if (status == 1) return DETECT_SIAGA1_MS;
  return DETECT_NORMAL_MS;
}

unsigned long sendInterval(int status) {
  if (status == 1) return SEND_SIAGA1_MS;
  if (status == 2) return SEND_SIAGA2_MS;
  return SEND_NORMAL_MS;
}

// ============================================================================
// FUNGSI: FILTER MEDIAN
// ============================================================================
float distanceMedian() {
  float v[5];
  int validCount = 0;

  for (int i = 0; i < 5; i++) {
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(4);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);

    long duration = pulseIn(ECHO_PIN, HIGH, 40000UL); // Timeout 40ms
    if (duration > 0) {
      float d = (duration * SOUND_SPEED) / 2.0;

      // Proteksi Deadzone
      if (d > 0 && d < DEADZONE_CM) d = DEADZONE_CM;

      if (d >= DEADZONE_CM && d <= SENSOR_HEIGHT) {
        v[validCount] = d;
        validCount++;
      }
    }
    delay(20);
  }

  if (validCount == 0) return -1;

  // Bubble Sort
  for (int i = 0; i < validCount - 1; i++) {
    for (int j = i + 1; j < validCount; j++) {
      if (v[i] > v[j]) {
        float temp = v[i];
        v[i] = v[j];
        v[j] = temp;
      }
    }
  }
  return v[validCount / 2];
}

// ============================================================================
// FUNGSI: AKUISISI DATA SENSOR
// ============================================================================
void doRead() {
  float currentDistance = distanceMedian();

  if (currentDistance < 0) {
    errorCount++;
    Serial.print("# [READ] ERROR (out of range / no echo). Fail count: ");
    Serial.println(errorCount);

    if (errorCount >= 5) {
      // Set ke -1 hanya jika gagal 5 kali berturut-turut
      lastDistance = -1;
      lastLevel = -1;
      Serial.println("# [READ] 5 consecutive errors. Resetting values to -1.");
    } else {
      Serial.println("# [READ] Using previous valid data.");
    }
  } else {
    // Pembacaan valid, reset error dan update data
    errorCount = 0;
    lastDistance = currentDistance;

    lastLevelEmber = SENSOR_HEIGHT - (int)lastDistance;
    if (lastLevelEmber < 0) lastLevelEmber = 0;
    if (lastLevelEmber > MAX_WATER_CM) lastLevelEmber = MAX_WATER_CM;

    // Digital Twin Mapping (0-50cm ember menjadi 0-1000cm Ciliwung simulasi)
    lastLevel = map(lastLevelEmber, 0, MAX_WATER_CM, 0, 1000);
    lastStatus = warningStatus(lastLevelEmber);

    // ---> FORMAT SERIAL DIKEMBALIKAN PERSIS SEPERTI KODE ORIGINAL <---
    Serial.print("# [READ] distance=");
    Serial.print(lastDistance, 1);
    Serial.print(" level=");
    Serial.print(lastLevel);
    Serial.print(" status=");
    Serial.println(lastStatus);
  }
}

// ============================================================================
// FUNGSI: PENGIRIMAN DATA LORA
// ============================================================================
void doSend() {
  // ---> FORMAT JSON PAYLOAD PERSIS SEPERTI KODE ORIGINAL <---
  String msg = "{\"id\":" + String(NODE_ID) +
               ",\"distance\":" + String(lastDistance, 1) +
               ",\"level\":" + String(lastLevel) +
               ",\"seq\":" + String(sequence) + "}";

  // ---> FORMAT SERIAL TX PERSIS SEPERTI KODE ORIGINAL <---
  Serial.print("# [TX] ");
  Serial.println(msg);

  LoRa.beginPacket();
  LoRa.print(msg);
  LoRa.endPacket();

  sequence++;
}

// ============================================================================
// SETUP & MAIN LOOP
// ============================================================================
void setup() {
  Serial.begin(115200);
  while (!Serial);
  Serial.println("Node Starting...");

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  LoRa.setPins(NSS, RST, DIO0);
  if (!LoRa.begin(LORA_FREQ)) {
    Serial.println("ERROR: LoRa failed to start");
    while (1);
  }
  LoRa.setSpreadingFactor(LORA_SF);
  LoRa.setSignalBandwidth(LORA_BW);
  LoRa.setCodingRate4(LORA_CR);
  LoRa.setSyncWord(LORA_SYNC);

  Serial.println("Lora Ready. Sensor reading and transmission starting...");

  // Take one reading and send once at boot for icmediate feedback.
  doRead();
  doSend();
  lastReadMs = millis();
  lastSendMs = millis();
}

void loop() {
  unsigned long now = millis();

  // 1. RUTINITAS PEMBACAAN ADAPTIF
  if (now - lastReadMs >= detectInterval(lastStatus)) {
    lastReadMs = now;
    int prevStatus = lastStatus;

    doRead();

    // Pada SETIAP perubahan status -> kirim seketika (hanya jika pembacaan valid)
    if (lastLevel >= 0 && lastStatus != prevStatus) {
      Serial.println("# Status change -> sending now");
      doSend();
      lastSendMs = now;
    }
  }

  // 2. RUTINITAS PENGIRIMAN BERTINGKAT (Time-Driven)
  if (now - lastSendMs >= sendInterval(lastStatus)) {
    lastSendMs = now;
    doSend();
  }
}