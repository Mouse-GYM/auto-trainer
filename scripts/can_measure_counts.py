
import time
import logging
import datetime

from collections import defaultdict

import pyjerrycan

logger = logging.getLogger(__name__)


def print_counts(per_type, t_now, t_next_refresh, refresh_window, cnt_none, cnt):
    per_dur = t_now - t_next_refresh + refresh_window  # t_now - t_prev_refresh
    cnt_per_sec = cnt / per_dur
    print(f"Total: {cnt_per_sec} msg / s ;;; {datetime.datetime.now().isoformat(timespec='seconds')}")
    print(f"{cnt_none / per_dur} None / s")
    for k, v in per_type.items():  # sorted(per_type.items(), key=lambda i: str(i[0])):
        per_type[k] = v / per_dur
    print("\n".join(f"{k} -> {v:.1f} / s" for k, v in sorted(per_type.items(), key=lambda i: str(i[0]))))
    print()



def main(jc, refresh_window=1):
    t0 = time.perf_counter()
    dur = 3600 * 4
    t_end = t0 + dur
    cnt = 0
    cnt_none = 0
    logger.info("starting")
    prev_none = False
    prev_t_msg = 0
    per_type = defaultdict(int)
    t_next_refresh = t0 + refresh_window
    while True:
        t_now = time.perf_counter()
        if t_now > t_end:
            print("reached t_end")
            break
        if t_now > t_next_refresh:
            print_counts(per_type, t_now, t_next_refresh, refresh_window, cnt_none, cnt)
            cnt = 0
            cnt_none = 0
            per_type = defaultdict(int)
            #for k in per_type:
            #    per_type[k] = 0
            t_next_refresh += refresh_window  #  t_now
        msgs = jc.ReceiveMessages(10, 5)
        if len(msgs) == 0:  # is None:
            cnt_none += 1
            if prev_none:
                pass
            prev_none = True
        else:
            for msg in msgs:
                cnt += 1
                per_type[msg.type] += 1
                prev_t_msg = t_now
                if False and msg.type == pyjerrycan.JerryCANCmdType.SERVO_STATUS and msg.servo_status.motor_id == 2:
                    print(msg.servo_status.motor_id)
                    return msg

    print_counts(per_type, t_now, t_next_refresh, refresh_window, cnt_none, cnt)
    #cnt_per_sec = cnt / refresh_window
    #print(f"Total: {cnt_per_sec} msg / s")
    #print(f"{cnt_none / refresh_window} None / s")
    #for k, v in per_type.items():
    #    per_type[k] = v / refresh_window
    #print("\n".join(f"{k}={v} / s" for k, v in per_type.items()))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    jc = pyjerrycan.JerryCAN()
    jc.Open()
    msg = main(jc)
