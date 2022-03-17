from concurrent.futures import process
from dis import dis
import glob
from multiprocessing.connection import wait
import os
from pyexpat import model
import re
import sys
from PIL import Image

try:
    sys.path.append(glob.glob('../carla/dist/carla-*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    pass

import carla
import random
import time
import math
import numpy as np
import cv2
import matplotlib.pyplot as plt
import lane_detector as lane
from time import sleep
from visualize_sensors import DisplayManager, SensorManager
import curved_lane_detection as det
import csv

IMG_WIDTH = 1280
IMG_HEIGHT = 720

actor_list = []
snap_list = []
yaw_list = [0,0,0,0,0]
big_dist = True

def convert_time(seconds):
    seconds = seconds%(24*3600)
    hrs = (seconds//3600)
    seconds %= 3600
    mins = seconds//60
    seconds %= 60
    mill = (seconds*1000)%1000
    return "%d:%02d:%02d:%04d"%(hrs,mins,seconds,mill)

def extract_data(snap,vehicle):
    vehicle_snap = snap.find(vehicle.id)
    transform = vehicle_snap.get_transform()
    frame = str(snap.frame)
    time = convert_time(snap.timestamp.elapsed_seconds)
    id = str(vehicle.id)
    type = str(vehicle.type_id)
    x = str("{0:10.3f}".format(transform.location.x))
    y = str("{0:10.3f}".format(transform.location.y))
    z = str("{0:10.3f}".format(transform.location.z))
    ya = str(transform.rotation.yaw)
    vel = vehicle_snap.get_velocity()
    speed = str('%15.2f'%(3.6*math.sqrt(vel.x**2 + vel.y**2 + vel.z**2)))
    throttle = str(vehicle.get_control().throttle)
    steer = str(vehicle.get_control().steer)
    brake = str(vehicle.get_control().brake)
    if throttle != 0.0 and steer != 0.0 and brake != 0.0:
        with open(dir + '/vehicle_data_%s.csv'%('leader' if vehicle==PlatooningLeader else 'follower'), 'a+', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fn)
            output = {'Snap':frame,'Time':time, 'ID':id, 'Type':type, 'X':x, 'Y':y, 'Z':z, 'Yaw':ya, 'Km/h':speed, 'Throttle':throttle, 'Steer':steer, 'Brake':brake}
            w.writerow(output)
    if vehicle==PlatooningLeader:
        yaw_list.append(float(ya))
        yaw_list.pop(0)

def record_vehicle_data(snap):
    snap_list.append(snap)
    for vehicle in actor_list:
        if isinstance(vehicle, carla.Vehicle):
            extract_data(snap,vehicle)
    #t,s,b = manage_follower(snap)
    
def leader_going_straight():
    res = True
    for i in range (4):
        if abs(yaw_list[i]-yaw_list[i+1])>0.01:
            res = False
    return res

def set_steer(fx,fy,yaw):
    with open(dir + '/vehicle_data_leader.csv', newline='') as f:
        r = csv.DictReader(f, fieldnames=fn)
        rl = list(r)
        n=0
        s=0.0
        delta_x = delta_y = 360
        best_x = best_y = rel_x = rel_y = 0
        for row in reversed(rl):
            if row!=rl[0]:
                lx = float(row['X'])
                ly = float(row['Y'])
                lyaw = float(row['Yaw'])
                if abs(lx-fx)<=(0.1 if leader_going_straight() else 0.6) and abs(ly-fy)<=(0.1 if leader_going_straight() else 0.6):
                    if lyaw<-90 and yaw>90:
                        s=float(row['Steer']) + (lyaw-yaw+360)/180
                    elif lyaw>90 and yaw<-90:
                        s=float(row['Steer']) + (lyaw-yaw-360)/180
                    else:
                        s=float(row['Steer']) + (lyaw-yaw)/180
                    if s>1.0:
                        s=1.0
                    elif s<-1.0:
                        s=-1.0
                    return s
                else:
                    if abs(lx-fx) < delta_x:
                        best_x = lx
                        rel_y = ly
                        delta_x = abs(lx-fx)
                        yaw_x = lyaw
                    if abs(ly-fy) < delta_y:
                        best_y = ly
                        rel_x = lx
                        delta_y = abs(ly-fy)
                        yaw_y=lyaw
                    lyaw = yaw_x if delta_x<delta_y else yaw_y
            n+=1
            if n>=500: break
        #non basta controllare il leader, se sono in curva e lui in rettilineo c'è un problema di correzione perchè quando il leader va verso sinistra invalida le misure
        if leader_going_straight():
            sample = yaw_list[0]
            if abs(sample)-abs(yaw)<=0.01:
                print("STRAIGHT CORRECTION")
                if abs(sample)<=45:
                    #check su x e fix y
                    s=(rel_y-fy)/20 + (sample-yaw)/180
                elif abs(sample>=135):
                    if sample>90 and yaw<-90:
                        s=(fy-rel_y)/20 + (sample-yaw-360)/180
                    if sample<-90 and yaw>90:
                        s=(fy-rel_y)/20 + (sample-yaw+360)/180
                elif sample<135 and sample>45:
                    #check su y e fix x
                    s=(fx-rel_x)/20 + (sample-yaw)/180
                elif sample>-135 and sample<-45:
                    s=(rel_x-fx)/20 + (sample-yaw)/180
                return s
                
        print("GENERIC CORRECTION")
        if yaw>-180 and yaw<=-90:
            l_pos = -rel_y if delta_x<delta_y else rel_x
            f_pos = fy if delta_x<delta_y else -fx
        if yaw>-90 and yaw<=0:
            l_pos = rel_y if delta_x<delta_y else rel_x
            f_pos = -fy if delta_x<delta_y else -fx
        if yaw>0 and yaw<=90:
            l_pos = rel_y if delta_x<delta_y else -rel_x
            f_pos = -fy if delta_x<delta_y else fx
        if yaw>90 and yaw<=180:
            l_pos = -rel_y if delta_x<delta_y else -rel_x
            f_pos = fy if delta_x<delta_y else fx
        s = (l_pos+f_pos)/20
        print(s)
        if lyaw>90 and yaw<-90:
            s+=(lyaw-yaw-360)/180
        elif lyaw<-90 and yaw>90:
            s+=(lyaw-yaw+360)/180
        else:
            s+=(lyaw-yaw)/180
        return s


def manage_follower(snap):
    with open(dir + '/vehicle_data_leader.csv', newline='') as f:
        r = csv.DictReader(f, fieldnames=fn)
        vehicle_snap = snap.find(PlatooningFollower.id)
        transform = vehicle_snap.get_transform()
        yaw = float(transform.rotation.yaw)
        vel = vehicle_snap.get_velocity()
        fspeed = float('%15.2f'%(3.6*math.sqrt(vel.x**2 + vel.y**2 + vel.z**2)))
        fx = float("{0:10.3f}".format(transform.location.x))
        fy = float("{0:10.3f}".format(transform.location.y))
        n=0
        t=s=b=0
        for row in r:
            if n!=0:
                if row['Snap'] == str(snap.frame):
                    lspeed = float(row['Km/h'])
                    delta = lspeed-fspeed
                    global big_dist
                    if (delta>0):
                        if big_dist:
                            t = 0.8
                            b = 0.0
                            s = set_steer(fx,fy,yaw)
                        else:
                            t = delta/10 if delta/10 <= 1.0 else 1.0
                            b = 0.0
                            s = set_steer(fx,fy,yaw)
                        #PlatooningFollower.apply_control(carla.VehicleControl(throttle=t, steer=s, brake=b))
                    elif delta==0:
                        b=1.0
                    else:
                        if not big_dist:
                            t = 0.0
                            b = 0.8
                            s = set_steer(fx,fy,yaw)
                        else:
                            t = 0.0
                            b = -delta/10 if -delta/10 <= 1.0 else 1.0
                            s = set_steer(fx,fy,yaw)
                    PlatooningFollower.apply_control(carla.VehicleControl(throttle=t, steer=s, brake=b))
            else:
                n+=1

def get_points(points):
    min = 500
    for p in points:
        if p.point.x<min:
            min = p.point.x
    global big_dist
    big_dist = True if min>=2 else False
            


        
try:
    client = carla.Client('localhost', 2000)
    client.set_timeout(5.0)
    
    world = client.get_world()
    settings = world.get_settings()
    settings.fixed_delta_seconds = 0.01
    world.apply_settings(settings)

    blueprint_library = world.get_blueprint_library()

    for v in world.get_actors():
        if isinstance(v, carla.Vehicle):
            v.destroy()

    dir = 'recs/' + time.strftime("%Y%m%d-%H%M%S")
    if not os.path.exists(dir):
        os.makedirs(dir)

    with open(dir + '/vehicle_data_leader.csv', 'w', newline='') as f:
        fn = ['Snap','Time', 'ID', 'Type', 'X', 'Y', 'Z', 'Yaw', 'Km/h', 'Throttle', 'Steer', 'Brake']
        w = csv.DictWriter(f, fieldnames=fn)
        print('Leader CSV file created.')
        w.writeheader()

    with open(dir + '/vehicle_data_follower.csv', 'w', newline='') as f:
        fn = ['Snap','Time', 'ID', 'Type', 'X', 'Y', 'Z', 'Yaw', 'Km/h', 'Throttle', 'Steer', 'Brake']
        w = csv.DictWriter(f, fieldnames=fn)
        print('Follower CSV file created.')
        w.writeheader()

    with open(dir + '/lidar_data_follower.csv', 'w', newline='') as f:
        ln = ['Location']
        w = csv.DictWriter(f, fieldnames=ln)
        print('Lidar CSV file created.')
        w.writeheader()

    world.on_tick(lambda snap: record_vehicle_data(snap))
    #------------------------------------
    #****** SPAWN TEST SUBJECT CAR ******
    #------------------------------------
    model3 = blueprint_library.filter('model3')[0]

    spawn = random.choice(world.get_map().get_spawn_points())

    PlatooningLeader = world.spawn_actor(model3, spawn)
    PlatooningLeader.set_autopilot(True)
    actor_list.append(PlatooningLeader)

    time.sleep(2)
    model3.set_attribute('color','255,0,0')
    PlatooningFollower = world.spawn_actor(model3, spawn)
    PlatooningFollower.apply_control(carla.VehicleControl(throttle=1.0, steer=0.0, brake=0.0))
    actor_list.append(PlatooningFollower)

    spawn = carla.Transform(carla.Location(x=2.5, z=0.8))
    lidar_bp = blueprint_library.find('sensor.lidar.ray_cast')
    lidar_bp.set_attribute('horizontal_fov','90')
    lidar_bp.set_attribute('upper_fov','5')
    lidar_bp.set_attribute('lower_fov','-5')
    LidarFollower = world.spawn_actor(lidar_bp, spawn, attach_to=PlatooningFollower)
    actor_list.append(LidarFollower)

    lanecrossing_bp = blueprint_library.find('sensor.other.lane_invasion')
    LaneSensorFollower = world.spawn_actor(lanecrossing_bp, spawn, attach_to=PlatooningFollower)
    actor_list.append(LaneSensorFollower)

    
    last_snap=0
    LidarFollower.listen(lambda points: get_points(points))
    LaneSensorFollower.listen(lambda event: print(event.transform))
    time.sleep(1)
    while True:
        if(snap_list):
            manage_follower(snap_list[-1])
        
except KeyboardInterrupt:
    pass

finally:
    print('destroying actors')
    for actor in actor_list:
        actor.destroy()
    print('done.')