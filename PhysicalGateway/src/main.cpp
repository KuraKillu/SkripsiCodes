/*
* ============================================================================
*  GATEWAY NODE FIRMWARE  (ESP32 + LoRa SX1278)
* ============================================================================
*/

#include <Arduino.h>
#include <SPI.h>
#include <LoRa.h>

#define SS    5
#define RST   14
#define DIO0  26

#define LORA_FREQ        433E6
#define LORA_SF          9
#define LORA_BW          125E3
#define LORA_CR          5
#define LORA_SYNC_WORD   0xA5

void setup() {
  Serial.begin(115200);

  while (!Serial);
    Serial.println("Gateway Starting...");

  LoRa.setPins(SS, RST, DIO0);
  if (!LoRa.begin(LORA_FREQ)) {
    Serial.println("ERROR: LoRa failed to start");
    while (1);
  }
  LoRa.setSpreadingFactor(LORA_SF);
  LoRa.setSignalBandwidth(LORA_BW);
  LoRa.setCodingRate4(LORA_CR);
  LoRa.setSyncWord(LORA_SYNC_WORD);

  Serial.println("Gateway Ready. Listening for packets...");
}

void loop() {
  int packetSize = LoRa.parsePacket();
  if (packetSize == 0) return;

  String packets = "";
  while (LoRa.available()) {
    packets += (char)LoRa.read();
  }
  int rssi = LoRa.packetRssi();

  Serial.println(packets);

  Serial.print("# RSSI=");
  Serial.println(rssi);
}
