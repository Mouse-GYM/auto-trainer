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
import numpy as np
import pandas as pd
import os
from scipy.signal import savgol_coeffs, filtfilt
import glob
import pickle
from autotrainer.core.analysis import prepare_jetson_data as prep_jet
import inspect

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

def segment_reaches(session, center_method, available_XYZ):
# session = session_list[0]
    
    results_dict = {
        'pellets_consumed': 0,
        'pellets_presented': 0,
        'successful_reaches': 0,
        'shift_x': 0,
        'shift_y': 0,
        'shift_z': 0
    }
    vid_tag = '.mp4'
    overwrite=True
    frame_rate = 150
    
    debug = False
    
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
        return results_dict
    
    
    data_path_3D = os.path.join(vid_dir, vid_name_base + '_centered3D.h5')
    if not os.path.isfile(data_path_3D):
        print('No 3D dataframe available for %s\n' % vid_name_base)
        return results_dict
    
    df_3d = pd.read_hdf(data_path_3D)
    
    coeffs = get_coeffs()    
    # Calculate distance and speed
    # bodyparts = df_3d.columns.get_level_values('bodyparts').unique()
    bp4speed = ['R_Hand','L_Hand','Pellet']
    for bp in bp4speed:
        dist_vec = np.sqrt(np.diff(df_3d[bp]['x']) ** 2 + np.diff(df_3d[bp]['y']) ** 2 +
                        np.diff(df_3d[bp]['z']) ** 2)  # calculate distance
        dist_vec = np.concatenate(([dist_vec[0]], dist_vec))  # adjust size
        speed_vec = dist_vec * (frame_rate / 1000)  # convert to speed in mm/ms
        
        # Apply filter using filtfilt for smoothing
        speed_vec_filt = filtfilt(coeffs, [1], speed_vec)
        # speed_vec_filt[df_3d[bp]['p'] == 0] = np.nan
        df_3d.loc[:, (bp, 'speed')] = speed_vec_filt
    
    if center_method[0] > 0 and center_method[1] == 'Pellet':
        pellet_home = [0,0,0]
    else:
        pellet_home = []
        for pos in ['x','y','z']:
            filtered_values = df_3d['Pellet'].loc[df_3d['Pellet']['p'] == 1, pos]
            pellet_home.append(filtered_values.median())
    
    #define dist and velo for each reach sequence
    dist_p = np.sqrt((df_3d['Pellet']['x'].values-pellet_home[0])**2+
                         (df_3d['Pellet']['y'].values-pellet_home[1])**2+
                         (df_3d['Pellet']['z'].values-pellet_home[2])**2)
    
    dist_st = np.sqrt((df_3d['Star']['x'].values-df_3d['Triangle']['x'].values)**2+
                         (df_3d['Star']['y'].values-df_3d['Triangle']['y'].values)**2+
                         (df_3d['Star']['z'].values-df_3d['Triangle']['z'].values)**2)
    
    dist_tpX = df_3d['Triangle']['x'].values - df_3d['Pellet']['x'].values
    dist_tpY = df_3d['Triangle']['y'].values - df_3d['Pellet']['y'].values
    dist_tpZ = df_3d['Triangle']['z'].values - df_3d['Pellet']['z'].values
    
    dist_tvpp = np.sqrt((df_3d['Tongue_mid']['x'].values-pellet_home[0])**2+
                            (df_3d['Tongue_mid']['y'].values-pellet_home[1])**2+
                            (df_3d['Tongue_mid']['z'].values-pellet_home[2])**2)
    
    dist_hvpp_R = np.sqrt((df_3d['R_Hand']['x'].values-pellet_home[0])**2+
                            (df_3d['R_Hand']['y'].values-pellet_home[1])**2+
                            (df_3d['R_Hand']['z'].values-pellet_home[2])**2)
    velocity_h_R = np.diff(dist_hvpp_R)*(frame_rate/1000)
    velocity_h_filt_R = filtfilt(coeffs, [1], velocity_h_R)
    Z_dist_h_R = df_3d['R_Hand']['z'].values-pellet_home[2]
    
    dist_hvpp_L = np.sqrt((df_3d['L_Hand']['x'].values-pellet_home[0])**2+
                              (df_3d['L_Hand']['y'].values-pellet_home[1])**2+
                              (df_3d['L_Hand']['z'].values-pellet_home[2])**2)
    velocity_h_L = np.diff(dist_hvpp_L)*(frame_rate/1000)
    velocity_h_filt_L = filtfilt(coeffs, [1], velocity_h_L)
    Z_dist_h_L = df_3d['L_Hand']['z'].values-pellet_home[2]
    
    Z_dist_p = pellet_home[2]-df_3d['Pellet']['z'].values
    Z_dist_p[df_3d['Pellet']['p'] == 0] = np.nan
    Y_dist_p = np.abs(df_3d['Pellet']['y'].values-pellet_home[1])
    
    ############################
    #### Pellet-related variables
    ############################
    # Duration in seconds that a pellet must be near the origin to be considered 'placed'
    time2place = .05
    
    # Minimum distance (mm) a pellet can be from origin and still be 'placed'
    min_dist_from_orig = 2
    
    # Duration in seconds that a pellet must be away from the origin to be considered 'lost'
    time2lost = 0.1
    
    # Minimum duration in seconds between 'lost' and 'placed'
    min_inter_pellet_interval = 5
    
    # Minimum distance (mm) a hand must be from the pellet to call it 'grabbed' when 'lost'
    min_dist_for_grab = 15 # 8
    
    
    ############################
    #### Reach-related variables
    ############################
    # Maximum reach duration (seconds)
    max_reach_dur = 1
    
    # Minimum reach duration (seconds)
    min_reach_dur = 0.1
    
    # The hand must come within this diestance to the pellet (mm)
    min_dist_from_pellet = 15
    
    
    batch_frm = 10
    batch_dist = 5
    position_window = 100
    speed_window = 100
    batch_speed = 5
    batch_stall = 25
    reach_init_speed = -0.025
    reach_dirchange_speed = 0.025
    pellet_drop_speed = 0.275 #0.225
    pellet_drop_dist = -5
    dist_thresh_end = 5
    confidence = 0.9
    
    
    frm_ct = np.shape(df_3d)[0]
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
                
            if count >= time2place*frame_rate:
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
    
    pellet_file_path = os.path.join(vid_dir, vid_name_base + '_pelletHistory.pickle')
    if len(pellet_events):
        for p in range(len(pellet_events)):
            if pellet_events[p]['lost'] >= 0:
                end_search = pellet_events[p]['lost']+position_window
                if end_search >= frm_ct:
                    end_search = frm_ct-1
                # print(np.round((Z_dist_p[pellet_events[p]['placed']:end_search])))
                # print(pellet_events[p]['placed'],end_search)
                if np.nanmin(Z_dist_p[pellet_events[p]['placed']:end_search]) <= pellet_drop_dist:
                    if debug == 2:
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
                    if debug == 2:
                        if pellet_detected == False:
                            print('No pellet detected')
                        else:
                            print('No (additional) reach detected')
                break
            testA = np.sum(df_3d['Pellet']['p'][frame:frame+batch_frm] > confidence)/batch_frm > 0.75 # test if pellet is there 
            if testA:
                pellet_detected = True
            else:
                pellet_detected = False
            
            if search_status == 1:                  # search for a reach initiation
                if pellet_detected == True:
                    testD = np.sum(df_3d['R_Hand']['p'][frame:frame+batch_frm] > confidence)/batch_frm > 0.75 # test if hand is there
                    if testD:
                        testA = Z_dist_h_R[frame] > -4 
                        testB = np.mean(velocity_h_filt_R[frame:frame+batch_speed]) < reach_init_speed
                        
                        if testA and testB: 
                            if debug == 2:
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
                speed_seg = np.asarray(df_3d['Pellet']['speed'][frame:frame + speed_window])
                if np.sum(speed_seg > pellet_drop_speed) > 1:
                    food_was_dropped = True 
                if np.any(Z_dist_p[frame:frame+position_window] < pellet_drop_dist): #food dropped if pellet is too low - 
                    z_dist_indices = np.where(Z_dist_p[frame:frame+position_window] < pellet_drop_dist)
                    testD = np.any(df_3d['Pellet']['p'][frame:frame+position_window].iloc[z_dist_indices] > confidence) 
                    if testD:
                        food_was_dropped = True   
                # print(np.mean(speed_hvh_init[frame:frame+batch_speed]))
                testB = np.mean(speed_hvh_init[frame:frame+batch_speed]) > reach_dirchange_speed
                if testB:
                    if debug == 2:
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
                testE = np.isclose(np.mean(df_3d['R_Hand']['speed'][frame:frame + batch_stall]), 0, atol = 0.025) 
                testF = np.all(dist_hvpp_R[frame:frame + batch_stall] < 6) #4
                speed_seg = np.asarray(df_3d['Pellet']['speed'][frame:frame + speed_window])
                if np.sum(speed_seg > pellet_drop_speed) > 1:
                    # print(np.sum(speed_seg > pellet_drop_speed))
                    food_was_dropped = True 
                    if debug == 2:
                        print(f'DROP: speed drop - line {get_ln()} - frame {frame}')
                        
                if np.any(Z_dist_p[frame:frame+position_window] < pellet_drop_dist): #food dropped if pellet is too low
                    z_dist_indices = np.where(Z_dist_p[frame:frame+position_window] < pellet_drop_dist)
                    testD = np.any(df_3d['Pellet']['p'][frame:frame+position_window].iloc[z_dist_indices] > confidence)
                    if testD:
                        food_was_dropped = True
                        if debug: 
                          print(f'DROP: pellet too low - line {get_ln()} - frame {frame}')
    
                if testA and testC and not food_was_dropped: #and pellet_detected: 
                    if debug == 2:
                        print('reach ended at frame %d!: NEW REACH' % int(frame-1))
                    reach_dict['end'] = int(frame-1)
                    reach_dict['outcome'] = 'missed'
                    # reach_events.append(('reachEnd_missed', int(frame-1)))
                    search_status = 1
                    dist_list.append(dist_hvpp_R[max_frm])
                elif testD and testE and testF: # and not food_was_dropped: 
                    if debug == 2: 
                      print('reach stalled')
                    # reach_events.append(('reachEnd_stalled', int(frame+10)))
                    reach_dict['end'] = int(frame+10)
                    reach_dict['outcome'] = 'stalled'
                    search_status = 1
                    # keep_looking = True
             
                elif testA and testB:
                    pTest = np.mean(dist_p[frame:frame+batch_frm]) < 2 # pellet wasnt dropped and still in original position 
                    if food_was_dropped == True:
                        if debug == 2:
                            print ('reach ended at frame %d!: DROPPED' % int(frame+2))
                        # reach_events.append(('reachEnd_dropped', int(frame+2)))
                        reach_dict['end'] = int(frame+2)
                        reach_dict['outcome'] = 'dropped'
                        lp = find_last_placement(frame+2, pellet_events)
                        pellet_events[lp]['outcome'] = 'dropped'
                        keep_looking = False
                    elif pellet_detected == True and pTest:
                        if debug == 2:
                            print('reach ended at frame %d!: MISSED' % int(frame+2))
                        # reach_events.append(('reachEnd_missed', int(frame+2)))
                        reach_dict['end'] = int(frame+2)
                        reach_dict['outcome'] = 'missed'
                        dist_list.append(dist_hvpp_R[max_frm])
                        frame += 2
                        search_status = 1  
                    else:
                        if debug == 2:
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
                        
                if keep_looking == False:
                    break
            frame += 1
            
    with open(pellet_file_path, 'wb') as f:
        pickle.dump(pellet_events, f)
    
    if debug == 1:
        print(pellet_events)

    shift_x = 0
    shift_y = 0
    shift_z = 0

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
                
    x_off = 0
    y_off = 0
    z_off = 0
    fail_ct = 0
    if len(reach_events):
        for r in reach_events:
            if r['outcome'] == 'missed' or r['outcome'] == 'dropped':
                fail_ct += 1
                x_off += df_3d['R_Hand']['x'][r['max']]
                y_off += df_3d['R_Hand']['y'][r['max']]
                z_off += df_3d['R_Hand']['z'][r['max']]
                
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

    if shift_x < available_XYZ[0,0]: shift_x = 0
    if shift_x > available_XYZ[0,1]: shift_x = 0
    if shift_y < available_XYZ[1,0]: shift_y = 0
    if shift_y > available_XYZ[1,1]: shift_y = 0
    if shift_z < available_XYZ[2,0]: shift_z = 0
    if shift_z > available_XYZ[2,1]: shift_z = 0
    
    if debug == 1:
        print(reach_events)
        
    with open(save_file_path, 'wb') as f:
        pickle.dump(reach_events, f)
    # with open(save_file_path, 'w') as file:
    #     for event in reach_events:
    #         file.write(f"{event[0]}\t{event[1]}\n")
    pellets_presented = len(pellet_events) -1
    
    results_dict['pellets_consumed'] = pellets_consumed
    results_dict['pellets_presented'] = pellets_presented
    results_dict['successful_reaches'] = successful_reaches
    results_dict['shift_x'] = shift_x
    results_dict['shift_y'] = shift_y
    results_dict['shift_z'] = shift_z
    
    return results_dict

def find_last_placement(frmq, pellet_events):
    for i, pe in enumerate(pellet_events[:-1]):
        if i == (len(pellet_events)-2):
            break
        elif pe['placed'] < frmq < pellet_events[i+1]['placed']:
            break
    return i
