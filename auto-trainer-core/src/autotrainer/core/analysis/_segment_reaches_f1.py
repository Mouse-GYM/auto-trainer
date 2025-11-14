from typing import Tuple

import numpy as np
import pandas as pd


def segment_reaches_f11(
    *,
    df_3d: pd.DataFrame,
    frame_rate: int,
    pellet_home: Tuple[float, float, float],
    debug: int,
):
    #define dist and velo for each reach sequence
    pellet_xyz_p = df_3d['Pellet']
    pellet_p = pellet_xyz_p['p']
    pellet_x_vals = pellet_xyz_p['x'].values
    pellet_y_vals = pellet_xyz_p['y'].values
    pellet_z_vals = pellet_xyz_p['z'].values
    dist_p = np.sqrt(
          (pellet_x_vals - pellet_home[0]) ** 2
        + (pellet_y_vals - pellet_home[1]) ** 2
        + (pellet_z_vals - pellet_home[2]) ** 2
    )

    triangle_xyz_p = df_3d['Triangle']
    # triangle_p = triangle_xyz_p['p']
    triangle_x_vals = triangle_xyz_p['x'].values
    triangle_y_vals = triangle_xyz_p['y'].values
    triangle_z_vals = triangle_xyz_p['z'].values
    star_xyz_p = df_3d['Star']
    # star_p = star_xyz_p['p']
    dist_st = np.sqrt((star_xyz_p['x'].values - triangle_x_vals)**2+
                         (star_xyz_p['y'].values - triangle_y_vals)**2+
                         (star_xyz_p['z'].values - triangle_z_vals)**2)

    dist_tpX = triangle_x_vals - pellet_x_vals
    dist_tpY = triangle_y_vals - pellet_y_vals
    dist_tpZ = triangle_z_vals - pellet_z_vals

    tongue_mid_xyz_p = df_3d['Tongue_mid']
    tongue_mid_p = tongue_mid_xyz_p['p']
    dist_tvpp = np.sqrt((tongue_mid_xyz_p['x'].values-pellet_home[0])**2+
                            (tongue_mid_xyz_p['y'].values-pellet_home[1])**2+
                            (tongue_mid_xyz_p['z'].values-pellet_home[2])**2)

    r_hand_xyz_p = df_3d['R_Hand']
    r_hand_p = r_hand_xyz_p['p']
    dist_hvpp_R = np.sqrt((r_hand_xyz_p['x'].values-pellet_home[0])**2+
                            (r_hand_xyz_p['y'].values-pellet_home[1])**2+
                            (r_hand_xyz_p['z'].values-pellet_home[2])**2)

    l_hand_xyz_p = df_3d['L_Hand']
    l_hand_p = l_hand_xyz_p['p']
    dist_hvpp_L = np.sqrt((l_hand_xyz_p['x'].values-pellet_home[0])**2+
                              (l_hand_xyz_p['y'].values-pellet_home[1])**2+
                              (l_hand_xyz_p['z'].values-pellet_home[2])**2)
    # velocity_h_L = np.diff(dist_hvpp_L)*(frame_rate/1000)
    # velocity_h_filt_L = filtfilt(coeffs, [1], velocity_h_L)
    # Z_dist_h_L = df_3d['L_Hand']['z'].values-pellet_home[2]

    Z_dist_p = pellet_home[2] - pellet_z_vals
    Z_dist_p[pellet_p == 0] = np.nan
    # Y_dist_p = np.abs(df_3d['Pellet']['y'].values-pellet_home[1])

    ############################
    #### Pellet-related variables
    ############################
    # Duration in seconds that a pellet must be near the origin to be considered 'placed'
    time2place = .05
    n_frames_2_place = time2place * frame_rate

    # Minimum distance (mm) a pellet can be from origin and still be 'placed'
    min_dist_from_orig = 2

    # Duration in seconds that a pellet must be away from the origin to be considered 'lost'
    time2lost = 0.1

    # Minimum duration in seconds between 'lost' and 'placed'
    min_inter_pellet_interval = 5

    # Minimum distance (mm) a hand must be from the pellet to call it 'grabbed' when 'lost'
    min_dist_for_grab = 15 # 8

    frames_on_found = []
    frames_on_lost = []
    frm_counter = -1
    frame_at_count_begin = 0
    count = 0
    pellet_state = 0 # 0 is lost, 1 is placed
    pellet_events = []
    for dp, st, tpX, tpY, tpZ, pp in zip(dist_p, dist_st, dist_tpX, dist_tpY, dist_tpZ, pellet_p):
        frm_counter += 1
        # if p == 1:
        #     print(f"{p_dist} - {frm_counter}")
        if pellet_state == 0: # Searching for placement
            testA = dp <= min_dist_from_orig
            testB = pp == 1 # is the pellet detected in frame
            testC = st > 12 or np.isnan(st) # was the cover open or not installed?
            testDx = (2 < tpX < 4.5) and not np.isnan(tpX)
            testDy = (1 < tpY < 5) and not np.isnan(tpY)
            testDz = (1.5 < tpZ < 4) and not np.isnan(tpZ)
            testD = testDx and testDy and testDz # was the pellet a correct distance from the triangle?

            if testA and testB and testC and testD:
                count += 1
            else:
                count = 0
                frame_at_count_begin = frm_counter

            if count >= n_frames_2_place:
                pellet_dict = {
                    'placed': frame_at_count_begin,
                    'lost': -1,
                    'method': 'none',
                    'outcome': 'none'
                }
                pellet_events.append(pellet_dict)
                frames_on_found.append(frame_at_count_begin)
                pellet_state = 1

        elif pellet_state == 1: # Searching for pellet lost
            if dp > min_dist_from_orig or pp == 0:
                count += 1
            else:
                count = 0
                frame_at_count_begin = frm_counter

            if count >= time2lost*frame_rate:
                frames_on_lost.append(frame_at_count_begin)
                pellet_dict['lost'] = frame_at_count_begin
                right_test = dist_hvpp_R[frame_at_count_begin] < min_dist_for_grab
                right_test = right_test and r_hand_p[frame_at_count_begin] == 1
                left_test = dist_hvpp_L[frame_at_count_begin] < min_dist_for_grab
                left_test = left_test and l_hand_p[frame_at_count_begin] == 1
                tongue_test = tongue_mid_p[frame_at_count_begin] == 1
                RVL_test = dist_hvpp_R[frame_at_count_begin] < dist_hvpp_L[frame_at_count_begin]
                TVR_test = dist_tvpp[frame_at_count_begin] < dist_hvpp_L[frame_at_count_begin]
                TVL_test = dist_tvpp[frame_at_count_begin] < dist_hvpp_R[frame_at_count_begin]
                pellet_dict['outcome'] = 'eaten'
                if TVR_test and TVL_test and tongue_test:
                    pellet_dict['method'] = 'tongue'
                elif RVL_test and right_test:
                    pellet_dict['method'] = 'right_hand'
                elif not RVL_test and left_test:
                    pellet_dict['method'] = 'left_hand'
                else:
                    pellet_dict['method'] = 'other'
                    pellet_dict['outcome'] = 'dropped'
                if debug >= 1:
                    print(f"Right hand : {dist_hvpp_R[frame_at_count_begin]} at {frame_at_count_begin}")
                    print(f"Left hand : {dist_hvpp_L[frame_at_count_begin]}")
                    print(f"Tongue : {dist_tvpp[frame_at_count_begin]}")
                    print(f"R/L/T conf : {r_hand_p[frame_at_count_begin]}/{l_hand_p[frame_at_count_begin]}/{tongue_mid_p[frame_at_count_begin]}")
                pellet_events[-1] = pellet_dict
                pellet_state = 2
        elif pellet_state == 2: # Waiting minimum inter-pellet interval
            count += 1
            if count >= min_inter_pellet_interval*frame_rate:
                pellet_state = 0
                count = 0
    # end big for
    return dist_p, Z_dist_p, dist_hvpp_R, pellet_events, pellet_home, frames_on_found
