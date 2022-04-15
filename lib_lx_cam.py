#!/usr/bin/env python
import datetime
import json
import os
import threading
import time
import subprocess

import paho.mqtt.client as mqtt

import piexif
from fractions import Fraction

import ftplib

my_lib_name = 'lib_lx_cam'

camera = None
ftp_client = None
lib_mqtt_client = None

control_topic = ''
data_topic = ''

broker_ip = 'localhost'
port = 1883

ftpUserID = 'lx_ftp'
ftpUserPW = 'lx123!'

cap_event = 0x00
CONTROL_E = 0x01
STOP_E = 0x02

msw_status = 'Init'
mqtt_status = 'disconnected'
ftp_status = 'disconnected'

lib = dict()
gpi_data = dict()

image_arr = []

dir_name = ''

captureImage = None
interval = 3


def on_connect(client, userdata, flags, rc):
    global control_topic
    global broker_ip
    global lib
    global mqtt_status

    print('[msw_mqtt_connect] connect to ', broker_ip)
    lib_mqtt_client.subscribe(control_topic, 0)
    print('[lib]control_topic\n', control_topic)
    gpi_topic = '/MUV/control/' + lib['name'] + '/global_position_int'
    lib_mqtt_client.subscribe(gpi_topic, 0)
    print('[lib]gpi_topic\n', gpi_topic)
    mqtt_status = 'connected'


def on_disconnect(client, userdata, flags, rc=0):
    print(str(rc))


def on_subscribe(client, userdata, mid, granted_qos):
    pass


def on_message(client, userdata, msg):
    global cap_event
    global CONTROL_E
    global STOP_E
    global lib
    global gpi_data
    global interval
    global dir_name

    if lib["control"][0] in msg.topic:
        message = str(msg.payload.decode("utf-8"))
        if 'g' in message:
            try:
                msg_arr = message.split(' ')
                if len(msg_arr) > 2:
                    interval = msg_arr[1]
                    dir_name = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime(
                        '%Y-%m-%d') + '-' + msg_arr[2]
                    dir_name = dir_name.replace("'", "")
                    if not os.path.exists(dir_name):
                        os.makedirs(dir_name)
                elif len(msg_arr) > 1:
                    interval = msg_arr[1]
                    dir_name = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime(
                        '%Y-%m-%d %H')
                    dir_name = dir_name.replace("'", "")
                    if not os.path.exists(dir_name):
                        os.makedirs(dir_name)
            except Exception as e:
                interval = 3
                dir_name = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime(
                    '%Y-%m-%d %H')
                dir_name = dir_name.replace("'", "")
                if not os.path.exists(dir_name):
                    os.makedirs(dir_name)
            cap_event |= CONTROL_E
        if message == 's':
            cap_event |= STOP_E
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


def send_status():
    global lib_mqtt_client
    global msw_status
    global data_topic
    global mqtt_status
    global ftp_status

    finish_count = 0
    while True:
        if 'Init' in msw_status:
            if mqtt_status == 'connected' and ftp_status == 'connected':
                msw_status = 'Ready'
            else:
                if mqtt_status != 'connected':
                    msw_status = 'Init - MQTT is not connected'
                elif ftp_status != 'connected':
                    msw_status = 'Init - FTP is not connected'

        elif msw_status == 'Finish':
            finish_count += 1
            if finish_count > 3:
                msw_status = 'Ready'

        else:
            pass

        lib_mqtt_client.publish(data_topic, msw_status)
        time.sleep(1)


def action():
    global msw_status
    global captureImage
    global interval

    try:
        captureImage = subprocess.Popen(
            ['gphoto2', '--capture-image-and-download', '--interval', str(interval), '--filename',
             '20%y-%m-%dT%H:%M:%S.jpg',
             '--folder', './'], stdout=subprocess.PIPE)
        print('Start taking pictures')
        msw_status = 'Capture'
    except Exception as e:
        print('[Error]\naction - ' + str(e))


def ret_imagefile():
    global image_arr
    global dir_name
    global msw_status

    # files = glob.glob('*.jpg')
    # if msw_status is 'Stop':
    #     if len(files) > 0:
    #         msw_status = 'Ready2Finish'
    #         files.sort(key=os.path.getmtime)
    #         for i in range(len(files)):
    #             if files[i] not in image_arr:
    #                 image_arr.append(files[i])
    #     else:
    #         msw_status = 'Finish'
    #         image_arr = files
    #
    # return image_arr

    files = os.listdir('./')
    file_arr = list(filter(filtering, files))

    if msw_status == 'Stop':
        if len(file_arr) > 0:
            msw_status = 'Ready2Finish'
            file_arr.sort(key=os.path.getmtime)
            for i in range(len(file_arr)):
                if file_arr[i] not in image_arr:
                    image_arr.append(file_arr[i])
        else:
            msw_status = 'Finish'
            image_arr = file_arr

    return image_arr


def ftp_connect():
    global ftp_status
    global ftp_client

    try:
        if ftp_client is None:
            ftp_client = ftplib.FTP()
            ftp_client.connect("gcs.iotocean.org", 50023)
            ftp_client.login(ftpUserID, ftpUserPW)
            ftp_status = 'connected'
        else:
            ftp_client.close()
            ftp_client = None
            ftp_client = ftplib.FTP()
            ftp_client.connect("gcs.iotocean.org", 50023)
            ftp_client.login(ftpUserID, ftpUserPW)
            ftp_status = 'connected'

    except Exception as e:
        print('[Error]\n' + str(e))
        ftp_status = 'disconnected'
        ftp_connect()


def filtering(x):
    return x.endswith('.jpg')


def send_image2ftp():
    global ftp_client
    global msw_status
    global dir_name
    global gpi_data

    crt_flag = False

    while True:
        imageList = ret_imagefile()
        if len(imageList) > 0:
            if dir_name != '' and not crt_flag:
                if dir_name in ftp_client.nlst():
                    ftp_client.cwd(dir_name)
                else:
                    ftp_client.mkd(dir_name)
                    ftp_client.cwd(dir_name)
                crt_flag = True

            try:
                insert_geotag(imageList[0])
                time.sleep(1)
                sending_file = open(imageList[0], 'rb')
                ftp_client.storbinary('STOR ' + '/' + dir_name + '/' + imageList[0][:-4] + '-' + str(gpi_data['lat']) + '-' + str(gpi_data['lon']) + '-' + str(gpi_data['relative_alt']) + '.jpg', sending_file)
                sending_file.close()
                os.replace(imageList[0], './' + dir_name + '/' + imageList[0][:-4] + '-' + str(gpi_data['lat']) + '-' + str(gpi_data['lon']) + '-' + str(gpi_data['relative_alt']) + '.jpg')
                del imageList[0]
            except FileNotFoundError as e:
                msw_status = 'FileNotFoundError ' + str(e)
                error_file = str(e).split("'")[1]
                if error_file in os.listdir(dir_name):
                    del str(e).split("'")[1]
                    print(error_file)
                    print(dir_name)
                    pass
        else:
            msw_status = 'Finish'

        time.sleep(1)


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

    print_flag = False
    '''
    # TODO: 아래 임시 좌표 삭제
    gpi_data['lat'] = 36.08584746715721
    gpi_data['lon'] = 126.873364002257
    gpi_data['alt'] = 50.03
    '''
    exif_dict = piexif.load(img_file)
    if print_flag:
        print('==============================================================')
    if piexif.ImageIFD.Make in exif_dict["0th"]:
        if print_flag:
            print("Make is", exif_dict["0th"][piexif.ImageIFD.Make].decode('utf-8'))
    else:
        pass
        # 없으면 카메라 정보 입력
    if piexif.ImageIFD.Model in exif_dict["0th"]:
        if print_flag:
            print("Model is", exif_dict["0th"][piexif.ImageIFD.Model].decode('utf-8'))
    else:
        pass
        # 없으면 카메라 정보 입력
    if piexif.ExifIFD.LensModel in exif_dict["Exif"]:
        if print_flag:
            print("LensModel is", exif_dict["Exif"][piexif.ExifIFD.LensModel].decode('utf-8'))
    else:
        pass
        # 없으면 카메라 정보 입력
    if piexif.ExifIFD.BodySerialNumber in exif_dict["Exif"]:
        if print_flag:
            print("BodySerialNumber is", exif_dict["Exif"][piexif.ExifIFD.BodySerialNumber].decode('utf-8'))
    else:
        pass
        # 없으면 카메라 정보 입력
    if piexif.ExifIFD.LensSerialNumber in exif_dict["Exif"]:
        if print_flag:
            print("LensSerialNumber is", exif_dict["Exif"][piexif.ExifIFD.LensSerialNumber].decode('utf-8'))
    else:
        pass
        # 없으면 카메라 정보 입력
    if piexif.ExifIFD.FocalLength in exif_dict["Exif"]:
        if print_flag:
            print("FocalLength is", exif_dict["Exif"][piexif.ExifIFD.FocalLength])
    else:
        pass
        # 없으면 카메라 정보 입력
    if piexif.ExifIFD.DateTimeOriginal in exif_dict["Exif"]:
        if print_flag:
            print("DateTimeOriginal is", (exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal]).decode('utf-8'))
    else:
        pass
        # 없으면 카메라 정보 입력
    if piexif.ExifIFD.SubSecTimeOriginal in exif_dict["Exif"]:  # 1초 미만의 데이터 * 100
        if print_flag:
            print("SubSecTimeOriginal is", (exif_dict["Exif"][piexif.ExifIFD.SubSecTimeOriginal]).decode('utf-8'))
    else:
        pass
        # 없으면 카메라 정보 입력
    if piexif.GPSIFD.GPSDateStamp in exif_dict["GPS"]:  # UTC 날짜(연:월:일)
        if print_flag:
            print("GPSDateStamp is", (exif_dict["GPS"][piexif.GPSIFD.GPSDateStamp]).decode('utf-8'))
    else:
        pass
        # 없으면 GPS 시간 입력
    if piexif.GPSIFD.GPSTimeStamp in exif_dict["GPS"]:  # UTC 시간(시, 분, 초)
        if print_flag:
            print("GPSTimeStamp is", (exif_dict["GPS"][piexif.GPSIFD.GPSTimeStamp]).decode('utf-8'))
    else:
        pass
        # 없으면 GPS 시간 입력
    if piexif.GPSIFD.GPSLatitude in exif_dict["GPS"]:  # 위도 도,분,초
        if print_flag:
            print("GPSLatitude is", (exif_dict["GPS"][piexif.GPSIFD.GPSLatitude]))
    else:
        # GPS 데이터 없을 경우
        lat, lat_ref = to_deg(gpi_data['lat'], ['S', 'N'])
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = lat
        gps_lat_bytes = piexif.dump(exif_dict)
        piexif.insert(gps_lat_bytes, img_file)
    if piexif.GPSIFD.GPSLatitudeRef in exif_dict["GPS"]:  # 남-'S' / 북-'N'
        if print_flag:
            print("GPSLatitudeRef is", (exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef]).decode('utf-8'))
    else:
        # GPS 데이터 없을 경우
        lat, lat_ref = to_deg(gpi_data['lat'], ['S', 'N'])
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
        gps_lat_bytes = piexif.dump(exif_dict)
        piexif.insert(gps_lat_bytes, img_file)
    if piexif.GPSIFD.GPSLongitude in exif_dict["GPS"]:
        if print_flag:
            print("GPSLongitude is", (exif_dict["GPS"][piexif.GPSIFD.GPSLongitude]))
    else:
        lon, lon_ref = to_deg(gpi_data['lon'], ['W', 'E'])
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = lon
        gps_lon_bytes = piexif.dump(exif_dict)
        piexif.insert(gps_lon_bytes, img_file)
    if piexif.GPSIFD.GPSLongitudeRef in exif_dict["GPS"]:  # 동-'E' / 서-'W'
        if print_flag:
            print("GPSLongitudeRef is", (exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef]).decode('utf-8'))
    else:
        lon, lon_ref = to_deg(gpi_data['lon'], ['W', 'E'])
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
        gps_lon_bytes = piexif.dump(exif_dict)
        piexif.insert(gps_lon_bytes, img_file)
    if piexif.GPSIFD.GPSAltitude in exif_dict["GPS"]:
        if print_flag:
            print("GPSAltitude is", (exif_dict["GPS"][piexif.GPSIFD.GPSAltitude]))
    '''
    else:
        f = Fraction(str(gpi_data['alt']))
        exif_dict["GPS"][piexif.GPSIFD.GPSAltitude] = (f.numerator, f.denominator)
        gps_alt_bytes = piexif.dump(exif_dict)
        piexif.insert(gps_alt_bytes, img_file)
    '''
    if piexif.GPSIFD.GPSAltitudeRef in exif_dict["GPS"]:  # 절대고도 해수면 위-0 / 해수면 아래-1
        if print_flag:
            print("GPSAltitudeRef is", (exif_dict["GPS"][piexif.GPSIFD.GPSAltitudeRef]).decode('utf-8'))
    else:
        pass
        # 없으면 GPS 고도 정보 입력
    if piexif.ExifIFD.FocalPlaneXResolution in exif_dict["Exif"]:  # Width 방향 ResolutionUnit당 픽셀 수
        if print_flag:
            print("FocalPlaneXResolution is", (exif_dict["Exif"][piexif.ExifIFD.FocalPlaneXResolution]).decode('utf-8'))
    elif piexif.ImageIFD.XResolution in exif_dict["0th"]:
        if print_flag:
            print("Use XResolution instead of FocalPlaneXResolution.\r\n XResolution is",
                  (exif_dict["0th"][piexif.ImageIFD.XResolution]))
    else:
        pass
        # 없으면 카메라 정보 입력
    if piexif.ExifIFD.FocalPlaneYResolution in exif_dict["Exif"]:  # Height 방향 ResolutionUnit당 픽셀 수
        if print_flag:
            print("FocalPlaneYResolution is", (exif_dict["Exif"][piexif.ExifIFD.FocalPlaneYResolution]).decode('utf-8'))
    elif piexif.ImageIFD.YResolution in exif_dict["0th"]:
        if print_flag:
            print("Use YResolution instead of FocalPlaneYResolution.\r\n YResolution is",
                  (exif_dict["0th"][piexif.ImageIFD.YResolution]))
    else:
        pass
        # 없으면 카메라 정보 입력
    if piexif.ExifIFD.FocalPlaneResolutionUnit in exif_dict["Exif"]:  # Resolution 측정 단위 1-단위X/2-Inch/3-cm
        if print_flag:
            print("FocalPlaneResolutionUnit is",
                  (exif_dict["Exif"][piexif.ExifIFD.FocalPlaneResolutionUnit]).decode('utf-8'))
    elif piexif.ImageIFD.ResolutionUnit in exif_dict["0th"]:
        if print_flag:
            print("Use ResolutionUnit instead of FocalPlaneResolutionUnit.\r\n ResolutionUnit is",
                  (exif_dict["0th"][piexif.ImageIFD.ResolutionUnit]))
    else:
        pass
        # 없으면 카메라 정보 입력
    if print_flag:
        print('==============================================================')


def main():
    global ftp_client
    global control_topic
    global data_topic
    global broker_ip
    global port
    global lib
    global my_lib_name
    global cap_event
    global CONTROL_E
    global STOP_E
    global msw_status
    global captureImage
    global dir_name

    try:
        lib = dict()
        with open('./' + my_lib_name + '.json', 'r') as f:
            lib = json.load(f)
            lib = json.loads(lib)

    except Exception as e:
        lib = dict()
        lib["name"] = my_lib_name
        lib["target"] = 'armv7l'
        lib["description"] = "[name]"
        lib["scripts"] = './' + my_lib_name
        lib["data"] = ['Status']
        lib["control"] = ['Capture']
        lib = json.dumps(lib, indent=4)
        lib = json.loads(lib)

        with open('./' + my_lib_name + '.json', 'w', encoding='utf-8') as json_file:
            json.dump(lib, json_file, indent=4)

    control_topic = '/MUV/control/' + lib["name"] + '/' + lib["control"][0]
    data_topic = '/MUV/data/' + lib["name"] + '/' + lib["data"][0]

    msw_mqtt_connect()

    t = threading.Thread(target=send_status, )
    t.start()

    ftp_connect()

    sendtoFTP = threading.Thread(target=send_image2ftp, )
    sendtoFTP.start()

    captureImage = subprocess.Popen(
        ['gphoto2', '--summary'], stdout=subprocess.PIPE)

    while True:
        if cap_event & CONTROL_E:
            cap_event &= (~CONTROL_E)
            action()

        elif cap_event & STOP_E:
            try:
                captureImage.terminate()
                print('Stop taking pictures')
                msw_status = 'Stop'
            except AttributeError as e:
                print('Before start')

            cap_event &= (~STOP_E)


if __name__ == "__main__":
    main()


