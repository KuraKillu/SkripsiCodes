import json
import sys
import time
import serial
from paho.mqtt import client as mqtt_client
 
# ----------------------------- CONFIGURATION -------------------------------
SERIAL_PORT = "COM9"        # Change to Gateway port
SERIAL_BAUD = 115200
 
MQTT_HOST   = "broker.hivemq.com"
MQTT_PORT   = 1883
 
PREFIX      = "skripsiSurya2026"
TOPIC_BASE  = f"{PREFIX}/flood/node"   # final: <prefix>/flood/node/<id>
# ---------------------------------------------------------------------------
 
    
def create_mqtt_client():
    # paho 2.x requires specifying the API version; VERSION1 = simple legacy style
    client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION1,
                                client_id="lora-physical-bridge")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client
 
 
def describe(data):
    """Build a readable one-line summary of the JSON without assuming field
    names. Shows id separately, then all other key=value pairs as-is."""
    node_id = data.get("id", "?")
    others = " ".join(
        f"{k}={v}" for k, v in data.items() if k != "id"
    )
    return f"id={node_id} {others}"
 
 
def main():
    print(f"[bridge] Opening serial {SERIAL_PORT} @ {SERIAL_BAUD} ...")
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
    except serial.SerialException as e:
        print(f"[ERROR] Failed to open serial: {e}")
        print("        Make sure the Arduino IDE Serial Monitor is CLOSED")
        print("        (the port can only be used by one application at a time).")
        sys.exit(1)
 
    print(f"[bridge] Connecting to MQTT {MQTT_HOST}:{MQTT_PORT} ...")
    client = create_mqtt_client()
    print(f"[bridge] Publish topic: {TOPIC_BASE}/<id>")
    print("[bridge] Ready. Waiting for packets from LoRa gateway...\n")
 
    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
 
            # Ignore debug lines starting with '#' (RSSI, banner, etc.)
            if line.startswith("#"):
                print(f"[debug] {line}")
                continue
 
            if not line.startswith("{"):
                # Unrecognized lines, display but do not publish
                print(f"[serial] {line}")
                continue
 
            data = json.loads(line)
            node_id = data.get("id")
            if node_id is None:
                print(f"[WARN] JSON has no 'id' field, skipping: {line!r}")
                continue
 
            topic = f"{TOPIC_BASE}/{node_id}"
            payload = json.dumps(data, separators=(",", ":")) # forward the ENTIRE object unchanged
            client.publish(topic, payload, qos=0)
 
            # Debug display shows actual fields, so 'None' never hides a mismatch
            print(f"[MQTT->] {topic}  {describe(data)}")
 
        except json.JSONDecodeError:
            print(f"[WARN] Line is not valid JSON: {line!r}")
        except KeyboardInterrupt:
            print("\n[bridge] Stopped by user.")
            break
        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(1)
 
    client.loop_stop()
    ser.close()
 
 
if __name__ == "__main__":
    main()