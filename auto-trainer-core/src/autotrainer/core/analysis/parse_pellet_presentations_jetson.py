#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jan 20 12:52:44 2025

@author: agx001
"""

# -*- coding: utf-8 -*-
"""
Created on Tue Jan 16 16:15:29 2024

@author: wrw
"""

import inspect
import os
import glob
import pickle
from typing import Tuple

import numpy as np
import pandas as pd
from scipy.signal import savgol_coeffs, filtfilt

import autotrainer.core.analysis._segment_reaches_f1 as segment_reaches_f11_module
from autotrainer.core import get_verbose_logger
from autotrainer.core.analysis import prepare_jetson_data as prep_jet


logger = get_verbose_logger(__name__)


# print(segment_reaches_f11_module)
segment_reaches_f11 = segment_reaches_f11_module.segment_reaches_f11


def get_coeffs():
    # Savitzky-Golay Smoothing filter parameters
    window_length = 9
    poly_order = 3
    # Obtain Savitzky-Golay filter coefficients
    coeffs = savgol_coeffs(window_length, poly_order)
    
    return coeffs


def get_ln():
    """Prints the current line number."""
    return inspect.currentframe().f_back.f_lineno


def segment_reaches(
    *,
    session,
    center_method,
    available_shift_xyz,
    df_3d,
    overwrite: bool = True,
    debug: int = 0,
):
    results_dict = {
        'pellets_consumed': 0,
        'pellets_presented': 0,
        'successful_reaches': 0,
        'shift_x': 0,
        'shift_y': 0,
        'shift_z': 0
    }
    if df_3d is None:
        return results_dict
    vid_tag = '.mp4'
    frame_rate = 150
    
    # Find video files
    mp4_list = os.path.join(session, '*' + vid_tag)
    videoList = glob.glob(mp4_list)
    
    # Extract relevant video paths in order
    videoOrder = ['left', 'right']
    video_paths = [video for key in videoOrder for video in videoList if key in video]
    if not video_paths:
        print('No Videos found!\n')
        return results_dict
    vid_name_base, vid_dir = prep_jet.get_vid_name_base(video_paths[0])
    
    save_file_path = os.path.join(vid_dir, vid_name_base + '_eventSegmentation.pickle')
    if os.path.isfile(save_file_path) and not overwrite:
        print('Previous analysis found for %s\n' % vid_name_base)
        # TODO: read the file and returns its results dicts..
        return results_dict

    coeffs = get_coeffs()

    dist_p, Z_dist_p, dist_hvpp_R, pellet_events, pellet_home, frames_on_found = segment_reaches_f1(
        df_3d=df_3d,
        frame_rate=frame_rate,
        coeffs=coeffs,
        center_method=center_method,
        debug=debug,
    )

    if debug >= 1:
        print(f"segment_reaches_f1: events={pellet_events}")

    pellets_consumed, pellets_presented, successful_reaches, shift_xyz, reach_events = segment_reaches_f2(
        available_shift_xyz=available_shift_xyz,
        df_3d=df_3d,
        coeffs=coeffs,
        vid_dir=vid_dir,
        vid_name_base=vid_name_base,
        pellet_events=pellet_events,
        pellet_home=pellet_home,
        dist_p=dist_p,
        Z_dist_p=Z_dist_p,
        frame_rate=frame_rate,
        frames_on_found=frames_on_found,
        dist_hvpp_R=dist_hvpp_R,
        debug=debug,
    )

    with open(save_file_path, 'wb') as f:
        pickle.dump(reach_events, f)

    return segment_reaches_f3(
        results_dict=results_dict,
        pellets_consumed=pellets_consumed,
        pellets_presented=pellets_presented,
        successful_reaches=successful_reaches,
        shift_xyz=shift_xyz,
    )


def segment_reaches_f1(
    *,
    df_3d: pd.DataFrame,
    frame_rate: int,
    coeffs: np.ndarray,
    center_method: Tuple[int, str],
    debug: int,
):
    # Calculate distance and speed
    # bodyparts = df_3d.columns.get_level_values('bodyparts').unique()
    bp4speed = ['R_Hand','L_Hand','Pellet']
    for bp in bp4speed:
        df_bp = df_3d[bp]
        dist_vec = np.sqrt(
              np.diff(df_bp['x']) ** 2
            + np.diff(df_bp['y']) ** 2
            + np.diff(df_bp['z']) ** 2
        )  # calculate distance
        dist_vec = np.concatenate(([dist_vec[0]], dist_vec))  # adjust size
        speed_vec = dist_vec * (frame_rate / 1000)  # convert to speed in mm/ms
        
        # Apply filter using filtfilt for smoothing
        speed_vec_filt = filtfilt(coeffs, [1], speed_vec)
        # speed_vec_filt[df_3d[bp]['p'] == 0] = np.nan
        df_3d.loc[:, (bp, 'speed')] = speed_vec_filt

    if center_method[0] > 0 and center_method[1] == 'Pellet':
        pellet_home = [0, 0, 0]
    else:
        # how many frames to use at start for getting pellet home pos:
        n_frames_mean = 50   # todo
        pellet_home = []
        df_3d_pellet = df_3d["Pellet"]
        for pos in ('x', 'y', 'z'):
            # using n_frames_mean first frames where p == 1 :
            ploc = df_3d_pellet.iloc[:n_frames_mean].loc[df_3d_pellet['p'] == 1, pos].median()
            pellet_home.append(ploc)

    pellet_home = (pellet_home[0], pellet_home[1], pellet_home[2])
    logger.verbose("segment_reaches: using pellet_home=%s", pellet_home)

    return segment_reaches_f11(
        df_3d=df_3d,
        frame_rate=frame_rate,
        pellet_home=pellet_home,
        debug=debug,
    )


def segment_reaches_f2(
    *,
    available_shift_xyz,
    df_3d: pd.DataFrame,
    coeffs,
    vid_dir,
    vid_name_base,
    pellet_events,
    pellet_home,
    dist_p,
    Z_dist_p,
    frame_rate,
    frames_on_found,
    dist_hvpp_R,
    debug,
):
    frm_ct = np.shape(df_3d)[0]
    ############################
    #### Reach-related variables
    ############################
    # Maximum reach duration (seconds)
    max_reach_dur = 1

    # Minimum reach duration (seconds)
    min_reach_dur = 0.1

    # The hand must come within this distance to the pellet (mm)
    min_dist_from_pellet = 15

    batch_frm = 10
    batch_dist = 5
    position_window = 100
    speed_window = 100
    batch_speed = 5
    batch_stall = 25
    reach_init_speed = -0.025
    reach_dirchange_speed = 0.025
    pellet_drop_speed = 0.275  # 0.225
    pellet_drop_dist = -5
    dist_thresh_end = 5
    confidence = 0.9

    if len(pellet_events):
        for p in range(len(pellet_events)):
            if pellet_events[p]['lost'] >= 0:
                end_search = pellet_events[p]['lost']+position_window
                if end_search >= frm_ct:
                    end_search = frm_ct-1
                # print(np.round((Z_dist_p[pellet_events[p]['placed']:end_search])))
                # print(pellet_events[p]['placed'],end_search)
                if np.nanmin(Z_dist_p[pellet_events[p]['placed']:end_search]) <= pellet_drop_dist:
                    if debug >= 2:
                        print(f'DROP: Z dist at {get_ln()}')
                    pellet_events[p]['outcome'] = 'dropped'
                
    else:
        print(f"Pellet never found for {vid_name_base}")
    
    pellet_dict = {
        'x': pellet_home[0],
        'y': pellet_home[1],
        'z': pellet_home[2]
    }
    pellet_events.append(pellet_dict)
    
    # ########
    # with open(pellet_file_path, 'wb') as f:
    #     pickle.dump(pellet_events, f)
    # print(pellet_events)
    # return
    # ########

    pellet_data = df_3d['Pellet']
    pellet_p = pellet_data['p']
    pellet_speed = pellet_data['speed']

    r_hand_data = df_3d['R_Hand']
    r_hand_p = r_hand_data['p']
    r_hand_speed = r_hand_data['speed']

    velocity_h_R = np.diff(dist_hvpp_R)*(frame_rate/1000)
    velocity_h_filt_R = filtfilt(coeffs, [1], velocity_h_R)
    Z_dist_h_R = r_hand_data['z'].values - pellet_home[2]

    reach_events = []
    dist_list = []
    max_frm = 0
    
    for frmindex, start_frame in enumerate(frames_on_found):
        
        search_status = 1
        food_was_dropped = False
        frame = start_frame-20 # in case reach begins prior to pellet placement
        pellet_detected = False
        while frame < frm_ct - batch_frm:             # test if we reached the next pellet placement 
            if frmindex < len(frames_on_found)-1 and frame >= frames_on_found[frmindex+1]: 
                if search_status == 1:
                    if debug >= 2:
                        if not pellet_detected:
                            print('No pellet detected')
                        else:
                            print('No (additional) reach detected')
                break
            testA = np.sum(pellet_p[frame:frame+batch_frm] > confidence)/batch_frm > 0.75 # test if pellet is there
            if testA:
                pellet_detected = True
            else:
                pellet_detected = False
            
            if search_status == 1:                  # search for a reach initiation
                if pellet_detected:
                    testD = np.sum(r_hand_p[frame:frame+batch_frm] > confidence)/batch_frm > 0.75 # test if hand is there
                    if testD:
                        testA = Z_dist_h_R[frame] > -4 
                        testB = np.mean(velocity_h_filt_R[frame:frame+batch_speed]) < reach_init_speed
                        
                        if testA and testB: 
                            if debug >= 2:
                                print('reach began at frame %d!' % frame)
                            reach_dict = {
                                'init': frame,
                                'max': -1,
                                'end': -1,
                                'outcome': ''
                            }
                            # reach_events.append(('reachInit', frame))
                            search_status = 2
                            food_was_dropped = False
                            speed_hvh_init = np.diff(dist_hvpp_R - dist_hvpp_R[frame])*(frame_rate/1000)
                            speed_hvh_init = filtfilt(coeffs, [1], speed_hvh_init)
            
            elif search_status == 2:                #search for reach max
                speed_seg = np.asarray(pellet_speed[frame:frame + speed_window])
                if np.sum(speed_seg > pellet_drop_speed) > 1:
                    food_was_dropped = True 
                if np.any(Z_dist_p[frame:frame+position_window] < pellet_drop_dist): #food dropped if pellet is too low - 
                    z_dist_indices = np.where(Z_dist_p[frame:frame+position_window] < pellet_drop_dist)
                    testD = np.any(pellet_p[frame:frame+position_window].iloc[z_dist_indices] > confidence)
                    if testD:
                        food_was_dropped = True   
                # print(np.mean(speed_hvh_init[frame:frame+batch_speed]))
                testB = np.mean(speed_hvh_init[frame:frame+batch_speed]) > reach_dirchange_speed
                if testB:
                    if debug >= 2:
                        print('reach max at frame %d!' % int(frame+3))
                    # reach_events.append(('reachMax', int(frame+3)))
                    reach_dict['max'] = int(frame+3)
                    max_frm = frame+3
                    
                    search_status = 3
                    frame += 3
            
            elif search_status == 3:                # search for reach end 
                keep_looking = True
                # print(np.mean(speed_hvh_init[frame:frame+batch_speed]))
                testA = np.mean(dist_hvpp_R[frame:frame + batch_dist]) > dist_thresh_end  # test if hand is far enough away and moving away from pellet                             
                testB = np.mean(speed_hvh_init[frame:frame+batch_speed]) < reach_dirchange_speed
                testC = np.mean(velocity_h_filt_R[frame:frame+batch_speed]) < reach_init_speed
                testD = np.allclose(np.mean(dist_hvpp_R[frame:frame+batch_stall]), dist_hvpp_R[frame], atol = 2)
                testE = np.isclose(np.mean(r_hand_speed[frame:frame + batch_stall]), 0, atol = 0.025)
                testF = np.all(dist_hvpp_R[frame:frame + batch_stall] < 6) #4
                speed_seg = np.asarray(pellet_speed[frame:frame + speed_window])
                if np.sum(speed_seg > pellet_drop_speed) > 1:
                    # print(np.sum(speed_seg > pellet_drop_speed))
                    food_was_dropped = True 
                    if debug >= 2:
                        print(f'DROP: speed drop - line {get_ln()} - frame {frame}')
                        
                if np.any(Z_dist_p[frame:frame+position_window] < pellet_drop_dist): #food dropped if pellet is too low
                    z_dist_indices = np.where(Z_dist_p[frame:frame+position_window] < pellet_drop_dist)
                    testD = np.any(pellet_p[frame:frame+position_window].iloc[z_dist_indices] > confidence)
                    if testD:
                        food_was_dropped = True
                        if debug: 
                          print(f'DROP: pellet too low - line {get_ln()} - frame {frame}')
    
                if testA and testC and not food_was_dropped: #and pellet_detected: 
                    if debug >= 2:
                        print('reach ended at frame %d!: NEW REACH' % int(frame-1))
                    reach_dict['end'] = int(frame-1)
                    reach_dict['outcome'] = 'missed'
                    # reach_events.append(('reachEnd_missed', int(frame-1)))
                    search_status = 1
                    dist_list.append(dist_hvpp_R[max_frm])

                elif testD and testE and testF: # and not food_was_dropped:
                    if debug >= 2:
                      print('reach stalled')
                    # reach_events.append(('reachEnd_stalled', int(frame+10)))
                    reach_dict['end'] = int(frame+10)
                    reach_dict['outcome'] = 'stalled'
                    search_status = 1
                    # keep_looking = True
             
                elif testA and testB:
                    pTest = np.mean(dist_p[frame:frame+batch_frm]) < 2 # pellet wasnt dropped and still in original position 
                    if food_was_dropped:
                        if debug >= 2:
                            print ('reach ended at frame %d!: DROPPED' % int(frame+2))
                        # reach_events.append(('reachEnd_dropped', int(frame+2)))
                        reach_dict['end'] = int(frame+2)
                        reach_dict['outcome'] = 'dropped'
                        lp = find_last_placement(frame+2, pellet_events)
                        pellet_events[lp]['outcome'] = 'dropped'
                        keep_looking = False
                    elif pellet_detected and pTest:
                        if debug >= 2:
                            print('reach ended at frame %d!: MISSED' % int(frame+2))
                        # reach_events.append(('reachEnd_missed', int(frame+2)))
                        reach_dict['end'] = int(frame+2)
                        reach_dict['outcome'] = 'missed'
                        dist_list.append(dist_hvpp_R[max_frm])
                        frame += 2
                        search_status = 1  
                    else:
                        if debug >= 2:
                            print('reach ended at frame %d!: GRABBED' % int(frame+2)) #alt: pellet position close to hand(within some threshold)
                        # reach_events.append(('reachEnd_grabbed', int(frame+2)))
                        reach_dict['end'] = int(frame+2)
                        reach_dict['outcome'] = 'grabbed'
                        # lp = find_last_placement(frame+2, pellet_events)
                        # pellet_events[lp]['outcome'] = 'eaten'
                        keep_looking = False 
                 
                if reach_dict['end'] > -1:
                    start_query = reach_dict['init']
                    max_query = reach_dict['max']
                    end_query = reach_dict['end']
                    testX = end_query - start_query < min_reach_dur*frame_rate
                    testY = end_query - start_query > max_reach_dur*frame_rate
                    testZ = dist_hvpp_R[max_query] > min_dist_from_pellet
                    if not (testX or testY or testZ):
                        reach_events.append(reach_dict)
                        
                if not keep_looking:
                    break
            frame += 1

    pellet_file_path = os.path.join(vid_dir, vid_name_base + '_pelletHistory.pickle')
    with open(pellet_file_path, 'wb') as f:
        pickle.dump(pellet_events, f)
    
    if debug >= 1:
        print(pellet_events)

    shift_x: float = 0
    shift_y: float = 0
    shift_z: float = 0

    successful_reaches = 0
    pellets_consumed = 0
    if len(pellet_events):
        for p in pellet_events[:-1]:
            if p['outcome'] == 'eaten':
                pellets_consumed += 1
                if p['method'] == 'right_hand':
                    successful_reaches += 1
            if p['method'] == 'tongue':
                shift_x = 1
                shift_z = -1
            elif p['method'] == 'left_hand':
                shift_x = 1
                
    x_off: float = 0
    y_off: float = 0
    z_off: float = 0
    fail_ct = 0
    if len(reach_events):
        for r in reach_events:
            if r['outcome'] == 'missed' or r['outcome'] == 'dropped':
                fail_ct += 1
                x_off += r_hand_data['x'][r['max']]
                y_off += r_hand_data['y'][r['max']]
                z_off += r_hand_data['z'][r['max']]
                
    if fail_ct > 0:
        x_off = x_off/fail_ct
        y_off = y_off/fail_ct
        z_off = z_off/fail_ct
        
        if x_off < 1: # Ideal x is 1.5
            shift_x = -1
        elif x_off > 2:
            shift_x = 1
        if y_off < -3.5: # Ideal y is -3
            shift_y = -1
        elif y_off > -2.5:
            shift_y = 1
        if z_off < -1.5: # Ideal z is -1
            shift_z = -1
        elif z_off > -0.5:
            shift_z = 1

    if not (available_shift_xyz[0, 0] <= shift_x <= available_shift_xyz[0, 1]):
        shift_x = 0
    if not (available_shift_xyz[1, 0] <= shift_y <= available_shift_xyz[1, 1]):
        shift_y = 0
    if not (available_shift_xyz[2, 0] <= shift_y <= available_shift_xyz[2, 1]):
        shift_z = 0

    if debug >= 1:
        print(reach_events)

    pellets_presented = len(pellet_events) -1
    return pellets_consumed, pellets_presented, successful_reaches, (shift_x, shift_y, shift_z), reach_events


def segment_reaches_f3(
    *,
    results_dict,
    pellets_consumed,
    pellets_presented,
    successful_reaches,
    shift_xyz,
):
    # with open(save_file_path, 'w') as file:
    #     for event in reach_events:
    #         file.write(f"{event[0]}\t{event[1]}\n")
    results_dict['pellets_consumed'] = pellets_consumed
    results_dict['pellets_presented'] = pellets_presented
    results_dict['successful_reaches'] = successful_reaches
    results_dict['shift_x'] = shift_xyz[0]
    results_dict['shift_y'] = shift_xyz[1]
    results_dict['shift_z'] = shift_xyz[2]
    
    return results_dict


def find_last_placement(frmq, pellet_events):
    for i, pe in enumerate(pellet_events[:-1]):
        if i == (len(pellet_events)-2):
            break
        elif pe['placed'] < frmq < pellet_events[i+1]['placed']:
            break
    return i
