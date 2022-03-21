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

import piexif
from fractions import Fraction

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
gpi_data = dict()


def on_connect(client, userdata, flags, rc):
    global control_topic
    global broker_ip
    global cap_event
    global CONTROL_E
    global lib

    print('[msw_mqtt_connect] connect to ', broker_ip)
    lib_mqtt_client.subscribe(control_topic, 0)
    print('[lib]control_topic\n', control_topic)
    gpi_topic = '/MUV/control/' + lib['name'] + '/global_position_int'
    lib_mqtt_client.subscribe(gpi_topic, 0)
    print('[lib]gpi_topic\n', gpi_topic)


def on_disconnect(client, userdata, flags, rc=0):
    print(str(rc))


def on_subscribe(client, userdata, mid, granted_qos):
    print("subscribed: " + str(mid) + " " + str(granted_qos))


def on_message(client, userdata, msg):
    global cap_event
    global CONTROL_E
    global lib
    global gpi_data

    if lib["control"][0] in msg.topic:
        message = str(msg.payload.decode("utf-8")).lower()
        if message == 'g':
            cap_event |= CONTROL_E
    elif 'global_position_int' in msg.topic:
        gpi_data = json.loads(msg.payload.decode("utf-8"))


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

        insert_geotag(target)
    except Exception as e:
        camera_status = 'camera connection error'
        print(e)
        lib_mqtt_client.publish(data_topic, 'camera connection error' + str(e))

    return target


def send_status():
    global lib_mqtt_client
    global camera_status
    global data_topic

    while True:
        if not (cap_event & CONTROL_E):
            if camera_status != 'camera connection error':
                camera_status = 'ready'
            lib_mqtt_client.publish(data_topic, camera_status)
        time.sleep(1)


def ftp_connect(ftp):
    if ftp == None:
        ftp = ftplib.FTP()
        ftp.connect("gcs.iotocean.org", 50023)
        ftp.login("lx_ftp", "lx123!")

        return ftp


def main():
    global ftp
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

    ftp = ftp_connect(ftp)

    t = threading.Thread(target=send_status, )
    t.start()

    while True:
        try:
            if cap_event & CONTROL_E:
                cap_event &= (~CONTROL_E)
                target = action()

                if camera_status != "camera connection error":
                    print('try if',camera_status)
                    lib_mqtt_client.publish(data_topic, 'captured')

                    insert_geotag(target)

                    sending_file = open(target, 'rb')
                    ftp.storbinary('STOR ' + '/FTP/' + target, sending_file)
                    sending_file.close()
                    # ftp.close
                else:
                    print('try else',camera_status)

                camera.exit()
        except Exception as e:
            ftp.close()
            ftp = None
            ftp = ftp_connect(ftp)


def to_deg(value, loc):
    """convert decimal coordinates into degrees, munutes and seconds tuple
    Keyword arguments: value is float gps-value, loc is direction list ["S", "N"] or ["W", "E"]
    return: tuple like (25, 13, 48.343 ,'N')
    """
    if value < 0:
        loc_value = loc[0]
    elif value > 0:
        loc_value = loc[1]
    else:
        loc_value = ""
    abs_value = abs(value)
    deg = int(abs_value)
    t1 = (abs_value - deg) * 60
    min = int(t1)
    # sec = round((t1 - min) * 60, 5)
    sec = int((round((t1 - min) * 60, 5)) * 100000)
    return ((deg, 1), (min, 1), (sec, 100000)), loc_value


def insert_geotag(img_file):
    global gpi_data

    exif_dict = piexif.load(img_file)

    if piexif.ImageIFD.Make in exif_dict["0th"]:
        print("Make is", exif_dict["0th"][piexif.ImageIFD.Make].decode('utf-8'))
    else:
        pass
        # TODO: 없으면 카메라 정보 입력
    if piexif.ImageIFD.Model in exif_dict["0th"]:
        print("Model is", exif_dict["0th"][piexif.ImageIFD.Model].decode('utf-8'))
    else:
        pass
        # TODO: 없으면 카메라 정보 입력
    if piexif.ExifIFD.LensModel in exif_dict["Exif"]:
        print("LensModel is", exif_dict["Exif"][piexif.ExifIFD.LensModel].decode('utf-8'))
    else:
        pass
        # TODO: 없으면 카메라 정보 입력
    if piexif.ExifIFD.BodySerialNumber in exif_dict["Exif"]:
        print("BodySerialNumber is", exif_dict["Exif"][piexif.ExifIFD.BodySerialNumber].decode('utf-8'))
    else:
        pass
        # TODO: 없으면 카메라 정보 입력
    if piexif.ExifIFD.LensSerialNumber in exif_dict["Exif"]:
        print("LensSerialNumber is", exif_dict["Exif"][piexif.ExifIFD.LensSerialNumber].decode('utf-8'))
    else:
        pass
        # TODO: 없으면 카메라 정보 입력
    if piexif.ExifIFD.FocalLength in exif_dict["Exif"]:
        print("FocalLength is", exif_dict["Exif"][piexif.ExifIFD.FocalLength])
    else:
        pass
        # TODO: 없으면 카메라 정보 입력
    if piexif.ExifIFD.DateTimeOriginal in exif_dict["Exif"]:
        print("DateTimeOriginal is", (exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal]).decode('utf-8'))
    else:
        pass
        # TODO: 없으면 카메라 정보 입력
    if piexif.ExifIFD.SubSecTimeOriginal in exif_dict["Exif"]:  # 1초 미만의 데이터 * 100
        print("SubSecTimeOriginal is", (exif_dict["Exif"][piexif.ExifIFD.SubSecTimeOriginal]).decode('utf-8'))
    else:
        pass
        # TODO: 없으면 카메라 정보 입력
    if piexif.GPSIFD.GPSDateStamp in exif_dict["GPS"]:  # UTC 날짜(연:월:일)
        print("GPSDateStamp is", (exif_dict["GPS"][piexif.GPSIFD.GPSDateStamp]).decode('utf-8'))
    else:
        pass
        # TODO: 없으면 GPS 시간 입력
    if piexif.GPSIFD.GPSTimeStamp in exif_dict["GPS"]:  # UTC 시간(시, 분, 초)
        print("GPSTimeStamp is", (exif_dict["GPS"][piexif.GPSIFD.GPSTimeStamp]).decode('utf-8'))
    else:
        pass
        # TODO: 없으면 GPS 시간 입력
    if piexif.GPSIFD.GPSLatitude in exif_dict["GPS"]:  # 위도 도,분,초
        print("GPSLatitude is", (exif_dict["GPS"][piexif.GPSIFD.GPSLatitude]))
    else:
        # TODO: GPS 데이터 없을 경우
        lat, lat_ref = to_deg(36.08584746715721, ['S', 'N'])
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = lat
        gps_lat_bytes = piexif.dump(exif_dict)
        piexif.insert(gps_lat_bytes, img_file)
    if piexif.GPSIFD.GPSLatitudeRef in exif_dict["GPS"]:  # 남-'S' / 북-'N'
        print("GPSLatitudeRef is", (exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef]).decode('utf-8'))
    else:
        # TODO: GPS 데이터 없을 경우
        lat, lat_ref = to_deg(36.08584746715721, ['S', 'N'])
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
        gps_lat_bytes = piexif.dump(exif_dict)
        piexif.insert(gps_lat_bytes, img_file)
    if piexif.GPSIFD.GPSLongitude in exif_dict["GPS"]:
        print("GPSLongitude is", (exif_dict["GPS"][piexif.GPSIFD.GPSLongitude]))
    else:
        lon, lon_ref = to_deg(126.873364002257, ['W', 'E'])
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = lon
        gps_lon_bytes = piexif.dump(exif_dict)
        piexif.insert(gps_lon_bytes, img_file)
    if piexif.GPSIFD.GPSLongitudeRef in exif_dict["GPS"]:  # 동-'E' / 서-'W'
        print("GPSLongitudeRef is", (exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef]).decode('utf-8'))
    else:
        lon, lon_ref = to_deg(126.873364002257, ['W', 'E'])
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
        gps_lon_bytes = piexif.dump(exif_dict)
        piexif.insert(gps_lon_bytes, img_file)
    if piexif.GPSIFD.GPSAltitude in exif_dict["GPS"]:
        print("GPSAltitude is", (exif_dict["GPS"][piexif.GPSIFD.GPSAltitude]))
    else:
        alt = 50.03
        f = Fraction(str(alt))
        exif_dict["GPS"][piexif.GPSIFD.GPSAltitude] = (f.numerator, f.denominator)
        gps_alt_bytes = piexif.dump(exif_dict)
        piexif.insert(gps_alt_bytes, img_file)
    if piexif.GPSIFD.GPSAltitudeRef in exif_dict["GPS"]:  # 절대고도 해수면 위-0 / 해수면 아래-1
        print("GPSAltitudeRef is", (exif_dict["GPS"][piexif.GPSIFD.GPSAltitudeRef]).decode('utf-8'))
    else:
        pass
        # TODO: 없으면 GPS 고도 정보 입력
    if piexif.ExifIFD.FocalPlaneXResolution in exif_dict["Exif"]:  # Width 방향 ResolutionUnit당 픽셀 수
        print("FocalPlaneXResolution is", (exif_dict["Exif"][piexif.ExifIFD.FocalPlaneXResolution]).decode('utf-8'))
    elif piexif.ImageIFD.XResolution in exif_dict["0th"]:
        print("Use XResolution instead of FocalPlaneXResolution.\r\n XResolution is",
              (exif_dict["0th"][piexif.ImageIFD.XResolution]))
    else:
        pass
        # TODO: 없으면 카메라 정보 입력
    if piexif.ExifIFD.FocalPlaneYResolution in exif_dict["Exif"]:  # Height 방향 ResolutionUnit당 픽셀 수
        print("FocalPlaneYResolution is", (exif_dict["Exif"][piexif.ExifIFD.FocalPlaneYResolution]).decode('utf-8'))
    elif piexif.ImageIFD.YResolution in exif_dict["0th"]:
        print("Use YResolution instead of FocalPlaneYResolution.\r\n YResolution is",
              (exif_dict["0th"][piexif.ImageIFD.YResolution]))
    else:
        pass
        # TODO: 없으면 카메라 정보 입력
    if piexif.ExifIFD.FocalPlaneResolutionUnit in exif_dict["Exif"]:  # Resolution 측정 단위 1-단위X/2-Inch/3-cm
        print("FocalPlaneResolutionUnit is",
              (exif_dict["Exif"][piexif.ExifIFD.FocalPlaneResolutionUnit]).decode('utf-8'))
    elif piexif.ImageIFD.ResolutionUnit in exif_dict["0th"]:
        print("Use ResolutionUnit instead of FocalPlaneResolutionUnit.\r\n ResolutionUnit is",
              (exif_dict["0th"][piexif.ImageIFD.ResolutionUnit]))
    else:
        pass
        # TODO: 없으면 카메라 정보 입력


if __name__ == "__main__":
    sys.exit(main())
