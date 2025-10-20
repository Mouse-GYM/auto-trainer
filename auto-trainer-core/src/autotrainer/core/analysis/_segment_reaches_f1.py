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
    pellet_x_vals = df_3d['Pellet']['x'].values
    pellet_y_vals = df_3d['Pellet']['y'].values
    pellet_z_vals = df_3d['Pellet']['z'].values
    dist_p = np.sqrt((pellet_x_vals - pellet_home[0])**2+
                         (pellet_y_vals - pellet_home[1])**2+
                         (pellet_z_vals - pellet_home[2])**2)

    triangle_x_vals = df_3d['Triangle']['x'].values
    triangle_y_vals = df_3d['Triangle']['y'].values
    triangle_z_vals = df_3d['Triangle']['z'].values
    dist_st = np.sqrt((df_3d['Star']['x'].values - triangle_x_vals)**2+
                         (df_3d['Star']['y'].values - triangle_y_vals)**2+
                         (df_3d['Star']['z'].values - triangle_z_vals)**2)

    dist_tpX = triangle_x_vals - pellet_x_vals
    dist_tpY = triangle_y_vals - pellet_y_vals
    dist_tpZ = triangle_z_vals - pellet_z_vals

    dist_tvpp = np.sqrt((df_3d['Tongue_mid']['x'].values-pellet_home[0])**2+
                            (df_3d['Tongue_mid']['y'].values-pellet_home[1])**2+
                            (df_3d['Tongue_mid']['z'].values-pellet_home[2])**2)

    dist_hvpp_R = np.sqrt((df_3d['R_Hand']['x'].values-pellet_home[0])**2+
                            (df_3d['R_Hand']['y'].values-pellet_home[1])**2+
                            (df_3d['R_Hand']['z'].values-pellet_home[2])**2)

    dist_hvpp_L = np.sqrt((df_3d['L_Hand']['x'].values-pellet_home[0])**2+
                              (df_3d['L_Hand']['y'].values-pellet_home[1])**2+
                              (df_3d['L_Hand']['z'].values-pellet_home[2])**2)
    # velocity_h_L = np.diff(dist_hvpp_L)*(frame_rate/1000)
    # velocity_h_filt_L = filtfilt(coeffs, [1], velocity_h_L)
    # Z_dist_h_L = df_3d['L_Hand']['z'].values-pellet_home[2]

    Z_dist_p = pellet_home[2] - pellet_z_vals
    Z_dist_p[df_3d['Pellet']['p'] == 0] = np.nan
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
    for dp, st, tpX, tpY, tpZ, pp in zip(dist_p, dist_st, dist_tpX, dist_tpY, dist_tpZ, df_3d['Pellet']['p']):
        frm_counter += 1
        # if p == 1:
        #     print(f"{p_dist} - {frm_counter}")
        if pellet_state == 0: # Searching for placement
            testA = dp <= min_dist_from_orig
            testB = pp == 1 # is the pellet detected in frame
            testC = st > 12 or np.isnan(st) # was the cover open or not installed?
            testDx = (3.5 < tpX < 4.5) and not np.isnan(tpX)
            testDy = (1 < tpY < 5) and not np.isnan(tpY)
            testDz = (3 < tpZ < 4) and not np.isnan(tpZ)
            testD = testDx and testDy and testDz # was the pellet a correct distance from the triangle?
            # x 3.5 : 4.5
            # y 1 : 5
            # z 3 : 4

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
                right_test = dist_hvpp_R[frames_on_lost[-1]] < min_dist_for_grab
                right_test = right_test and df_3d['R_Hand']['p'][frames_on_lost[-1]] == 1
                left_test = dist_hvpp_L[frames_on_lost[-1]] < min_dist_for_grab
                left_test = left_test and df_3d['L_Hand']['p'][frames_on_lost[-1]] == 1
                tongue_test = df_3d['Tongue_mid']['p'][frames_on_lost[-1]] == 1
                RVL_test = dist_hvpp_R[frames_on_lost[-1]] < dist_hvpp_L[frames_on_lost[-1]]
                TVR_test = dist_tvpp[frames_on_lost[-1]] < dist_hvpp_L[frames_on_lost[-1]]
                TVL_test = dist_tvpp[frames_on_lost[-1]] < dist_hvpp_R[frames_on_lost[-1]]
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
                if debug == 1:
                    print(f"Right hand : {dist_hvpp_R[frames_on_lost[-1]]} at {frames_on_lost[-1]}")
                    print(f"Left hand : {dist_hvpp_L[frames_on_lost[-1]]}")
                    print(f"Tongue : {dist_tvpp[frames_on_lost[-1]]}")
                    print(f"R/L/T conf : {df_3d['R_Hand']['p'][frames_on_lost[-1]]}/{df_3d['L_Hand']['p'][frames_on_lost[-1]]}/{df_3d['Tongue_mid']['p'][frames_on_lost[-1]]}")
                pellet_events[-1] = pellet_dict
                pellet_state = 2
        elif pellet_state == 2: # Waiting minimum inter-pellet interval
            count += 1
            if count >= min_inter_pellet_interval*frame_rate:
                pellet_state = 0
                count = 0
    # end big for
    return dist_p, Z_dist_p, dist_hvpp_R, pellet_events, pellet_home, frames_on_found
