import random
import time

# Function to send commands to the CupCarbon simulator engine
def cup(com): print(com, flush=True)

cup("getid")
MY_ID = input().strip() 

# Memory for AODV Routing protocol
routing_table = {}       
reverse_routes = {}        
processed_rreqs = set()    
req_counter = 0            

# Kumpulan ID node mati yang sudah dilaporkan ke sink (proxy obituary),
# agar RERR duplikat tidak memicu laporan berulang.
dead_reported = set()

# Mengacak waktu mulai agar node tidak mengirim bersamaan di detik 0
tick_counter = random.randint(0, 30)

# Penghitung tick total (~detik) sejak awal simulasi, dipakai untuk transisi fase.
# Tidak ikut di-reset oleh logika pengiriman sehingga selalu merekam waktu tempuh.
total_ticks = 0

seq_counter = 0        
recovery_start = 0.0   

if 100 <= int(MY_ID) < 200: main_sink = 100
elif 200 <= int(MY_ID) < 300: main_sink = 200
else: main_sink = 0

cup(f"print RELAY id={MY_ID} :: Ready (Serving ZONE {main_sink} only)...")

while True:
    try:
        cup("read")
        msg = input().strip()
        if not msg: continue

        cup("getaction")
        if input().strip() == "1":
            cup(f"print [KILL] Node {MY_ID} clicked. DEAD!")
            cup("visible 0") 

            # --- GRACEFUL SHUTDOWN (LAPIS 3) ---
            # Jika rute ke sink masih ada, kirim paket pamit lvl=-1 agar sink
            # langsung menghapus node ini dari agregasi tanpa menunggu timeout.
            route_info = routing_table.get(str(main_sink))
            if route_info is not None:
                next_hop = route_info[0]
                seq_counter += 1
                pamit_msg = f"D_{next_hop}_{MY_ID}_-1_{MY_ID}_{seq_counter}_{time.time()}"
                time.sleep(random.uniform(0.01, 0.1))
                cup(f"send {pamit_msg} {next_hop}")
            # ------------------------------------

            # RERR format 4-bagian: RERR_*_{pengirim}_{yang_mati}.
            # Karena pengirim = yang mati, tetangga 1 hop tahu pesan ini
            # didengar LANGSUNG dari node yang sekarat dan dapat bertindak
            # sebagai proxy pelapor ke sink.
            time.sleep(random.uniform(0.01, 0.1))
            cup(f"send RERR_*_{MY_ID}_{MY_ID} *")
            break 

        if msg == "TICK":
            tick_counter += 1
            total_ticks += 1

            # ==========================================================
            # SKENARIO TRANSISI: SIAGA 2 -> SIAGA 1
            #   30 detik pertama : Siaga 2 (850 - 949 mm, < 950)
            #   detik ke-31 dst  : Siaga 1 (>= 950 mm)
            # ==========================================================
            if total_ticks <= 30:
                my_level = random.randint(850, 949)    # Siaga 2
            else:
                my_level = random.randint(950, 1049)   # Siaga 1

            # --- SKEMA ADAPTIF 15 MENIT (30s / 20s / 10s) ---
            if my_level >= 950:
                send_interval = 10  # 10 Detik (Siaga 1)
            elif my_level >= 850:
                send_interval = 20  # 20 Detik (Siaga 2)
            else:
                send_interval = 30  # 30 Detik (Normal / Siaga 3)
            # ------------------------------------------------

            # Label status untuk mempermudah pengamatan transisi di konsol
            if my_level >= 950:   status_txt = "SIAGA 1"
            elif my_level >= 850: status_txt = "SIAGA 2"
            elif my_level >= 750: status_txt = "SIAGA 3"
            else:                 status_txt = "NORMAL"

            if tick_counter >= send_interval:
                tick_counter = 0
                
                route_info = routing_table.get(str(main_sink))

                if route_info is not None:
                    next_hop = route_info[0]
                    seq_counter += 1
                    t_now = time.time()
                    msg_data = f"D_{next_hop}_{MY_ID}_{my_level}_{MY_ID}_{seq_counter}_{t_now}"
                    
                    time.sleep(random.uniform(0.05, 0.2)) 
                    cup(f"send {msg_data} {next_hop}")
                    cup(f"print Node {MY_ID} | Water: {my_level}mm | {status_txt} | Sent via {next_hop}")
                else:
                    cup(f"print Node {MY_ID} | Water: {my_level}mm | {status_txt} | Searching SINK {main_sink}...")

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
        
        # --- STRICT ZONE ISOLATION ---
        try:
            main_id = int(parts[2])
            sender_zone = main_id // 100
            my_zone = int(MY_ID) // 100
            if sender_zone != my_zone: continue 
        except Exception: pass
        # -----------------------------

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
                    recovery_start = 0.0 
            
            if MY_ID != searcher_id and searcher_id in reverse_routes:
                return_path = reverse_routes[searcher_id]
                time.sleep(random.uniform(0.01, 0.1)) 
                cup(f"send RREP_{return_path}_{searcher_id}_{req_id}_{sink_id}_{my_hops_to_sink}_{MY_ID} {return_path}")

        # ==========================================================
        # RERR (3 atau 4 bagian)
        #   RERR_*_{sender}         : invalidasi rute biasa (sender hidup)
        #   RERR_*_{sender}_{dead}  : membawa identitas node yang mati
        # ==========================================================
        elif msg_type == "RERR" and len(parts) in (3, 4):
            broken_node = parts[2]
            dead_origin = parts[3] if len(parts) == 4 else None

            # --- PROXY OBITUARY ---
            # Jika pesan ini didengar LANGSUNG dari node yang mati
            # (sender == dead) dan saya masih punya rute ke sink,
            # laporkan kematiannya ke sink lewat paket D lvl=-1.
            # Ini perlu karena propagasi RERR bergerak MENJAUHI sink.
            if (dead_origin is not None and broken_node == dead_origin
                    and dead_origin != MY_ID and dead_origin not in dead_reported):
                dead_reported.add(dead_origin)
                if len(dead_reported) > 200: dead_reported.clear()
                proxy_route = routing_table.get(str(main_sink))
                if proxy_route is not None and proxy_route[0] != dead_origin:
                    seq_counter += 1
                    obit = f"D_{proxy_route[0]}_{dead_origin}_-1_{MY_ID}_{seq_counter}_{time.time()}"
                    time.sleep(random.uniform(0.01, 0.1))
                    cup(f"send {obit} {proxy_route[0]}")
                    cup(f"print Node {MY_ID} | Melaporkan node {dead_origin} MATI ke SINK {main_sink}")

            # --- PEMELIHARAAN RUTE (perilaku AODV semula) ---
            to_delete = [s_id for s_id, info in routing_table.items() if info[0] == broken_node]
            if len(to_delete) > 0:
                for s_id in to_delete: del routing_table[s_id]
                cup("unmark")
                cup(f"print Node {MY_ID} | Status: Route via {broken_node} is broken!")
                if recovery_start == 0.0: recovery_start = time.time() 
                time.sleep(random.uniform(0.01, 0.1))
                # Propagasi mengawetkan identitas node mati bila ada
                if dead_origin is not None:
                    cup(f"send RERR_*_{MY_ID}_{dead_origin} *")
                else:
                    cup(f"send RERR_*_{MY_ID} *")

        elif msg_type == "D" and len(parts) >= 7:
            origin, lvl, passed_path, pkt_seq, t_stamp = parts[2], parts[3], parts[4], parts[5], parts[6]
            if origin == MY_ID: continue 
            
            # --- DETEKSI ROUTING LOOP ---
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