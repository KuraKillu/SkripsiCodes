import os
import csv
import time 
from datetime import datetime

# Function to send commands to the CupCarbon simulator engine
def cup(com): print(com, flush=True)

# Fetch the node's ID from CupCarbon
cup("getid")
MY_ID = input().strip()

# =================================================================
# INITIALIZE 4 CSV FILES FOR LOGGING
# =================================================================
CSV_AVG = f"sink_avg_{MY_ID}.csv"
if not os.path.exists(CSV_AVG):
    with open(CSV_AVG, mode='w', newline='') as f:
        csv.writer(f).writerow(["Time", "Average_Water_Level", "Node_List"])

CSV_DATA = f"sink_individual_data_{MY_ID}.csv"
if not os.path.exists(CSV_DATA):
    with open(CSV_DATA, mode='w', newline='') as f:
        csv.writer(f).writerow(["Time", "Node_ID", "Water_Level", "Current_Path"])

CSV_QOS = f"sink_qos_{MY_ID}.csv"
if not os.path.exists(CSV_QOS):
    with open(CSV_QOS, mode='w', newline='') as f:
        csv.writer(f).writerow(["Time", "Node_ID", "Packet_Seq", "Delay_Seconds"])

CSV_ROUTING_TABLE = f"sink_routing_table_{MY_ID}.csv"
if not os.path.exists(CSV_ROUTING_TABLE):
    with open(CSV_ROUTING_TABLE, mode='w', newline='') as f:
        csv.writer(f).writerow(["Time", "Source_Node_ID", "Active_Route", "Hop_Count", "Status"])
# =================================================================

# Memory variables to store the latest state of the network
latest_data = {}
latest_routes = {}
last_seen = {}             # {node_id: waktu (time.time()) data terakhir diterima}

NODE_TIMEOUT = 65          # detik; > 2x interval kirim terlama (30 s) + margin jitter
MONITOR_EVERY = 15         # cetak status umur data tiap 15 TICK (~15 detik)
monitor_counter = 0

SINK_ZONE = int(MY_ID) // 100
alert_timer = 0          
last_status = "NORMAL" 
current_avg = 0.0          

# -----------------------------------------------------------------
# Fungsi bantu: hapus satu node dari seluruh struktur agregasi Sink,
# hitung ulang rata-rata, dan catat ke CSV. Dipakai oleh tiga jalur:
# (1) RERR 4-bagian, (2) paket data lvl=-1, (3) timeout TICK.
# -----------------------------------------------------------------
def purge_node(node_id, reason_label):
    global current_avg, last_status
    t = datetime.now().strftime("%H:%M:%S")
    removed = False

    if node_id in last_seen:
        del last_seen[node_id]
    if node_id in latest_data:
        del latest_data[node_id]
        removed = True
        with open(CSV_DATA, mode='a', newline='') as f:
            csv.writer(f).writerow([t, node_id, reason_label, "-"])
    if node_id in latest_routes:
        del latest_routes[node_id]
        with open(CSV_ROUTING_TABLE, mode='a', newline='') as f:
            csv.writer(f).writerow([t, node_id, "NONE", "-", reason_label])

    if removed:
        # Hitung ulang agar status siaga tidak tertahan oleh data basi
        if len(latest_data) > 0:
            current_avg = sum(latest_data.values()) / len(latest_data)
        else:
            current_avg = 0.0
            last_status = "NORMAL"
        nl = ", ".join(sorted(latest_data.keys())) if latest_data else "-"
        cup(f"print [SINK {MY_ID}] Node {node_id} {reason_label} | Sisa aktif: [{nl}]")
    return removed

cup(f"print SINK id={MY_ID} :: ready to log Data, QoS, and Alerts...")

while True:
    try:
        # cup("read") blocks the script until a radio message or sensor event arrives
        cup("read")
        msg = input().strip()

        # cup("getaction") checks if the user clicked the node in the GUI (returns '1')
        cup("getaction")
        if input().strip() == "1":
            t = datetime.now().strftime("%H:%M:%S")
            cup(f"print [KILL] SINK {MY_ID} clicked. SINK IS DEAD!")
            # cup("visible 0") hides the node from the CupCarbon map
            cup("visible 0") 
            with open(CSV_ROUTING_TABLE, mode='a', newline='') as f:
                csv.writer(f).writerow([t, MY_ID, "SINK DEAD", "-", "OFFLINE"])
            
            # Broadcast Route Error (format 4-bagian: pembawa identitas mati)
            cup(f"send RERR_*_{MY_ID}_{MY_ID} *")
            break # Exit the loop, ending the script

        # =========================================================
        # BLOK TICK: (a) purge timeout, (b) monitor umur data,
        #            (c) pengulangan alarm Siaga 1
        # =========================================================
        if msg == "TICK":
            now = time.time()

            # (a) LAPIS 2 - TIMEOUT: node senyap > NODE_TIMEOUT dihapus
            stale_nodes = [n for n, ts in list(last_seen.items()) if now - ts > NODE_TIMEOUT]
            for n in stale_nodes:
                purge_node(n, "TIMEOUT")

            # (b) MONITOR: bukti terukur isi agregasi + umur data tiap node
            monitor_counter += 1
            if monitor_counter >= MONITOR_EVERY:
                monitor_counter = 0
                if last_seen:
                    ages = ", ".join(f"{n}:{int(now - ts)}s" for n, ts in sorted(last_seen.items()))
                    cup(f"print [MONITOR SINK {MY_ID}] Umur data (batas {NODE_TIMEOUT}s): {ages}")
                else:
                    cup(f"print [MONITOR SINK {MY_ID}] Agregasi kosong")

            # (c) Pengulangan alarm Siaga 1 setiap 10 detik
            if current_avg >= 950:
                alert_timer += 1
                if alert_timer >= 10:
                    alert_timer = 0   
                    # cup("alert ...") shows a blinking warning popup in CupCarbon GUI
                    cup(f"alert [AWAS SIAGA 1] Average Water Level: {current_avg:.1f}mm! Evacuate!")
            continue

        if not msg: continue

        parts = msg.split("_")
        msg_type = parts[0]
        if len(parts) < 3: continue 
        target = parts[1]
        
        # --- STRICT ZONE ISOLATION (LOGICAL SUBNETTING) ---
        try:
            main_id = int(parts[2])
            sender_zone = main_id // 100
            # Ignore completely if the packet is from a different zone
            if sender_zone != SINK_ZONE: continue 
        except Exception: pass
        # --------------------------------------------------

        # =========================================================
        # LAPIS 1 - PROSES RERR
        #   RERR_*_{sender}          (3 bagian) : invalidasi rute;
        #       sender masih hidup -> JANGAN hapus dari agregasi
        #   RERR_*_{sender}_{dead}   (4 bagian) : membawa identitas
        #       node yang mati -> hapus 'dead' dari agregasi
        # Ditangani sebelum filter target karena RERR bertarget "*".
        # =========================================================
        if msg_type == "RERR":
            if len(parts) == 4:
                dead_id = parts[3]
                purge_node(dead_id, "OFFLINE")
            continue

        # Only process RREQ and messages intended for this node
        if msg_type != "RREQ" and target != MY_ID: continue

        # --- PROCESS ROUTE REQUEST (RREQ) ---
        if msg_type == "RREQ" and len(parts) == 5:
            target_sink, searcher_id, req_id, last_sender = parts[1], parts[2], parts[3], parts[4]
            if target_sink == MY_ID:
                # Reply with Route Reply (RREP)
                rrep_msg = f"RREP_{last_sender}_{searcher_id}_{req_id}_{MY_ID}_0_{MY_ID}"
                cup(f"send {rrep_msg} {last_sender}")

        # --- PROCESS INCOMING SENSOR DATA ---
        elif msg_type == "D" and len(parts) >= 7:
            origin = parts[2]
            lvl = parts[3]
            passed_path = parts[4]
            pkt_seq = parts[5]
            t_stamp = parts[6]
            
            full_path = f"{passed_path}-{MY_ID}"
            t = datetime.now().strftime("%H:%M:%S")
            hop_count = len(full_path.split('-')) - 1

            # LAPIS 3 - Paket kematian (lvl = -1): dikirim node yang pamit
            # secara graceful ATAU oleh tetangga sebagai proxy obituary.
            if lvl == "-1":
                purge_node(origin, "OFFLINE")
            else:
                lvl = int(float(lvl))
                latest_data[origin] = lvl
                last_seen[origin] = time.time()

                # Log normal data
                with open(CSV_DATA, mode='a', newline='') as f:
                    csv.writer(f).writerow([t, origin, lvl, full_path])
                
                # Log routing changes only if the path is new or updated
                if origin not in latest_routes or latest_routes[origin] != full_path:
                    latest_routes[origin] = full_path
                    with open(CSV_ROUTING_TABLE, mode='a', newline='') as f:
                        csv.writer(f).writerow([t, origin, full_path, hop_count, "ACTIVE"])
                    cup(f"print [ROUTE UPDATE] Node {origin} -> {full_path}")

                # Calculate End-to-End Delay (QoS Metric)
                try:
                    delay = time.time() - float(t_stamp)
                    with open(CSV_QOS, mode='a', newline='') as f:
                        csv.writer(f).writerow([t, origin, pkt_seq, f"{delay:.4f}"])
                except Exception: pass
            
            # --- CALCULATE AVERAGE & TRIGGER ALERTS ---
            if len(latest_data) > 0:
                nodes = sorted(latest_data.keys())
                current_avg = sum(latest_data.values()) / len(latest_data)
                nl = ", ".join(nodes)
                
                with open(CSV_AVG, mode='a', newline='') as f:
                    csv.writer(f).writerow([t, round(current_avg, 2), nl])
                
                # STATUS LEVELS (KEPT IN INDONESIAN AS REQUESTED)
                if current_avg >= 950: current_status = "SIAGA 1 (AWAS)"
                elif current_avg >= 850: current_status = "SIAGA 2 (SIAGA)"
                elif current_avg >= 750: current_status = "SIAGA 3 (WASPADA)"
                else: current_status = "NORMAL"

                cup(f"print [SINK {MY_ID}] Avg: {current_avg:.1f}mm | Status: {current_status} | Active: [{nl}]")

                # Trigger Siaga 2 Alert ONLY ONCE upon entering the status
                if current_status == "SIAGA 2 (SIAGA)" and last_status != "SIAGA 2 (SIAGA)":
                    cup(f"alert [PERINGATAN SIAGA 2] Rata-rata Air menyentuh {current_avg:.1f}mm! Pintu Air Dibuka!")
                
                # Trigger Siaga 1 Alert immediately, then timer takes over for repetition
                if current_status == "SIAGA 1 (AWAS)" and last_status != "SIAGA 1 (AWAS)":
                    cup(f"alert [PERINGATAN DINI SIAGA 1] Air Kritis {current_avg:.1f}mm! Bunyikan Sirine Wilayah!")
                    alert_timer = 0 

                last_status = current_status
            else:
                current_avg = 0.0
                last_status = "NORMAL"
                cup(f"print [SINK {MY_ID}] ZONE {SINK_ZONE} Avg: 0.0mm | Status: EMPTY")

    except Exception as e: pass