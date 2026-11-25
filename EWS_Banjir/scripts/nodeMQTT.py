import json
import random
import time
import csv
import os
from datetime import datetime
from paho.mqtt import client as mqtt_client

def cup(com): print(com, flush=True)

cup("getid")
MY_ID = input().strip()

CLIENT_ID = "flood-src-aodv-" + MY_ID
BROKER    = "broker.hivemq.com"
PORT      = 1883
TOPIC     = "skripsiSurya2026/flood/node/" + MY_ID

routing_table = {}
reverse_routes = {}
processed_rreqs = set()
req_counter = 0

tick_counter = random.randint(0, 30)
# === QoS ADDITION: state ditambah phys_seq & recv_ts (dari ESP32/bridge.py) ===
state = {"origin": None, "level": None, "have": False, "phys_seq": None, "recv_ts": None}

seq_counter = 0
recovery_start = 0.0

# Penemuan sink otomatis sesuai id: sink zona = (id // 100) * 100.
# (Enumerasi multi-zona if/elif DIHAPUS -- fokus intra-zona, satu zona.)
main_sink = (int(MY_ID) // 100) * 100

# === QoS ADDITION: Network Recovery Time (NRT) dicatat ke CSV ===
# Sebelumnya NRT hanya muncul lewat cup("print [QOS-RECOVERY] ...") di konsol
# GUI CupCarbon, yang berarti pengumpulan datanya bergantung pada screenshot
# manual. Ini rapuh untuk 194 event re-route yang sudah direkap di Lampiran --
# dengan CSV, semua event bisa diagregasi otomatis tanpa baca satu-satu dari
# tangkapan layar.
CSV_RECOVERY = f"node_recovery_{MY_ID}.csv"
if not os.path.exists(CSV_RECOVERY):
    with open(CSV_RECOVERY, mode='w', newline='') as f:
        csv.writer(f).writerow(["Time", "Node_ID", "Recovery_Seconds"])

def connect_mqtt():
    def on_connect(client, userdata, flags, rc, *args): pass
    try: client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)
    except AttributeError: client = mqtt_client.Client(CLIENT_ID)
    client.on_connect = on_connect
    client.connect(BROKER, PORT, keepalive=60)
    return client

def subscribe(client):
    def on_message(client, userdata, msg):
        raw = msg.payload.decode("utf-8", "ignore").strip()
        try:
            d = json.loads(raw)
            if "id" in d and "level" in d:
                state["origin"] = str(d["id"])
                state["level"] = str(int(float(d["level"])))
                state["have"] = True
                # === QoS ADDITION ===
                # Ambil nomor urut ASLI dari ESP32 ("seq" di payload JSON firmware
                # sensor) dan timestamp penerimaan di bridge.py ("bridge_rx_ts",
                # ditambahkan di bridge.py -- lihat file terpisah). Kalau field ini
                # tidak ada (mis. skrip dites tanpa bridge.py yang sudah dimodifikasi),
                # fallback ke None / waktu lokal supaya kode tetap jalan.
                state["phys_seq"] = d.get("seq", d.get("phys_seq"))
                state["recv_ts"] = d.get("bridge_rx_ts", time.time())
        except Exception: pass
    client.subscribe(TOPIC)
    client.on_message = on_message

client = connect_mqtt()
subscribe(client)

cup(f"print MQTT NODE id={MY_ID} :: Ready (Serving ZONE {main_sink} only)...")

while True:
    try:
        client.loop(timeout=0.05)

        cup("read")
        msg = input().strip()
        if not msg: continue

        if msg == "TICK":
            tick_counter += 1
            if state["have"]:

                # --- SKEMA ADAPTIF 15 MENIT (30s / 20s / 10s) ---
                current_level = int(state["level"])
                if current_level >= 950:
                    send_interval = 10  # 10 Detik
                elif current_level >= 850:
                    send_interval = 20  # 20 Detik
                elif current_level == -1:
                    send_interval = 1   # Segera mati
                else:
                    send_interval = 30  # 30 Detik
                # ------------------------------------------------

                if tick_counter >= send_interval:
                    tick_counter = 0
                    route_info = routing_table.get(str(main_sink))

                    if state["level"] == "-1":
                        time.sleep(random.uniform(0.01, 0.1))
                        cup(f"send RERR_*_{MY_ID} *")
                        cup(f"print [KILL] Node DEAD due to MQTT message!")
                        cup("visible 0")
                        client.disconnect()
                        break

                    if route_info is not None:
                        next_hop = route_info[0]

                        # === QoS ADDITION ===
                        # Pakai seq FISIK dari ESP32 kalau ada, supaya packet loss
                        # bisa dideteksi sink dari ujung ke ujung (termasuk hop
                        # LoRa sensor->gateway dan gateway->bridge->MQTT). Kalau
                        # tidak ada (mode uji tanpa hardware fisik), fallback ke
                        # counter lokal seperti semula.
                        if state.get("phys_seq") is not None:
                            pkt_seq = state["phys_seq"]
                        else:
                            seq_counter += 1
                            pkt_seq = seq_counter

                        # === QoS ADDITION ===
                        # t0 dipakai adalah waktu paket MASUK ke mesh CupCarbon
                        # (recv_ts, dicatat saat MQTT message diterima / saat
                        # bridge.py menerima dari serial), BUKAN waktu baru
                        # dibuat di titik ini. Ini menyamakan definisi delay
                        # dengan node simulasi murni (nodeSensorNormal.py), yaitu
                        # "delay forwarding di dalam mesh", bukan delay sensor
                        # fisik -> sink (yang TIDAK bisa diukur akurat tanpa
                        # sinkronisasi jam ESP32).
                        t_now = state.get("recv_ts") or time.time()

                        msg_data = f"D_{next_hop}_{state['origin']}_{state['level']}_{MY_ID}_{pkt_seq}_{t_now}"

                        time.sleep(random.uniform(0.05, 0.2))
                        cup(f"send {msg_data} {next_hop}")
                        cup(f"print MQTT Node {MY_ID} | Water: {state['level']}mm | Status: Sent via {next_hop}")
                    else:
                        cup(f"print MQTT Node {MY_ID} | Water: {state['level']}mm | Status: Searching SINK {main_sink}...")

                        req_counter += 1
                        req_id = f"{MY_ID}-{req_counter}"
                        processed_rreqs.add(req_id)

                        time.sleep(random.uniform(0.05, 0.3))
                        cup(f"send RREQ_{main_sink}_{MY_ID}_{req_id}_{MY_ID} *")
                        cup("unmark")

                        tick_counter = -random.randint(2, 6)
            continue

        parts = msg.split("_")
        msg_type = parts[0]
        if len(parts) < 3: continue
        target = parts[1]

        # (Blok isolasi zona DIHAPUS: fokus intra-zona, satu zona saja.)

        if msg_type != "RREQ" and msg_type != "RERR" and target != "*" and target != MY_ID: continue

        if msg_type == "RREQ" and len(parts) == 5:
            target_sink, searcher_id, req_id, last_sender = parts[1], parts[2], parts[3], parts[4]
            if target_sink != str(main_sink): continue

            if req_id not in processed_rreqs:
                processed_rreqs.add(req_id)
                if len(processed_rreqs) > 500: processed_rreqs.clear()
                reverse_routes[searcher_id] = last_sender

                route_info = routing_table.get(target_sink)

                time.sleep(random.uniform(0.01, 0.1))
                if route_info is not None and route_info[0] != searcher_id and route_info[0] != last_sender:
                    my_hops = route_info[1]
                    cup(f"send RREP_{last_sender}_{searcher_id}_{req_id}_{target_sink}_{my_hops}_{MY_ID} {last_sender}")
                else:
                    cup(f"send RREQ_{target_sink}_{searcher_id}_{req_id}_{MY_ID} *")

        elif msg_type == "RREP" and len(parts) == 7:
            searcher_id, req_id, sink_id, hop_count, last_sender = parts[2], parts[3], parts[4], int(parts[5]), parts[6]
            my_hops_to_sink = hop_count + 1
            cur = routing_table.get(sink_id)

            if cur is None or my_hops_to_sink < cur[1]:
                routing_table[sink_id] = (last_sender, my_hops_to_sink)
                cup("mark")
                if recovery_start > 0:
                    rec_time = time.time() - recovery_start
                    cup(f"print [QOS-RECOVERY] Node {MY_ID} acquired new route: {rec_time:.2f} seconds!")
                    # === QoS ADDITION: simpan NRT ke CSV, tidak hanya console ===
                    with open(CSV_RECOVERY, mode='a', newline='') as f:
                        csv.writer(f).writerow([datetime.now().strftime("%H:%M:%S"), MY_ID, f"{rec_time:.2f}"])
                    recovery_start = 0.0

            if MY_ID != searcher_id and searcher_id in reverse_routes:
                return_path = reverse_routes[searcher_id]
                time.sleep(random.uniform(0.01, 0.1))
                cup(f"send RREP_{return_path}_{searcher_id}_{req_id}_{sink_id}_{my_hops_to_sink}_{MY_ID} {return_path}")

        elif msg_type == "RERR" and len(parts) == 3:
            broken_node = parts[2]
            to_delete = [s_id for s_id, info in routing_table.items() if info[0] == broken_node]
            if len(to_delete) > 0:
                for s_id in to_delete: del routing_table[s_id]
                cup("unmark")
                cup(f"print MQTT Node {MY_ID} | Status: Route via {broken_node} is broken!")
                if recovery_start == 0.0: recovery_start = time.time()
                time.sleep(random.uniform(0.01, 0.1))
                cup(f"send RERR_*_{MY_ID} *")

        elif msg_type == "D" and len(parts) >= 7:
            origin, lvl, passed_path, pkt_seq, t_stamp = parts[2], parts[3], parts[4], parts[5], parts[6]
            if origin == MY_ID or (state.get("origin") and origin == state["origin"]): continue

            if MY_ID in passed_path.split('-'):
                routing_table.clear()
                cup("unmark")
                if recovery_start == 0.0: recovery_start = time.time()
                time.sleep(random.uniform(0.01, 0.1))
                cup(f"send RERR_*_{MY_ID} *")
                continue

            route_info = routing_table.get(str(main_sink))
            next_hop = route_info[0] if route_info is not None else None

            time.sleep(random.uniform(0.02, 0.15))
            if next_hop is not None:
                new_path = f"{passed_path}-{MY_ID}"
                fwd_msg = f"D_{next_hop}_{origin}_{lvl}_{new_path}_{pkt_seq}_{t_stamp}"
                cup(f"send {fwd_msg} {next_hop}")
            else:
                cup(f"send RERR_*_{MY_ID} *")
                cup("unmark")
                if recovery_start == 0.0: recovery_start = time.time()

    except Exception as e: pass