#!/usr/bin/env python

from __future__ import print_function

import logging
import datetime
import json
import sys
import os
import threading
import time

import paho.mqtt.client as mqtt

import gphoto2 as gp

import ftplib

my_lib_name = 'lib_lx_cam'

camera = None
ftp = None
lib_mqtt_client = None

control_topic = ''
data_topic = ''

broker_ip = 'localhost'
port = 1883

cap_event = 0x00
CONTROL_E = 0x01

my_msw_name = ''
camera_status = 'init'

lib = dict()


def on_connect(client, userdata, flags, rc):
    global control_topic
    global broker_ip
    global cap_event
    global CONTROL_E

    print('[msw_mqtt_connect] connect to ', broker_ip)
    lib_mqtt_client.subscribe(control_topic, 0)
    print('[lib]control_topic\n', control_topic)


def on_disconnect(client, userdata, flags, rc=0):
    print(str(rc))


def on_subscribe(client, userdata, mid, granted_qos):
    print("subscribed: " + str(mid) + " " + str(granted_qos))


def on_message(client, userdata, msg):
    global data_topic
    global control_topic
    global cap_event
    global CONTROL_E

    message = str(msg.payload.decode("utf-8")).lower()
    if message == 'g':
        cap_event |= CONTROL_E


def msw_mqtt_connect():
    global lib_mqtt_client
    global broker_ip
    global port

    lib_mqtt_client = mqtt.Client()
    lib_mqtt_client.on_connect = on_connect
    lib_mqtt_client.on_disconnect = on_disconnect
    lib_mqtt_client.on_subscribe = on_subscribe
    lib_mqtt_client.on_message = on_message
    lib_mqtt_client.connect(broker_ip, port)
    lib_mqtt_client.loop_start()

    return lib_mqtt_client


def action():
    global camera
    global ftp
    global my_msw_name
    global lib_mqtt_client
    global data_topic
    global camera_status

    file_name = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime(
        '%Y-%m-%dT%H:%M:%S.%f')
    target = os.path.join('./', file_name + '.jpg')

    logging.basicConfig(
        format='%(levelname)s: %(name)s: %(message)s', level=logging.WARNING)
    callback_obj = gp.check_result(gp.use_python_logging())
    camera = gp.Camera()
    try:
        camera.init()
        file_path = camera.capture(gp.GP_CAPTURE_IMAGE)
        camera_file = camera.file_get(
            file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL)
        camera_file.save(target)
    except Exception as e:
        camera_status = 'camera connection error'
        lib_mqtt_client.publish(data_topic, 'camera connection error')

    return target


def send_status():
    global lib_mqtt_client
    global camera_status

    while True:
        if not (cap_event & CONTROL_E):
            if camera_status != 'camera connection error':
                camera_status = 'ready'
            lib_mqtt_client.publish(data_topic, camera_status)
        time.sleep(1)


def main():
    global camera
    global lib_mqtt_client
    global control_topic
    global data_topic
    global broker_ip
    global port
    global lib
    global my_lib_name
    global cap_event
    global CONTROL_E
    global my_msw_name

    my_msw_name = 'msw' + my_lib_name[3:] + '_' + 'msw' + my_lib_name[3:]

    try:
        lib = dict()
        with open('./' + my_msw_name + '/' + my_lib_name + '.json', 'r') as f:
            lib = json.load(f)
            lib = json.loads(lib)

    except Exception as e:
        lib = dict()
        lib["name"] = my_lib_name
        lib["target"] = 'armv6'
        lib["description"] = "[name]"
        lib["scripts"] = './' + my_lib_name
        lib["data"] = ['Status']
        lib["control"] = ['Capture']
        lib = json.dumps(lib, indent=4)
        lib = json.loads(lib)

        # with open('./' + my_msw_name + '/' + my_lib_name + '.json', 'w', encoding='utf-8') as json_file:
        with open('./' + my_lib_name + '.json', 'w', encoding='utf-8') as json_file:
            json.dump(lib, json_file, indent=4)

    control_topic = '/MUV/control/' + lib["name"] + '/' + lib["control"][0]
    data_topic = '/MUV/data/' + lib["name"] + '/' + lib["data"][0]

    msw_mqtt_connect()

    ftp = ftplib.FTP()
    ftp.connect("203.253.128.177", 50023)
    ftp.login("d_keti", "keti123")

    t = threading.Thread(target=send_status, )
    t.start()

    while True:
        if cap_event & CONTROL_E:
            cap_event &= (~CONTROL_E)
            target = action()
            print(camera_status)
            print('camera connection error')
            if camera_status != "camera connection error":
                print(camera_status)
                lib_mqtt_client.publish(data_topic, 'captured')

                sending_file = open(target, 'rb')
                ftp.storbinary('STOR ' + '/Downloads/ftp_test/' + target, sending_file)
                sending_file.close()
                ftp.close
            camera.exit()


if __name__ == "__main__":
    sys.exit(main())
