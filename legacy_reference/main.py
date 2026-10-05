import cv2
import numpy as np
import time
from collections import deque
import os
import redis
import logging
import configparser
# logging.basicConfig(level=logging.CRITICAL)  # Configure logging level
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
redis_host = os.environ.get("REDIS_HOST", "localhost")
r = None

try:
    r = redis.Redis(host=redis_host, port=6379, db=0)
except Exception as e:
    logging.critical("Error connecting to Redis: %s", e)

if r is None:
    raise ConnectionError("Redis connection unavailable. Please check your Redis setup.")

def load_config(config_file='config.ini'):
    config = configparser.ConfigParser()
    try:
        config.read(config_file)
        if not config.sections():
            logging.critical("Error: No sections found in the configuration file.")
            return None

        camera_config = config['camera']
        settings_config = config['settings']
        roi_config = config['roi']
        
        # Parse ROI points
        roi_points = list(map(int, roi_config.get('points').split(',')))
        roi_pts = np.array(roi_points, np.int32).reshape((-1, 2))

        # Return the configurations as a dictionary
        config_data = {
            'username': camera_config.get('username'),
            'password': camera_config.get('password'),
            'camera_ip': camera_config.get('camera_ip'),
            'port': camera_config.get('port'),
            'channel': camera_config.get('channel'),
            'subtype': camera_config.get('subtype'),
            'threshold': settings_config.getint('threshold'),
            'detect_frame': settings_config.getint('detect_frame'),
            'roi_pts': roi_pts
        }
        
        logging.info("Configuration loaded successfully.")
        return config_data

    except Exception as e:
        logging.critical(f"Error loading configuration: {e}")
        return None

def get_queue():
    try:
        order = r.rpop('CTRL').decode('UTF-8')
        if (order != None):
            return True, order
        else:
            return False, ''
    except Exception as e:
        # logging.critical("Order Empty")
        return False, ''

def put_response( status):
    try:
        # status = 'S0', 'E0', 'E1' , 'E2', 'E3', 'E4'  :: ('S0' : success) , ('E0' : no drop"47") , ('>
        item = r.lpush('CAMERA', status)
        return True
    except Exception as e:
        logging.critical("redis error")
        return False

# Function to calculate frame difference in the specified ROI
def frame_difference(frame1, frame2, roi_pts):
    try:
        mask1 = np.zeros(frame1.shape[:2], dtype=np.uint8)
        mask2 = np.zeros(frame2.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask1, [roi_pts], 255)
        cv2.fillPoly(mask2, [roi_pts], 255)
        roi_frame1 = cv2.bitwise_and(frame1, frame1, mask=mask1)
        roi_frame2 = cv2.bitwise_and(frame2, frame2, mask=mask2)
        diff = cv2.absdiff(roi_frame1, roi_frame2)
        gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray_diff, 30, 255, cv2.THRESH_BINARY)
        return np.sum(thresh)
    except Exception as e:
        logging.critical("Error calculating frame difference: %s", e)
        return 0

# Function to set up video capture and seek to start frame
def setup_video_capture(video_path):
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logging.critical("Error: Could not open video stream.")
            return None
        return cap
    except Exception as e:
        logging.critical("Error setting up video capture: %s", e)
        return None




# Main function to initialize parameters and start detection
def main():
    # video_path = 0
    config = load_config()
    if config:
        username = config['username']
        password = config['password']
        camera_ip = config['camera_ip']
        port = config['port']
        channel = config['channel']
        subtype = config['subtype']
        threshold = config['threshold']
        detect_frame = config['detect_frame']
        roi_pts = config['roi_pts']
    rtsp_url = f"rtsp://{username}:{password}@{camera_ip}:{port}/cam/realmonitor?channel={channel}&subtype={subtype}"

    try:
        while True :
            try:
                get_q_sta, order = get_queue()
                # logging.info("Version 3 ")
                if order == 'START' :
                    logging.info("GET QUEUE")
                    order = None
                    cap = setup_video_capture(rtsp_url)
                    
                    if cap == None :
                        continue

                    start_time = time.time()
                    count_detection = 0
                    ret = None

                    while((time.time()-start_time) < 300):
                        get_q_sta, order = get_queue()
                        # time.sleep(0.1) # time
                        if (order == 'STOP'):
                            order = None
                            break

                        retries = 5
                        while ret == None and retries > 0:
                            ret, frame = cap.read()

                            retries -= 1
                            first_frame = frame
                        if not ret:
                            logging.critical("Error: Unable to retrieve frames after retries.")
                            break


                        ret, frame = cap.read()
                        if not ret:
                            break
                        change = frame_difference(first_frame, frame, roi_pts)
                        # logging.info("Change value: %d", change)
                        if change > threshold:
                            count_detection += 1
                            
                            logging.info("Item drop detected : %d", count_detection)

                        if count_detection >= detect_frame :
                            filename = f"frame_lasted.jpg"
                            cv2.imwrite(filename, frame)
                            put_response('S0')
                            logging.info("Response 'S0' sent to Redis.")
                            # print("Put Response")
                            order = None
                            break
                        else:
                            pass
                    cap.release()

                time.sleep(0.5)
            except Exception as e:
                logging.critical("Error in main loop: %s", e)
    finally:
        if cap:
            cap.release()
        logging.info("Video capture released.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.critical("Unhandled exception: %s", e)
