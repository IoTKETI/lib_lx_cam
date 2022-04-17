const {nanoid} = require("nanoid");
const mqtt = require("mqtt");
let fs = require('fs');
const exec = require("child_process").exec;
const piexif = require("piexifjs");
const moment = require("moment");

let my_lib_name = 'lib_lx_cam';

let lib = {};

let lib_mqtt_client = null;
let control_topic = '';
let data_topic = '';
let captured_position_topic = '';
let gpi_topic = '';
let gpi_data = {};

init();

function init() {
    try {
        lib = {};
        lib = JSON.parse(fs.readFileSync('./' + my_lib_name + '.json', 'utf8'));
    } catch (e) {
        lib = {};
        lib.name = my_lib_name;
        lib.target = 'armv7l';
        lib.description = "[name]";
        lib.scripts = './' + my_lib_name;
        lib.data = ['Status'];
        lib.control = ['Capture'];

        fs.writeFileSync('./' + my_lib_name + '.json', JSON.stringify(lib, null, 4), 'utf8');
    }

    control_topic = '/MUV/control/' + lib["name"] + '/' + lib["control"][0]
    data_topic = '/MUV/data/' + lib["name"] + '/' + lib["data"][0]
    captured_position_topic = '/MUV/data/' + lib["name"] + '/' + lib["data"][1]
    gpi_topic = '/MUV/control/' + lib['name'] + '/global_position_int'

    lib_mqtt_connect('localhost', 1883, gpi_topic, control_topic, data_topic);
}

function lib_mqtt_connect(broker_ip, port, fc, control, data) {
    if (lib_mqtt_client == null) {
        let connectOptions = {
            host: broker_ip,
            port: port,
            protocol: "mqtt",
            keepalive: 10,
            protocolId: "MQTT",
            protocolVersion: 4,
            clientId: 'lib_mqtt_client_mqttjs_' + my_lib_name + '_' + nanoid(15),
            clean: true,
            reconnectPeriod: 2000,
            connectTimeout: 2000,
            rejectUnauthorized: false
        };

        lib_mqtt_client = mqtt.connect(connectOptions);

        lib_mqtt_client.on('connect', function () {
            console.log('[lib_mqtt_connect] connected to ' + broker_ip);

            if (fc !== '') {
                lib_mqtt_client.subscribe(gpi_topic, function () {
                    console.log('[lib_mqtt] lib_sub_fc_topic: ' + gpi_topic);
                });
            }
            if (control !== '') {
                lib_mqtt_client.subscribe(control, function () {
                    console.log('[lib_mqtt] lib_sub_control_topic: ' + control);
                });
            }
        });

        lib_mqtt_client.on('message', function (topic, message) {
            if (topic === gpi_topic) {
                gpi_data = JSON.parse(message.toString());
            }

            if (topic === control) {
                if (message.toString().includes('g')) {
                    capture_image(gpi_data)
                }
            }
        });

        lib_mqtt_client.on('error', function (err) {
            console.log(err.message);
        });
    }
}

function capture_image(gps) {
    console.log(gps);
    let filename = moment().format('YYYY-MM-DDTHH:mm:ss') + '.jpg';
    let capture_command = exec("gphoto2 --capture-image-and-download --filename " + filename + " --folder ./");

    capture_command.stdout.on('data', function (data) {
        console.log('stdout: ' + data);
    });

    capture_command.stderr.on('data', function (data) {
        console.log('stderr: ' + data);
    });

    capture_command.on('exit', function (code) {
        console.log('exit: ' + code);
        gps.image = filename;
        console.log(gps);
        lib_mqtt_client.publish(captured_position_topic, JSON.stringify(gps));
        geotag_image(filename);
    });

    capture_command.on('error', function (code) {
        console.log('error: ' + code);
        // TODO: gphoto2 설치
    });
}

function geotag_image(filename) {
    var jpeg = fs.readFileSync(filename);
    var data = jpeg.toString("binary");

    var exifObj = piexif.load(data);

    exifObj.GPS[piexif.GPSIFD.GPSLatitude] = degToDmsRational(36.0858474);
    exifObj.GPS[piexif.GPSIFD.GPSLongitude] = degToDmsRational(126.8733640);
    exifObj.GPS[piexif.GPSIFD.GPSAltitude] = degToDmsRational(50.03);

    var exifbytes = piexif.dump(exifObj);

    var newData = piexif.insert(exifbytes, data);
    var newJpeg = Buffer.from(newData, "binary");
    fs.writeFileSync(filename, newJpeg);
}

function degToDmsRational(degFloat) {
    var minFloat = degFloat % 1 * 60
    var secFloat = minFloat % 1 * 60
    var deg = Math.floor(degFloat)
    var min = Math.floor(minFloat)
    var sec = Math.round(secFloat * 100)

    deg = Math.abs(deg) * 1
    min = Math.abs(min) * 1
    sec = Math.abs(sec) * 1

    return [[deg, 1], [min, 1], [sec, 100]]
}


