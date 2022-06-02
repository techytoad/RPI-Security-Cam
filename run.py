import cv2
import time
from datetime import datetime
import subprocess
import threading
import os
from pygame import camera
import pygame
import faulthandler
import io
import socket
import RPi.GPIO as GPIO

#print c++ faults
faulthandler.enable()

#configurations
ip = "192.168.1.3"
port = 12345
days_recorded = 10
record_frame_rate = 2
time_cycle = 2*60 #seconds
run_httpserver = True
font = cv2.FONT_HERSHEY_SIMPLEX

#defaults
HD_send = False
convert_on = False
active_camera = 0

#cam thread lock
camlock = threading.Lock()
recents = [None,None]

#initial conditions
photos_cam1 = []
photos_cam2 = []

#outdoor sensor to only record when bright enough
def bright_enough():
    return not GPIO.input(18)


def write_video():
    global time_cycle, photos_cam1, photos_cam2, run
    formatting = cv2.VideoWriter_fourcc(*'DIVX')
    last_save = time.time()
    while run:
        if(time.time() >= last_save + time_cycle):
            # remove past recordings if we recorded more than 10 days...
            if(len([x for x in os.listdir() if x.find("2022")!=-1]) >= days_recorded):
                print("Deleting old directories")
                subprocess.run("sudo rm -rf *2022", shell=True)
            # create new dir if not found
            todaydate = datetime.now().strftime("%m_%d_%Y")
            if(todaydate not in os.listdir()):
                print("Making new directory for today's date")
                os.mkdir(todaydate)

            print("Saving video 1")
            myphotos = photos_cam1[:]
            if len(myphotos)>0:
                last_save = time.time()
                photos_cam1[:] = []
                frame_rate = len(myphotos) / time_cycle
                height, width, layers = myphotos[0].shape
                size = (width,height)
                writeplace = os.path.join(os.getcwd(),todaydate, "inside_"+datetime.now().strftime("%m_%d_%Y_%H_%M_%S")+".avi")
                out = cv2.VideoWriter(writeplace,formatting, frame_rate, size)
                for i in range(len(myphotos)):
                    out.write(myphotos[i])
                out.release()
                print("ending video1 writing")
                if convert_on:
                    subprocess.run(f'ffmpeg -i inside_{date_time_str}.avi -vcodec libx265 -crf 32 inside_{date_time_str}.mp4', shell=True)
                    subprocess.run(f'rm inside_{date_time_str}.avi', shell=True)

            print("Saving video 2")
            myphotos = photos_cam2[:]
            if len(myphotos)>0:
                photos_cam2[:] = []
                frame_rate = len(myphotos) / time_cycle
                height, width, layers = myphotos[0].shape
                size = (width,height)
                writeplace = os.path.join(os.getcwd(),todaydate, "outside_"+datetime.now().strftime("%m_%d_%Y_%H_%M_%S")+".avi")
                out = cv2.VideoWriter(writeplace,formatting, frame_rate, size)
                for i in range(len(myphotos)):
                    out.write(myphotos[i])
                out.release()
                print("ending video2 writing")
                if convert_on:
                    subprocess.run(f'ffmpeg -i outside_{date_time_str}.avi -vcodec libx265 -crf 32 outside_{date_time_str}.mp4', shell=True)
                    subprocess.run(f'rm outside_{date_time_str}.avi', shell=True)
        
        time.sleep(5)


def record_cam1():
    global record_frame_rate, photos_cam1, run, recents
    cam = None
    try:
        cam = pygame.camera.Camera("/dev/video0",(640,480))
        cam.start()
    except:
        print("Cannot connect to camera 1")
        return
    while run:
        try:
            # Capture frame
            camlock.acquire()
            frame1 = cam.get_image()
            camlock.release()
            print(f"\tCam 1 took pic {time.time()}")

            #  create a copy of the surface
            view = pygame.surfarray.array3d(frame1)
            #  convert from (width, height, channel) to (height, width, channel)
            view = view.transpose([1, 0, 2])
            #  convert from rgb to bgr
            frame1 = cv2.cvtColor(view, cv2.COLOR_RGB2BGR)

            date_time_str = datetime.now().strftime("%m_%d_%Y_%H_%M_%S")
            cv2.putText(frame1,date_time_str,(0,15), font, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            photos_cam1.append(frame1)
            recents[0] = frame1
            time.sleep(1/record_frame_rate)
        except:
            print("Could not get frame! Cam 1")
            continue
    cam.stop()


def record_cam2():
    global record_frame_rate, photos_cam2, run, recents
    cam = None
    try:
        cam = pygame.camera.Camera("/dev/video2",(640,480))
        cam.start()
    except:
        print("Cannot connect to camera 2")
        return
    while run:
        if bright_enough():
            try:
                # Capture frame
                camlock.acquire()
                frame2 = cam.get_image()
                camlock.release()
                print(f"\tCam 2 took pic {time.time()}")

                #  create a copy of the surface
                view = pygame.surfarray.array3d(frame2)
                #  convert from (width, height, channel) to (height, width, channel)
                view = view.transpose([1, 0, 2])
                #  convert from rgb to bgr
                frame2 = cv2.cvtColor(view, cv2.COLOR_RGB2BGR)

                date_time_str = datetime.now().strftime("%m_%d_%Y_%H_%M_%S")
                cv2.putText(frame2,date_time_str,(0,15), font, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
                photos_cam2.append(frame2)
                recents[1] = frame2
                time.sleep(1/record_frame_rate)
            except:
                print("Could not get frame! Cam 2")
                continue
    cam.stop()



class httpserver:
    def __init__(self, ip, port):
        print("Launching HTTP server")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((ip, port))
        self.clients = []
        self.sock.listen()
        self.active_camera = 0
        self.HD_send = False
        while(1):       #listen for 1 connection
            connectionSocket, addr = self.sock.accept()
            print("Got a new client")
            self.recv_thread = threading.Thread(target=self.recv, args=[connectionSocket])
            self.recv_thread.start()

    def getIndex(self):
        index = open("index.html").read()
        index = index.replace("{Cam_number}",str(self.active_camera))\
            .replace("{HD_status}",str(self.HD_send))
        return index.encode()


    def recv(self, newclient):
        global recents
        print("Listening to new client messages")
        while(run):
            newmsg = newclient.recv(4096).decode()
            print(newmsg)
            if not newmsg:
                time.sleep(2)
                print("Client disconnected")
                return
            if "GET / HTTP/1.1" in newmsg:
                print("Sending response")
                newclient.send("HTTP/1.1 200 OK\r\n\r\n".encode())
                newclient.send(self.getIndex())
            elif "change_hd_status" in newmsg:
                self.HD_send = not self.HD_send
                #change hd status flag
            elif "change_camera_view" in newmsg:
                self.active_camera = (self.active_camera+1)%2
                #change camera view flag
            elif "video" in newmsg:
                newclient.send("HTTP/1.1 200 OK\r\n".encode())
                newclient.send("Content-Type: image/jpeg\r\n".encode())
                newclient.send("Accept-Ranges: bytes\r\n\r\n".encode())
                frame = None
                recent = None
                try:
                    recent = recents[self.active_camera]
                except:
                    print("HTTPSERVER ERROR: No recent photo")
                if recent is not None:
                    if not self.HD_send:
                        recent = cv2.resize(recent, (160, 120))
                    ret, buff = cv2.imencode('.jpg', recent)
                    recent = buff.tobytes()
                    print(f"Sending frame {hex(id(recent))} at {time.time()}")
                    newclient.send(recent)


if __name__ == '__main__':
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(18, GPIO.IN)
    run = True
    subprocess.run("sudo chmod 777 /dev/video0", shell=True)
    subprocess.run("sudo chmod 777 /dev/video2", shell=True)
    camera.init()
    cam1_record = threading.Thread(target = record_cam1, args = [])
    cam1_record.start()
    cam2_record = threading.Thread(target = record_cam2, args = [])
    cam2_record.start()
    video_thread = threading.Thread(target = write_video, args = [])
    video_thread.start()
    if(run_httpserver):
        httpserverthread = threading.Thread(target = httpserver, args = [ip,port])
        httpserverthread.start()
    while True:
        time.sleep(1)
    run = False
    cam1_record.join()
    cam2_record.join()
    video_thread.join()
