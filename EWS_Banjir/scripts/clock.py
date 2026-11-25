# =================================================================
# CLOCK.PY
#
# Functions as a "heartbeat" node for waking up other node in 
# CupCarbon. 
# 
# Used because cup("read") is blocking
# =================================================================

import time

def cup(com):
    print(com, flush=True)

cup("getid")
MY_ID = input().strip()

cup("print [CLOCK] Memulai detak global...")

while True:
    cup("send TICK *")
    time.sleep(1.0)