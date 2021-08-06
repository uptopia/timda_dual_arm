#!/usr/bin/env python

# The following code is used to watch a video stream, detect Aruco markers, and use
# a set of markers to determine the posture of the camera in relation to the plane
# of markers.
#
# Assumes that all markers are on the same plane, for example on the same piece of paper
#
# Requires camera calibration (see the rest of the project for example calibration)

import rospy, rospkg
import std_msgs, std_srvs
import numpy as np
import cv2
import cv2.aruco as aruco
import os
import pickle
import ConfigParser
from hand_eye.srv import aruco_info, aruco_infoResponse
import time
import pyrealsense2 as rs
NUMBER = 5
# # Constant parameters used in Aruco methods
# ARUCO_PARAMETERS = aruco.DetectorParameters_create()
# ARUCO_DICT = aruco.Dictionary_get(aruco.DICT_4X4_100)

# Constant parameters used in Aruco methods
ARUCO_PARAMETERS = aruco.DetectorParameters_create()
ARUCO_DICT = aruco.Dictionary_get(aruco.DICT_4X4_50)
CHARUCOBOARD_ROWCOUNT=7
CHARUCOBOARD_COLCOUNT=5

# Create grid board object we're using in our stream
CHARUCO_BOARD = aruco.CharucoBoard_create(
        squaresX=CHARUCOBOARD_COLCOUNT,
        squaresY=CHARUCOBOARD_ROWCOUNT,
        squareLength=0.0359,
        markerLength=0.0244,
        dictionary=ARUCO_DICT)



class CharucoBoardPosture():
    def __init__(self, name, size):
        self.name = name
        self.markersize = size
        self.cnd = 0
        self.frameId = 0
        self.pipeline = rs.pipeline()
        rs_config = rs.config()
        rs_config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        rs_config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 30)

        self.pipeline.start(rs_config)
        # Check for camera calibration data

        config = ConfigParser.ConfigParser()
        config.optionxform = str
        rospack = rospkg.RosPack()
        self.curr_path = rospack.get_path('hand_eye')
        config.read(self.curr_path + '/config/img_trans.ini')
        # curr_path = os.path.dirname(os.path.abspath(__file__))
        # config = ConfigParser.ConfigParser()
        # path = curr_path + '\..\config\img_trans.ini'
        # config.read(path)
        b00 = float(config.get("Internal", "Key_1_1"))
        b01 = float(config.get("Internal", "Key_1_2"))
        b02 = float(config.get("Internal", "Key_1_3"))
        b10 = float(config.get("Internal", "Key_2_1"))
        b11 = float(config.get("Internal", "Key_2_2"))
        b12 = float(config.get("Internal", "Key_2_3"))
        b20 = float(config.get("Internal", "Key_3_1"))
        b21 = float(config.get("Internal", "Key_3_2"))
        b22 = float(config.get("Internal", "Key_3_3"))

        self.cameraMatrix = np.mat([[b00, b01, b02],
                                    [b10, b11, b12],
                                    [b20, b21, b22]])
        # c_x = 643.47548083
        # c_y = 363.67742746
        # f_x = 906.60886808
        # f_y = 909.34831447
        # k_1 = 0.16962942
        # k_2 = -0.5560001
        # p_1 = 0.00116353
        # p_2 = -0.00122694
        # k_3 = 0.52491878

        # c_x = 649.007507324219
        # c_y = 356.122222900391
        # f_x = 922.76806640625
        # f_y = 923.262023925781
    
        # self.cameraMatrix = np.array([[f_x, 0, c_x],
        #                        [0, f_y, c_y],
        #                        [0, 0, 1]])
        # self.distCoeffs = np.array([k_1, k_2, p_1, p_2, k_3])
        self.distCoeffs = np.array([0.0, 0, 0, 0, 0])

        # Create vectors we'll be using for rotations and translations for postures
        self.rvecs = None 
        self.tvecs = None
        self.rvecs_arr = np.zeros((3, NUMBER))
        self.tvecs_arr = np.zeros((3, NUMBER))

        self.cam = None
        self.QueryImg = None
        self.init_server()
        frames = self.pipeline.wait_for_frames()
        color_frame = frames.get_color_frame()
        self.QueryImg = np.asanyarray(color_frame.get_data())

    def init_server(self):
        self.server = rospy.Service('get_ar_marker', aruco_info, self.findCharucoBoard)

    def findCharucoBoard(self, req):
        self.rvecs_arr = np.zeros((3, NUMBER))
        self.tvecs_arr = np.zeros((3, NUMBER))
        res = aruco_infoResponse()

        for order in range (NUMBER):
            # Capturing each frame of our video stream
            # ret, self.QueryImg = self.cam.read()
            # frames = self.pipeline.wait_for_frames()
            # color_frame = frames.get_color_frame()
            # self.QueryImg = np.asanyarray(color_frame.get_data())
            # grayscale image
            gray = cv2.cvtColor(self.QueryImg, cv2.COLOR_BGR2GRAY)

            # Detect Aruco markers
            corners, ids, rejectedImgPoints = aruco.detectMarkers(gray, ARUCO_DICT, parameters=ARUCO_PARAMETERS)

            # Refine detected markers
            # Eliminates markers not part of our board, adds missing markers to the board
            corners, ids, rejectedImgPoints, recoveredIds = aruco.refineDetectedMarkers(
                    image = gray,
                    board = CHARUCO_BOARD,
                    detectedCorners = corners,
                    detectedIds = ids,
                    rejectedCorners = rejectedImgPoints,
                    cameraMatrix = self.cameraMatrix,
                    distCoeffs = self.distCoeffs)   

            # Require 15 markers before drawing axis
            if ids is not None and len(ids) > 10:
                response, charuco_corners, charuco_ids = aruco.interpolateCornersCharuco(
                        markerCorners=corners,
                        markerIds=ids,
                        image=gray,
                        board=CHARUCO_BOARD)

                # Require more than 20 squares
                if response is not None and response > 20:
                    # Estimate the posture of the charuco board, which is a construction of 3D space based on the 2D video 
                    pose, rvec, tvec = aruco.estimatePoseCharucoBoard(
                            charucoCorners=charuco_corners, 
                            charucoIds=charuco_ids, 
                            board=CHARUCO_BOARD, 
                            cameraMatrix=self.cameraMatrix, 
                            distCoeffs=self.distCoeffs)
                    if pose:
                        if order == 0:
                            print("=============================================")
                            print(rvec)
                            print(tvec)
                        for i in range(3):
                            self.rvecs_arr[i][order] = rvec[i][0]
                            self.tvecs_arr[i][order] = tvec[i][0]
                    
                #     self.QueryImg = aruco.drawAxis(self.QueryImg, self.cameraMatrix, self.distCoeffs, rvec, tvec, 0.02)
            cv2.waitKey(10)
            # Display our image
        # print('self.rvecs_arr = ', self.rvecs_arr)
        # print('self.tvecs_arr = ', self.tvecs_arr)
        cv2.destroyAllWindows()
        r_avg = np.zeros(3) 
        t_avg = np.zeros(3)

        ra = self.rvecs_arr[0].nonzero()
        rb = self.rvecs_arr[1].nonzero()
        rc = self.rvecs_arr[2].nonzero()
        tx = self.tvecs_arr[0].nonzero()
        ty = self.tvecs_arr[1].nonzero()
        tz = self.tvecs_arr[2].nonzero()
        ra = self.rvecs_arr[0][ra]
        rb = self.rvecs_arr[1][rb]
        rc = self.rvecs_arr[2][rc]
        tx = self.tvecs_arr[0][tx]
        ty = self.tvecs_arr[1][ty]
        tz = self.tvecs_arr[2][tz]
        ra = np.sort(ra, kind = 'quicksort')
        rb = np.sort(rb, kind = 'quicksort')
        rc = np.sort(rc, kind = 'quicksort')
        tx = np.sort(tx, kind = 'quicksort')
        ty = np.sort(ty, kind = 'quicksort')
        tz = np.sort(tz, kind = 'quicksort')
        r = np.array((ra, rb, rc))
        t = np.array((tx, ty, tz))
        for i in range(3):
            rv, tv = r[i], t[i]
            
            while np.std(rv) > 0.01 and len(rv) >= NUMBER*0.2:
                if abs(rv[0] - np.average(rv)) > abs(rv[-1] - np.average(rv)):
                    rv = np.delete(rv, 0)
                else:
                    rv = np.delete(rv, -1)
            while np.std(tv) > 0.01 and len(tv) >= NUMBER*0.2:
                if abs(tv[0] - np.average(tv)) > abs(tv[-1] - np.average(tv)):
                    tv = np.delete(tv, 0)
                else:
                    tv = np.delete(tv, -1)
            
            r_avg[i] = np.average(rv)
            t_avg[i] = np.average(tv)
        
        res.rvecs = r_avg
        res.tvecs = t_avg
        print('res.rvecs is ', res.rvecs)
        print('res.tvecs is ', res.tvecs)
        result = np.array(())
        result = np.append(result, [np.copy(r_avg), np.copy(t_avg)])
        
        result = result.reshape(2,3)

        if self.name == 'test':
            # Outline all of the markers detected in our image
            self.QueryImg = aruco.drawDetectedMarkers(self.QueryImg, corners, borderColor=(0, 0, 255))
            self.QueryImg = aruco.drawAxis(self.QueryImg, self.cameraMatrix, self.distCoeffs, result[0], result[1], 0.02)
            # self.curr_path = os.path.dirname(os.path.abspath(__file__))
            filename = self.curr_path + "/pic/camera-pic-of-charucoboard-" +  str(int(self.frameId)) + ".jpg"
            cv2.imwrite(filename, self.QueryImg)
            self.frameId += 1

            print('------')

        return res
            
if __name__ == '__main__':
    rospy.init_node('aruco_tracker')
    is_show = True
    name = 'test'
    size = rospy.get_param('~marker_size')
    if rospy.has_param('is_show'):
        is_show = rospy.get_param('is_show')
    if is_show == False:
        name = 'fuck_run'

    mp = CharucoBoardPosture(name, size)
    if mp.name == 'test':
        while mp.QueryImg is None:
            time.sleep(0.1)
        while not rospy.is_shutdown():
            frames = mp.pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            mp.QueryImg = np.asanyarray(color_frame.get_data())
            cv2.imshow('Amanda', mp.QueryImg)
            cv2.waitKey(10)
    rospy.spin()
    cv2.destroyAllWindows()
    del mp

    
