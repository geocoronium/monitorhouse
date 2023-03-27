#!/usr/bin/env python3

import constants
import serial
import serial.tools.list_ports
import confuse
import sys
import syslog
import threading
import time
import re
import uuid
from socket import gethostname
from hashlib import md5
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Queue

loop=True

def ambient_send(msg_queue,ambient_config):
    syslog.syslog(syslog.LOG_DEBUG,"In ambient_send")
    global loop
    syslog.syslog(syslog.LOG_INFO,"ambient_send() started.")

def sensor_receive(msg_queue,com_port,dev_uuid,sensor_specs):
    syslog.syslog(syslog.LOG_DEBUG,"In sensor_receive")
    sensor_type = sensor_specs[CFG_SENSORS_SPECS_TYPE].as_str()
    if sensor_type == CFG_SENSORS_SPECS_TYPE_ON_DEMAND:
        sensor_receive_on_demand(msg_queue,com_port,dev_uuid,sensor_specs)
    elif sensor_type == CFG_SENSORS_SPECS_TYPE_AUTONOMOUS:
        sensor_receive_autonomous(msg_queue,com_port,dev_uuid,sensor_specs)
    else:
        syslog.syslog(syslog.LOG_INFO,"No derived function found in sensor_receive()")

def sensor_receive_on_demand(msg_queue,com_port,dev_uuid,sensor_specs):
    syslog.syslog(syslog.LOG_DEBUG,"In sensor_receive_on_demand")
    global loop
    dev_uuid_str = str(dev_uuid)
    syslog.syslog(syslog.LOG_INFO,"sensor_receive_on_demand() started. UUID = "+dev_uuid_str)
    regexp = re.compile(sensor_specs[CFG_SENSORS_SPECS_REGEXP].as_str())
    newline = bytes.fromhex(sensor_specs[CFG_SENSORS_SPECS_NEWLINE].as_str())
    factor = sensor_specs[CFG_SENSORS_SPECS_FACTOR]
    command = sensor_specs[CFG_SENSORS_SPECS_COMMAND].as_str().encode("utf-8")+newline
    get_interval = sensor_specs[CFG_SENSORS_SPECS_GET_INTERVAL].as_number()
    sampling_times = sensor_specs[CFG_SENSORS_SPECS_SAMPLING_TIMES].as_number()
    port = serial.Serial(port=com_port.device,timeout=sampling_times/2.0)
    num_metrics = 0
    while loop:
        for c in range(sampling_times):
            if not loop:
                break
            port.write(command)
            line = port.read_until(expected=newline).decode("utf-8").rstrip()
            groups = re.match(regexp,line).groups()
            num_metrics = len(groups)
            if c == 0:
                metric = [0.0] * num_metrics
            for i in range(num_metrics):
                metric[i] += float(groups[i])
            time.sleep(get_interval)
        for i in range(num_metrics):
            if not loop:
                break
            value = metric[i] * factor[i].as_number() / sampling_times
            metric[i] = round(value,2)
        if loop:
            print(metric)


def sensor_receive_autonomous(msg_queue,com_port,dev_uuid,sensor_specs):
    syslog.syslog(syslog.LOG_DEBUG,"In sensor_receive_autonomous")
    global loop
    local_loop = True
    dev_uuid_str = str(dev_uuid)
    syslog.syslog(syslog.LOG_INFO,"sensor_receive_autonomous() started. UUID = "+dev_uuid_str)
    regexp = re.compile(sensor_specs[CFG_SENSORS_SPECS_REGEXP].as_str())
    newline = bytes.fromhex(sensor_specs[CFG_SENSORS_SPECS_NEWLINE].as_str())
    factor = sensor_specs[CFG_SENSORS_SPECS_FACTOR]
    startcommand = sensor_specs[CFG_SENSORS_SPECS_STARTCOMMAND].as_str().encode("utf-8")+newline
    stopcommand = sensor_specs[CFG_SENSORS_SPECS_STOPCOMMAND].as_str().encode("utf-8")+newline
    command_result = sensor_specs[CFG_SENSORS_SPECS_COMMAND_RESULT].as_number()
    sampling_times = sensor_specs[CFG_SENSORS_SPECS_SAMPLING_TIMES].as_number()
    port = serial.Serial(port=com_port.device,timeout=sampling_times/2.0)
    num_metrics = 0
    while loop:
        for c in range(sampling_times):
            if not loop:
                break
            raw_line = port.read_until(expected=newline)
            print(c)
            if len(raw_line) == 0:
                port.write(startcommand)
                raw_line = port.read_until(expected=newline)
                print(raw_line)
                time.sleep(1.0)
                continue
            line = raw_line.decode("utf-8").strip()
            groups = re.match(regexp,line).groups()
            num_metrics = len(groups)
            if c == 0:
                metric = [0.0] * num_metrics
            for i in range(num_metrics):
                metric[i] += float(groups[i])
        for i in range(num_metrics):
            if not loop:
                break
            value = metric[i] * factor[i].as_number() / sampling_times
            metric[i] = round(value,2)
        if loop:
            print(metric)
    port.write(stopcommand)
    if command_result == "True":
        line = port.read_until(expected=newline).decode("utf-8").strip()

if __name__ == "__main__":
    try:
        syslog.openlog("monitorhouse",syslog.LOG_PID,syslog.LOG_DAEMON)
        configuration = confuse.Configuration("monitorhouse")

        #queue = Queue()
        queue = "QUEUE"

        ambient = configuration[CFG_AMBIENT]
        with ProcessPoolExecutor(max_workers=4) as ppe:
            ppe.submit(ambient_send,queue,ambient)

            sensors = configuration[CFG_SENSORS]
            comports = serial.tools.list_ports.comports()
            for comport in comports:
                for sensor in sensors:
                    svid = sensor[CFG_SENSORS_VID].as_number()
                    spid = sensor[CFG_SENSORS_PID].as_number()
                    if comport.vid == svid and comport.pid == spid:
                        specs = sensor[CFG_SENSORS_SPECS]
                        hwid_md5 = md5(comport.hwid.encode()).hexdigest()
                        url = "http://"+gethostname()+"/"+hwid_md5
                        dev_uuid = uuid.uuid5(uuid.NAMESPACE_URL,url)
                        syslog.syslog(syslog.LOG_INFO,"Sensor found at "+url)
                        ppe.submit(sensor_receive,queue,comport,dev_uuid,specs)

    except KeyboardInterrupt as e:
        loop=False
        syslog.syslog(syslog.LOG_INFO,str(e))
    except BaseException as e:
        syslog.syslog(syslog.LOG_ERR,str(e))
