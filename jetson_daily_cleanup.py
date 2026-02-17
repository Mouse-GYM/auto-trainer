#!/usr/bin/env python3

import os
import cv2
import glob
import shutil
import sys


def create_movie_from_images(image_folder, output_video_path, frame_rate):
    """
    Create a video from PNG images in a folder, embedding timestamps from filenames.
    
    Parameters:
    - image_folder: Path to the folder containing PNG images.
    - output_video_path: Path to save the output video file.
    - frame_rate: Frame rate for the output video.
    """
    print(f"Reading images from {image_folder}")
    curr_frm = 0
    
    # Get list of PNG files and sort by filename
    image_files = sorted(glob.glob(os.path.join(image_folder, "*.png")))
    if not image_files:
        raise ValueError("No PNG files found in the specified folder.")

    # Get the dimensions of the first image for video properties
    for image_file in image_files:
        sample_image = cv2.imread(image_file)
        if sample_image is not None:
            height, width, _ = sample_image.shape
            break
        elif image_file == image_files[-1]:
            print(f"No valid images from {image_folder}")
            return curr_frm
            
    # Define the codec and initialize VideoWriter
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # For .mp4 files
    video_writer = cv2.VideoWriter(output_video_path, fourcc, frame_rate, (width, height))
    ts_list = []
    for image_file in image_files:
        # Read the image
        frame = cv2.imread(image_file)
        if frame is None:
            continue
        
        # Extract timestamp from filename (assuming format includes hh:mm:ss)
        filename = os.path.basename(image_file)
        # Example assumes timestamp in the format "image_hh-mm-ss.png"
        # timestamp = filename.split('_')[-1].split('.')[0].replace('-', ':')
        timestamp = filename.split('_')[-2]  # Extract hhmmss part
        formatted_timestamp = f"{timestamp[:2]}:{timestamp[2:4]}:{timestamp[4:]}"  # Convert to hh:mm:ss
        millis = filename.split('_')[-1]  # Extract hhmmss part
        ts_list.append((curr_frm,f"{timestamp}_{millis[:-4]}"))
        curr_frm+=1

        
        # Embed timestamp as text in the frame
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.0
        font_color = (255, 255, 255)  # White
        thickness = 2
        position = (10, 30)  # Top-left corner (x, y)
        cv2.putText(frame, formatted_timestamp, position, font, font_scale, font_color, thickness, cv2.LINE_AA)

        # Write the frame to the video
        video_writer.write(frame)

    # Release the video writer
    video_writer.release()
    
    # Write all timestams to .txt file
    
    fileID = os.path.basename(image_folder) + '_timestamps.txt'
    file_path = os.path.join(image_folder, fileID)
    with open(file_path, 'w') as file:
        for ts in ts_list:
            file.write(f"{ts[0]}\t{ts[1]}\n")
            
    print(f"Video saved to {output_video_path}")
    return curr_frm


def validate_and_cleanup(image_folder, video_path, frm_ct):
    """
    Validate the created video and delete PNG files if validation succeeds.
    
    Parameters:
    - video_path: Path to the created video file.
    - image_folder: Path to the folder containing the original PNG files.
    
    Returns:
    - None (Performs validation and file deletion).
    """
    # Count the number of PNG files in the folder
    image_files = sorted(glob.glob(os.path.join(image_folder, "*.png")))
    
    if frm_ct == 0:
        print("No PNG files found in the image folder.")
        return

    # Open the video file
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        if os.path.isfile(video_path):
            print(f"Error: Cannot open video file {video_path}. The file might be corrupt.")
        else:
            print(f"Error: {video_path} does not exist.")
        return

    # Get the total number of frames in the video
    num_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Number of frames in the video: {num_frames}")
    print(f"Number of PNG files: {frm_ct}")

    # Compare the number of frames to the number of PNG files
    if num_frames == frm_ct:
        print("Validation successful: The number of frames matches the number of PNG files.")
        
        # Optional: Confirm that the video is viewable by displaying the first frame
        ret, frame = cap.read()
        # Release the video capture object
        cap.release()
        if not ret:
            print("Error: Unable to read frames from the video. The video might be corrupt.")
            return
        
        # Delete PNG files
        print("Deleting PNG files...")
        for image_file in image_files:
            try:
                os.remove(image_file)
            except Exception as e:
                print(f"Error deleting {image_file}: {e}")
        print("All PNG files deleted successfully.")
    else:
        print("Validation failed: The number of frames does NOT match the number of PNG files.")
    

def find_web_image_directories(start_dir):
    """
    Find all subdirectories under the given starting directory
    that end with '_web_images'.
    
    Parameters:
    - start_dir: The starting directory to search from.
    
    Returns:
    - A list of paths to directories ending with '_web_images'.
    """
    web_image_dirs = []
    
    # Traverse the directory tree
    for root, dirs, files in os.walk(start_dir):
        for directory in dirs:
            if directory.endswith('_web_images'):
                image_folder = os.path.join(root, directory)
                image_files = sorted(glob.glob(os.path.join(image_folder, "*.png")))
                if image_files:
                    web_image_dirs.append(image_folder)
    
    return web_image_dirs


def copy_directory_contents(src_dir, dst_dir):
    """
    Copy the entire contents of one directory into another, skipping files
    or directories that exist in the destination and have the same size.

    Parameters:
        src_dir (str): Path to the source directory.
        dst_dir (str): Path to the destination directory.
    """
    # Ensure the source directory exists
    if not os.path.exists(src_dir):
        raise ValueError(f"Source directory does not exist: {src_dir}")
    
    # Ensure the destination directory exists, or create it
    if not os.path.exists(dst_dir):
        os.makedirs(dst_dir)

    # Copy the contents of the source directory to the destination directory
    for item in os.listdir(src_dir):
        src_item = os.path.join(src_dir, item)
        dst_item = os.path.join(dst_dir, item)

        if os.path.isdir(src_item):
            # Recursively copy directories
            if not os.path.exists(dst_item):
                shutil.copytree(src_item, dst_item)
            else:
                copy_directory_contents(src_item, dst_item)  # Recurse for subdirectories
        else:
            # Skip files that already exist and have the same size
            if os.path.exists(dst_item) and os.path.getsize(src_item) == os.path.getsize(dst_item):
                continue
            # Copy file
            try:
                shutil.copy2(src_item, dst_item)
            except:
                print('Copy2 failed, trying copy')
                try:
                    shutil.copy(src_item, dst_item)
                except:
                    print('Copy failed, trying copyfile')
                    shutil.copyfile(src_item, dst_item)


def main():
    home_dir = os.getenv("HOME")
    start_directory = os.path.join(home_dir, "Documents", "RawDataLocal")
    web_image_dirs = find_web_image_directories(start_directory)
    for image_folder in web_image_dirs:
        output_video_name = os.path.basename(image_folder).replace('_images','_video')+'.mp4'
        output_video_path = os.path.join(image_folder, output_video_name)
        
        frame_rate = 30
        frm_ct = create_movie_from_images(image_folder, output_video_path, frame_rate)
        if frm_ct > 0:
            validate_and_cleanup(image_folder, output_video_path, frm_ct)
            
    dest_parent = '/mnt/isilon/Data/JetsonAutoTrainer/RawDataLocal'
    prev_date_list = [name for name in os.listdir(start_directory)]
    for f in prev_date_list:
        if f < '20241120':
            continue
        src_dir = os.path.join(start_directory,f)
        dst_dir = os.path.join(dest_parent,f)
        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir)
        try:
            copy_directory_contents(src_dir, dst_dir)
        except:
            print('First copy attempt threw an error')
            copy_directory_contents(src_dir, dst_dir)


if __name__ == '__main__':
    sys.exit(main())
