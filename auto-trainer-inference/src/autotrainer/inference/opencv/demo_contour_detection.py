import argparse
from pathlib import Path

import cv2
# import numpy as np
# import matplotlib.pyplot as plt

import sys


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("input_video_path", type=Path)
    parser.add_argument("output_video_path", type=Path)

    args = parser.parse_args()

    cap = cv2.VideoCapture(args.input_video_path)
    if not cap.isOpened():
        print("Error opening video file")
        raise SystemExit(-1)

    backSub = cv2.createBackgroundSubtractorMOG2()
    # backSub = cv2.createBackgroundSubtractorKNN()

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    # w, h = 600, 450

    writer = cv2.VideoWriter()
    writer.open(args.output_video_path,
                cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))

    window_name = "demo output"

    cv2.namedWindow(window_name)
    # cv2.startWindowThread()

    history_list = []
    history_count = 1  # 30 * 1  # fps * duration

    while cap.isOpened():
        if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 0:
            break

        # Capture frame-by-frame
        ret, frame = cap.read()
        if not ret:
            break
        # frame = cv2.resize(frame, (600, 450))

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        history_list.append(gray_frame)
        if len(history_list) <= history_count:
            # fg_mask = backSub.apply(frame)
            continue
        else:
            background = history_list.pop(0)
            fg_mask = cv2.absdiff(background, gray_frame)
        fg_mask[fg_mask < 0.1] = 0

        # Apply background subtraction
        # apply global threshold to remove shadows
        retval, mask_thresh = cv2.threshold(fg_mask,
                                            180, #180,
                                            255,
                                            # cv2.THRESH_TRIANGLE,
                                            cv2.THRESH_BINARY
                                            )

        # set the kernal
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            # cv2.MORPH_RECT,
            (3, 3),
        )
        # Apply erosion
        mask_eroded = cv2.morphologyEx(mask_thresh,
                                       # cv2.MORPH_BLACKHAT,
                                       cv2.MORPH_OPEN, # cv2.MORPH_OPEN,
                                       # cv2.MORPH_CLOSE,
                                       # cv2.MOTION_HOMOGRAPHY,
                                       # cv2.MORPH_GRADIENT,
                                       kernel)

        # frame = mask_eroded

        # Find contours
        contours, hierarchy = cv2.findContours(mask_eroded,  # fg_mask,
                                               cv2.RETR_EXTERNAL,  # cv2.RETR_LIST,  # cv2.RETR_CCOMP,  # cv2.RETR_EXTERNAL,
                                               cv2.CHAIN_APPROX_SIMPLE,
                                               # cv2.CHAIN_APPROX_TC89_L1,
                                               # cv2.CHAIN_APPROX_TC89_KCOS, # cv2.CHAIN_APPROX_SIMPLE,
                                               )
        # print(contours)
        # frame_ct = cv2.drawContours(frame, contours, -1, (0, 255, 0), 1)
        # Display the resulting frame
        # frame = frame_ct
        # cv2.imshow('Frame_final', frame_ct)
        # cv2.waitKey(0)

        min_contour_area = 800  # Define your minimum area threshold
        large_contours = []  # cnt for cnt in contours if cv2.contourArea(cnt) > min_contour_area]
        for cnt in contours:
            a = cv2.contourArea(cnt)
            if a < min_contour_area:
                continue
            large_contours.append((cnt, a))

        # sort by area:
        large_contours = sorted(large_contours, key=lambda t: t[1], reverse=True)

        # frame_out = frame.copy()
        frame_out = cv2.drawContours(frame.copy(), [c[0] for c in large_contours[:4]], -1, (0, 255, 0), 1)
        for idx, (cnt, area) in enumerate(large_contours):
            if idx > 0:
                if area < 0.75 * large_contours[0][1]:
                    break
            x, y, w, h = cv2.boundingRect(cnt)
            frame_out = cv2.rectangle(frame, (x, y), (x + w, y + h),
                                      (255, 0, 0),  # color
                                      1,  # thickness
                                      )
            if idx >= 3:
                break

        # Display the resulting frame
        frame_out_display = cv2.cvtColor(fg_mask, cv2.COLOR_BGR2RGB)
        cv2.imshow(window_name, frame_out_display)
        key = cv2.waitKey(1)
        if key == 27:
            break
        writer.write(frame_out_display)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
