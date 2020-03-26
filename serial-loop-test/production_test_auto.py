#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import binascii
import configobj
import collections
from ctypes import *
import datetime
import logging
import math
import os
import Queue
import re
import sys
import signal
import serial
import struct
import time
import threading
import xmodem
import numpy as np
import matplotlib.pyplot as plt


# Return Code:
Err_ok = 0
Err_fail = -1
Err_timeout = -2


class _tx_rx_loopback(Structure):  # 17 bytes
    _pack_ = 1
    _fields_ = [('w_character', c_ubyte),
                ('q_character', c_ubyte),
                ('accurate_indication', c_ubyte),
                ('tx_gain', c_ubyte),
                ('tx_adc_power', c_ubyte),
                ('tx_dc', c_int8),
                ('tx_ppm', c_int16),
                ('tx_snr', c_int8),
                ('rx_phase', c_ubyte),
                ('rx_gain', c_ubyte),
                ('rx_adc_power', c_ubyte),
                ('rx_dc', c_int8, 5),  # little endian: LSB
                ('reserver', c_int8, 3),
                ('rx_ppm', c_int8),
                ('rx_snr', c_int8),
                ('dut_real_ppm', c_int16)
                ]


class _chip_info(Structure):  # 5 bytes
    _pack_ = 1
    _fields_ = [("mac_addr_1", c_ubyte),
                ("mac_addr_2", c_ubyte),
                ("mac_addr_3", c_ubyte),
                ("ver_pkg_flash", c_ubyte, 1),
                ("ver_pkg_lic", c_ubyte, 1),
                ("ver_pkg_bumping", c_ubyte, 2),
                ("ver_reserved", c_ubyte, 4),
                ("ver_wafer", c_ubyte, 4),
                ("not_used_4bits", c_ubyte, 4)
                ]


DictGpioSetLevel = {
    32: 0,  # Tx LED Pull Down
    33: 0   # Rx LED Pull Down
}


DictModuleType = {
    "00": "STA",
    "01": "CCO",
    "02": "IIC",
    "03": "STA_TEST",
    "04": "3PS"
}


# 0: STA / 1: IIC / 2: 13_CCO / 3: 09_CCO / 4: Triple_Phase
DictFilterGpio = {
    0: "23",  # STA: 23
    1: "28",  # IIC: 28
    2: "2",   # 13_CCO: 2
    3: "2",   # 09_CCO: 2
    4: "23"   # Triple_Phase: 23
}


# 0: STA / 1: IIC / 2: 13_CCO / 3: 09_CCO / 4: Triple_Phase
DictDeviceTypeNumMapping = {
    0: "00",
    1: "02",
    2: "01",
    3: "01",
    4: "04"
}


# #define DUT_STA          0
# #define DUT_TRI_PHASE    1
# #define DUT_09_CCO       2
# #define DUT_13_CCO       3
# #define DUT_IIC          4
# 0: STA / 1: IIC / 2: 13_CCO / 3: 09_CCO / 4: Triple_Phase
DictGPIODeviceTypeMapping = {
    0: 0,
    1: 4,
    2: 3,
    3: 2,
    4: 1
}


# GPIO10 EVENT
# GPIO28 SET
# GPIO36 STAOUT
# GPIO48 RST
# 0: STA / 1: IIC / 2: 13_CCO / 3: 09_CCO / 4: Triple_Phase
DictGPIOLevelSetList = {
    0: [10, 48, 28, 36],
    1: [],
    2: [],
    3: [28],
    4: [10, 48, 28, 36]
}


# Dut              --->   PtK48
# GPIO23 STA_PLC   --->   GPA4
# GPIO28 EVENT     --->   GPA7
# GPIO36 SET       --->   GPA5
DictKTJGPIOMapping = {
    23: 4,
    28: 7,
    36: 5
}


ListKTJVoltageChannel = [0, 1, 2, 3, 5]


DictPhase = {
    "A": "01",  # Phase A
    "B": "02",  # Phase B
    "C": "03"  # Phase C
}


DictEndianType = {
    "<": "little-endian",
    ">": "big_endian"
}


DictStructDataFormat = {
    "x": "pad_byte",
    "c": "char",
    "b": "signed_char",
    "B": "unsigned_char",
    "?": "_bool",
    "h": "short",
    "H": "unsigned_short",
    "i": "int",
    "I": "unsigned_int",
    "l": "long",
    "L": "unsigned_long",
    "q": "long_long",
    "Q": "unsigned_long_long",
    "f": "float",
    "d": "double"
}


DictTmi = {
    0: "TMI_0",
    1: "TMI_1",
    2: "TMI_2",
    3: "TMI_3",
    4: "TMI_4",
    5: "TMI_5",
    6: "TMI_6",
    7: "TMI_7",
    8: "TMI_8",
    9: "TMI_9",
    10: "TMI_10",
    11: "TMI_11",
    12: "TMI_12",
    13: "TMI_13",
    14: "TMI_14",
    15: "EXT_TMI_0",
    16: "EXT_TMI_1",
    17: "EXT_TMI_2",
    18: "EXT_TMI_3",
    19: "EXT_TMI_4",
    20: "EXT_TMI_5",
    21: "EXT_TMI_6",
    22: "EXT_TMI_7",
    23: "EXT_TMI_8",
    24: "EXT_TMI_9",
    25: "EXT_TMI_10",
    26: "EXT_TMI_11",
    27: "EXT_TMI_12",
    28: "EXT_TMI_13",
    29: "EXT_TMI_14",
}


DictChipInfo = {
    "00011": "K48V1A (HZ3011)",
    "10011": "K48V2A (HZ3011)",
    "11011": "K48V2A (WQ3011)",
    "12011": "K48V2A (WQ3012)",
    "20011": "K48V3A (HZ3011)",
    "21011": "K48V3A (WQ3011)",
    "22011": "K48V3A (WQ3012)",
    "00001": "K68V1A (HZ3001)",
    "00201": "K68V1B (no bumping) (MT8201)",
    "00101": "K68V1B (bumping) (MT8201)",
    "10001": "K68V2A (HZ3001)",
    "10201": "K68V2B (no bumping) (MT8201)",
    "10101": "K68V2B (bumping) (MT8201)",
    "20001": "K68V3A (HZ3001)",
    "20201": "K68V3B (no bumping) (MT8201)",
    "20101": "K68V3B (bumping) (MT8201)",
    "20301": "K68V3A (MT8201 A)",
    "18001": "Null"
}


DictStructChannelVoltage = collections.OrderedDict()
DictStructChannelVoltage["channel_0_ADC_12V"] = 'H'
DictStructChannelVoltage["channel_1_ADC_3.3V"] = 'H'
DictStructChannelVoltage["channel_2_ADC_1.2V"] = 'H'
DictStructChannelVoltage["channel_3_ADC_5V"] = 'H'


def signal_exit(sig_num, sig_frame):
    print ("Exit: Ctrl C Pressed, Signal Index: %s, Program Frame: %s!!!\n" %
           (str(sig_num), str(sig_frame)))
    sys.exit()


time_out_queue = Queue.Queue(maxsize=10)


def timeout_set(time_interval, to_queue):
    def wrapper(func):
        def time_out():
            to_queue.put(1)
            print ("Timeout Error: function not responded in %d seconds, exit automatically!" % time_interval)

        def deco(*args, **kwargs):
            timer = threading.Timer(time_interval, time_out)
            timer.start()
            res = func(*args, **kwargs)
            timer.cancel()
            to_queue.queue.clear()
            return res

        return deco
    return wrapper


def cmd_id_get(data_str):
    m_cmd_id = re.search(r"2323(\w{24})(\w{8})(\w{8})(\w{8})(\w{4})((\w{2})+)4040", data_str)
    if m_cmd_id:
        str_cmd_id = m_cmd_id.group(5)  # eg. 0200
    else:
        str_cmd_id = None

    return str_cmd_id
 

@timeout_set(3, time_out_queue)
def cmd_send(pser, cmd_str, info_q, logger_p, to_queue):
    cmd_id_str = cmd_id_get(cmd_str)
    pser.write(binascii.a2b_hex(cmd_str))
    cs_info = ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}[0-9a-fA-F]{8}" + cmd_id_str + r"(\w{2})+?4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            logger_p.debug("cmd_send receive return info: %s" % m_tt.group(0))
            raw_data_str = m_tt.group(0).decode("hex")
            info_q.put(raw_data_str[32:-2])
            return Err_ok

        if not to_queue.empty():
            info_q.put(Err_timeout)
            return Err_timeout


def command_line_build(cli_data_field_str):
    str_head = r"2323" + r"00" * 12
    str_moduleid = r"03000000"
    str_messageid = r"04000000"
    str_tail = r"4040"
    
    len_total_data = len(cli_data_field_str) / 2  # length unit: byte
    totallen_str = struct.pack('<I', len_total_data).encode("hex")
    command_line = str_head + str_moduleid + str_messageid + totallen_str + cli_data_field_str + str_tail

    return command_line


def return_list_from_structure(struct_name, raw_data_str):
    s = struct_name()
    memmove(addressof(s), raw_data_str, sizeof(s))
    return_list, return_info = [], ''
    for e_info in s._fields_:
        dstr = r"hex(s." + e_info[0] + r")"
        return_info = eval(dstr)
        return_list.append((e_info[0], return_info))

    return return_list


def command_foramt_convert(obj_value, obj_endian, obj_format):
    if (isinstance(obj_value, int) and
            (obj_endian in DictEndianType.keys()) and
            (obj_format in DictStructDataFormat.keys())):
        obj_struct = struct.pack((r"%s%s" % (obj_endian, obj_format)), obj_value).encode("hex")
        temp_str, temp_index = '', 0
        for each_l in obj_struct:
            temp_index += 1
            if 2 == temp_index:
                temp_str += each_l + " "
                temp_index = 0
            else:
                temp_str += each_l
        return temp_str.strip()
    else:
        return Err_fail


def structure_info_parse_bytes(obj_struct_dict, raw_data_str, lb_endian):
    structure_parameters = obj_struct_dict.keys()
    structure_data_form = ''.join(obj_struct_dict.values())
    parse_format = struct.Struct(lb_endian + structure_data_form)
    parse_size = struct.calcsize(lb_endian + structure_data_form)

    if parse_size == len(raw_data_str):
        pass
    elif parse_size < len(raw_data_str):
        raw_data_str = raw_data_str[0: parse_size]
    else:  # parse_size > len(raw_data_str)
        padding_str = "00".decode("hex")
        raw_data_str += padding_str * (parse_size - len(raw_data_str))

    parse_results_list = list(parse_format.unpack(raw_data_str))
    return_list = zip(structure_parameters, parse_results_list)

    return return_list


def power_down_up(pser):
    str_power_down = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 04 00 00 00 00 00 00 00 00 00 00 00 40 40"
    str_power_up = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 04 00 00 00 01 00 00 00 00 00 00 00 40 40"
    command_str_power_down = str_power_down.replace(" ", "")
    command_str_power_up = str_power_up.replace(" ", "")

    time.sleep(0.5)
    print "Chip power down..."
    pser.write(binascii.a2b_hex(command_str_power_down))
    time.sleep(0.5)

    print "Chip power up..."
    pser.write(binascii.a2b_hex(command_str_power_up))
    time.sleep(0.5)


def rst_low_high(pser):
    str_rst_low = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 04 00 00 00 04 00 00 00 00 00 00 00 40 40"
    str_rst_high = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 04 00 00 00 03 00 00 00 00 00 00 00 40 40"
    command_str_rst_low = str_rst_low.replace(" ", "")
    command_str_rst_high = str_rst_high.replace(" ", "")

    time.sleep(0.5)
    print "Chip reset low..."
    pser.write(binascii.a2b_hex(command_str_rst_low))
    time.sleep(0.5)

    print "Chip reset high..."
    pser.write(binascii.a2b_hex(command_str_rst_high))
    time.sleep(0.5)


@timeout_set(2, time_out_queue)
def reg_read(pser, reg_addr, to_queue):
    if not re.match(r"0x\w{8}", reg_addr):
        print ("Error: Read Reg Address Format Illegal! Please check...")
        return Err_fail

    little_endian_reg_addr = struct.pack("<I", int(reg_addr, 16)).encode("hex")
    temp_str, temp_index = '', 0
    for each_l in little_endian_reg_addr:
        temp_index += 1
        if 2 == temp_index:
            temp_str += each_l + " "
            temp_index = 0
        else:
            temp_str += each_l
    rf_little_endian_reg_addr = temp_str.strip()

    str_overstress_int_flag_read = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                                   r"03 00 00 00 02 00 00 00 0c 00 00 00 02 00 06 00 06 00 " + \
                                   rf_little_endian_reg_addr + \
                                   r" 04 00 40 40"
    command_str_overstress_int_flag_read = str_overstress_int_flag_read.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_overstress_int_flag_read)
    pser.write(binascii.a2b_hex(command_str_overstress_int_flag_read))
    return_value, cs_info = 0, ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"04000400(\w{8})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            little_endian_hex_str = m_tt.group(1)
            format_return_value = struct.Struct('<I')
            unpack_tuple = format_return_value.unpack(little_endian_hex_str.decode("hex"))
            dec_value = unpack_tuple[0]
            bin_value_str = bin(dec_value)
            return bin_value_str

        if not to_queue.empty():
            return Err_timeout


@timeout_set(15, time_out_queue)
def enter_test_mode(serp, ini_str, enter_str, to_queue):
    s_info = ''

    m_sbl_comp = re.compile(r"kunlun v1.0 >")
    m_init_done_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}0c[0]{6}2c0006000600[0]{12}4040")

    while 1:
        serp.write(ini_str)
        s_info += serp.read(1)
        bytes2read = serp.inWaiting()
        tmp = serp.read(bytes2read)
        s_info += tmp

        m_sbl = m_sbl_comp.search(s_info)

        if m_sbl:
            match_sbl_str = m_sbl.group(0)
            print(match_sbl_str)
            s_info = s_info.replace(match_sbl_str, "")
            break

    serp.write("\n")
    serp.write(enter_str)

    while 1:
        s_info += serp.read(1)
        bytes2read = serp.inWaiting()
        tmp = serp.read(bytes2read)
        s_info += tmp

        m_init_done = m_init_done_comp.search(s_info.encode("hex"))

        if m_init_done:
            print "Test Mode Entered and Initial completes...\r\n"
            return Err_ok

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def efuse_prog_bit_lock(pser, to_queue):
    str_efuse_lock = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                     r"03 00 00 00 2d 00 00 00 06 00 00 00 2d 00 00 00 00 00 40 40"
    command_str_efuse_lock = str_efuse_lock.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_efuse_lock)
    pser.write(binascii.a2b_hex(command_str_efuse_lock))
    return_str, cs_info = '', ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"01000100(\w{2})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            return_str = m_tt.group(1)
            return return_str

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def vendor_id_set(pser, v_id_str, to_queue):
    ascii_vid_str = binascii.b2a_hex(v_id_str)
    if 4 == len(ascii_vid_str):
        tmp_vid_str = ''
        for each_l in ascii_vid_str:
            tmp_vid_str += each_l
            if 2 == len(tmp_vid_str):
                tmp_vid_str += " "
    else:
        return Err_fail
    str_vendor_id_set = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                        r"03 00 00 00 31 00 00 00 08 00 00 00 " \
                        r"31 00 02 00 02 00 " + tmp_vid_str + r" 40 40"
    command_str_vendor_id_set = str_vendor_id_set.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_vendor_id_set)
    pser.write(binascii.a2b_hex(command_str_vendor_id_set))
    return_str, cs_info = '', ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"01000100(\w{2})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            return_str = m_tt.group(1)
            return return_str

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def vendor_id_get(pser, to_queue):
    str_vendor_id_get = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                        r"03 00 00 00 37 00 00 00 06 00 00 00 37 00 00 00 00 00 40 40"
    command_str_vendor_id_get = str_vendor_id_get.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_vendor_id_get)
    pser.write(binascii.a2b_hex(command_str_vendor_id_get))
    return_str, cs_info = '', ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"02000200(\w{4})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            return_str = m_tt.group(1)
            return return_str.decode("hex")  # eg. 54 48 ---> TH

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def chip_code_get(pser, to_queue):
    str_chip_code_get = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                        r"03 00 00 00 33 00 00 00 06 00 00 00 33 00 00 00 00 00 40 40"
    command_str_chip_code_get = str_chip_code_get.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_chip_code_get)
    pser.write(binascii.a2b_hex(command_str_chip_code_get))
    return_str, cs_info = '', ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"02000200(\w{4})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            return_str = m_tt.group(1)
            return return_str

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def module_type_get(pser, to_queue):
    str_module_type_get = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                          r"03 00 00 00 30 00 00 00 06 00 00 00 30 00 00 00 00 00 40 40"
    command_str_module_type_get = str_module_type_get.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_module_type_get)
    pser.write(binascii.a2b_hex(command_str_module_type_get))
    return_str, cs_info = '', ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"01000100(\w{2})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            return_str = m_tt.group(1)
            return return_str

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def chip_mmid_get(pser, to_queue):
    str_chip_mmid_get = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                        r"03 00 00 00 38 00 00 00 06 00 00 00 38 00 00 00 00 00 40 40"
    command_str_chip_mmid_get = str_chip_mmid_get.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_chip_mmid_get)
    pser.write(binascii.a2b_hex(command_str_chip_mmid_get))
    return_str, cs_info, tmp_str, return_list = '', '', '', []

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"18001800(\w{48})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            return_str = m_tt.group(1)
            for each_letter in return_str:
                tmp_str += each_letter
                if 2 == len(tmp_str):
                    return_list.append(tmp_str)
                    tmp_str = ''
            return_list.reverse()
            return "".join(return_list)

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def read_chip_info(pser, to_queue):
    str_read_chip_id = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                               r"03 00 00 00 25 00 00 00 06 00 00 00 25 00 00 00 00 00 40 40"
    command_str_read_chip_id = str_read_chip_id.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_read_chip_id)
    pser.write(binascii.a2b_hex(command_str_read_chip_id))
    return_list, cs_info = [], ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"05000500(\w{10})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            chip_info_str = m_tt.group(1)
            raw_data_str = chip_info_str.decode("hex")
            s = _chip_info()
            memmove(addressof(s), raw_data_str, sizeof(s))
            chip_info_dict_str = (str(s.ver_wafer) + str(s.ver_reserved) + str(s.ver_pkg_bumping) +
                                  str(s.ver_pkg_lic) + str(s.ver_pkg_flash))

            cid_str = m_tt.group(1)[0:6]
            chip_id_str_new, letter_index = '', 0
            for each_letter in cid_str:
                chip_id_str_new += each_letter
                letter_index += 1
                if letter_index == 2:
                    chip_id_str_new += "-"
                    letter_index = 0

            if chip_info_dict_str in DictChipInfo.keys():
                str_chip_type = DictChipInfo[chip_info_dict_str]
                return_list.append(("chip type", str_chip_type))
                return_list.append(("chip id", chip_id_str_new[0:-1]))
                return_list.append(("ver_wafer", "0b" + (bin(s.ver_wafer)[2:]).zfill(4)))
                return_list.append(("ver_reserved", "0b" + (bin(s.ver_reserved)[2:]).zfill(4)))
                return_list.append(("ver_pkg_bumping", "0b" + (bin(s.ver_pkg_bumping)[2:]).zfill(2)))
                return_list.append(("ver_pkg_lic", "0b" + (bin(s.ver_pkg_lic)[2:]).zfill(1)))
                return_list.append(("ver_pkg_flash", "0b" + (bin(s.ver_pkg_flash)[2:]).zfill(1)))

                return return_list
            else:
                print ("Chip Info Dismatched...")
                print ("Chip Info String: %s and Chip Info ID: %s" % (chip_info_str, chip_info_dict_str))
                return Err_fail

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def read_fw_ver(pser, to_queue):
    str_read_chip_id = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                       r"03 00 00 00 26 00 00 00 06 00 00 00 26 00 00 00 00 00 40 40"
    command_str_read_chip_id = str_read_chip_id.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_read_chip_id)
    pser.write(binascii.a2b_hex(command_str_read_chip_id))
    return_str, cs_info = '', ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"\w{4}\w{4}((\w{2})+?)4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            fw_ver_str = m_tt.group(1)
            return fw_ver_str.decode("hex")

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def mac_addr_burn(pser, str_mac_addr, to_queue):
    str_burn_mac_addr_base = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                             r"03 00 00 00 27 00 00 00 0c 00 00 00 27 00 06 00 06 00 "
    burn_mac_addr_command_str = (str_burn_mac_addr_base + str_mac_addr.replace(":", " ") + r" 40 40").replace(" ", "")
    cmd_id_str = cmd_id_get(burn_mac_addr_command_str)
    pser.write(binascii.a2b_hex(burn_mac_addr_command_str))
    cs_info = ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"06000600(\w{12})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            return str_mac_addr

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def mac_addr_read(pser, to_queue):
    str_read_mac_addr = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                        r"03 00 00 00 2b 00 00 00 06 00 00 00 2b 00 00 00 00 00 40 40"
    command_str_read_mac_addr = str_read_mac_addr.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_read_mac_addr)
    pser.write(binascii.a2b_hex(command_str_read_mac_addr))
    return_str, cs_info, letter_index = '', '', 0

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"06000600(\w{12})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            return_mac_addr_str = m_tt.group(1)
            for each_l in return_mac_addr_str:
                letter_index += 1
                return_str += each_l
                if letter_index == 2:
                    return_str += ":"
                    letter_index = 0
            return return_str[0:-1]

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def calc_noise_floor(pser, to_queue):
    str_scan_nf = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                  r"03 00 00 00 0a 00 00 00 08 00 00 00 0a 00 02 00 02 00 08 0e 40 40"
    command_str_scan_nf = str_scan_nf.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_scan_nf)
    pser.write(binascii.a2b_hex(command_str_scan_nf))
    cs_info = ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"01000100(\w{2})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            str_nf_value = m_tt.group(1)
            dec_nf_value = int("0x" + str_nf_value, 16)
            return dec_nf_value

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def global_nid_set(pser, obj_nid, to_queue):
    obj_nid_parameter_str = struct.pack("<B", obj_nid).encode("hex")
    str_glb_nid = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                  r"03 00 00 00 35 00 00 00 07 00 00 00 35 00 01 00 01 00 " + obj_nid_parameter_str + r" 40 40"
    command_str_glb_nid = str_glb_nid.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_glb_nid)
    pser.write(binascii.a2b_hex(command_str_glb_nid))
    cs_info = ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"01000100(\w{2})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            str_nid_value = m_tt.group(1)
            dec_nid_value = int("0x" + str_nid_value, 16)
            return dec_nid_value

        if not to_queue.empty():
            return Err_timeout


def data_matplot_diagram(data_list, x_name, y_name, s_label, gpio_cnt, s_phase, test_loop_cnt, f_log):
    dict_line_shape = {
        "A": 'b-',
        "B": 'r--',
        "C": 'c-.'
    }
    pic_folder = f_log + r".\rx_filter_spectrogram"
    if not os.path.exists(pic_folder):
        os.makedirs(pic_folder)

    x_lim_start = data_list[-4]
    x_lim_end = data_list[-3]
    real_data_list = data_list[0:-4]
    data_x = np.array(range(x_lim_start, x_lim_end + 1))
    data_y = np.array(real_data_list)

    pic_num = (test_loop_cnt << 1) + gpio_cnt
    plt.figure(num=pic_num, figsize=(10, 10), dpi=150)
    plt.xlabel(x_name)
    plt.ylabel(y_name)
    # plt.xlim(x_lim_start, y_lim_start)
    plt.ylim(0, 100)
    title_name = 'CSI Flatness Dump Spectrogram'
    pic_legend_str = "Channel: %s | Max : %s , Min : %s , Var : %s " % \
                     (s_phase, str(max(data_y)), str(min(data_y)), str(np.var(data_y)))
    plt.title(title_name)
    plt.plot(data_x, data_y, dict_line_shape[s_phase], label=pic_legend_str)
    plt.legend(loc='upper left')
    plt.grid()
    plt.savefig(pic_folder + "\\" + r"csi_dump_" + s_label + "_" + r"_GPIO_" + str(gpio_cnt) + r".png")

    return_var = np.var(data_y)
    del data_x, data_y
    
    return return_var


def phase_filter_gpio_control(pser, switch_flag, fgpio_num, logger_printer):
    # GPIO STA: 23 / IIC: 28 / CCO: 2
    if switch_flag:
        return_gpio_set = gpio_level_set(pser, fgpio_num, 1, time_out_queue)
    else:
        return_gpio_set = gpio_level_set(pser, fgpio_num, 0, time_out_queue)

    if not return_gpio_set:
        logger_info = r"GPIO %d set level %d successfully" % (fgpio_num, switch_flag)
        logger_printer.info(logger_info)
        return Err_ok
    else:
        logger_info = r"GPIO %d set level %d failed" % (fgpio_num, switch_flag)
        logger_printer.info(logger_info)
        return Err_fail


def csi_dump_data_collect(pdata_msg):
    global dump_data_str
    global cur_gain_cnt
    global first_cur_gain

    if 3 == len(pdata_msg):
        csi_batch_info_len, fmt_csi_batch_info = 3, "3B"
    else:
        csi_batch_info_len, fmt_csi_batch_info = 8, "4H"
    csi_batch_info_str = pdata_msg[-csi_batch_info_len:]
    csi_dump_data_str = pdata_msg[0:-csi_batch_info_len]
    fs_csi_batch_info = struct.Struct('<' + fmt_csi_batch_info)
    csi_batch_info = (fs_csi_batch_info.unpack(csi_batch_info_str))
    start_tone_num = csi_batch_info[0]
    end_tone_num = csi_batch_info[1]
    gain_entry_num = csi_batch_info[2]
    # packet_info = csi_batch_info[3]
    cur_gain_cnt += 1

    if 1 == cur_gain_cnt:
        first_cur_gain = gain_entry_num
    if start_tone_num == end_tone_num == 0:
        dump_data_str += csi_dump_data_str
        return Err_ok
    elif 87 == start_tone_num and 81 == end_tone_num and 1 == gain_entry_num:
        return Err_fail
    else:
        dump_data_str += pdata_msg
        return_str = dump_data_str
        dump_data_str = ''
        return return_str


def filter_data_recalculation(obj_value_list, obj_remove_tone_list, obj_tone_start, obj_tone_end, obj_func_name):
    return_val = None
    tmp_remain_tone_index_list, tmp_calculate_data_list = [], []
    tmp_cur_tone_list = list(range(obj_tone_start, obj_tone_end))

    for each_tone in tmp_cur_tone_list:
        if each_tone in obj_remove_tone_list:
            pass
        else:
            tmp_remain_tone_index_list.append(each_tone - obj_tone_start)

    if len(tmp_remain_tone_index_list):
        for each_remain_index in tmp_remain_tone_index_list:
            tmp_calculate_data_list.append(obj_value_list[each_remain_index])
    else:
        tmp_calculate_data_list = obj_value_list

    if "avg" == obj_func_name:
        return_val = sum(tmp_calculate_data_list) / float(len(tmp_calculate_data_list))
    elif "var" == obj_func_name:
        return_val = np.var(np.array(tmp_calculate_data_list))
    else:
        pass

    return return_val


def filter_data_inspection(obj_data_list, obj_x_start, obj_x_end,
                           obj_gpio_value, obj_cur_spur_cnt, obj_cur_spur_list, obj_logger_printer):
    global dict_filter_data_info

    spur_tone_list, all_remove_tone_list = [], []

    real_y_axis_data_list = obj_data_list
    read_x_axis_data_list = range(obj_x_start, obj_x_end + 1)

    if len(read_x_axis_data_list) == len(real_y_axis_data_list):
        pass
    else:
        obj_logger_printer.info(r"Error: Fileter(Csi Dump) Data length mismatched, please check...")
        return Err_fail

    # 9 tones: 32...40
    y_axis_value_list_32_40 = real_y_axis_data_list[0:9]
    # 39 tones: 41...79
    y_axis_value_list_40_80 = real_y_axis_data_list[9:48]
    # 41 tones: 80...120
    y_axis_value_list_80_120 = real_y_axis_data_list[48:]

    avg_32_40 = sum(y_axis_value_list_32_40) / float(len(y_axis_value_list_32_40))
    avg_40_80 = sum(y_axis_value_list_40_80) / float(len(y_axis_value_list_40_80))
    avg_80_120 = sum(y_axis_value_list_80_120) / float(len(y_axis_value_list_80_120))
    var_80_120 = np.var(np.array(y_axis_value_list_80_120))

    # check spur tone, must be in range start tone and end tone
    if 0 == obj_cur_spur_cnt:
        pass
    elif 0 < obj_cur_spur_cnt <= spur_max_limit_cnt:
        for each_spur_tone in obj_cur_spur_list:
            if obj_x_start <= each_spur_tone <= obj_x_end:
                spur_tone_list.append(each_spur_tone)
    else:
        obj_logger_printer.info("Error: Spur detected %s tones position more than thd %d tones range, please check." %
                                (obj_cur_spur_cnt, spur_max_limit_cnt))
        return Err_fail

    # remove spur tone for calculation
    spur_tone_list.sort()
    if len(spur_tone_list):
        obj_logger_printer.info("Spur detected %d tone range at: %s." % (len(spur_tone_list), str(spur_tone_list)))

        for each_remove_tone in spur_tone_list:
            all_remove_tone_list.extend(range(each_remove_tone - spur_remove_tone_cnt,
                                              each_remove_tone + spur_remove_tone_cnt + 1))
        uniq_all_remove_tone_list = list(set(all_remove_tone_list))
        uniq_all_remove_tone_list.sort()
        obj_logger_printer.info("Auto remove tone num: %s." % str(uniq_all_remove_tone_list))

        # re-calculate data
        # parameters range number is [x, y]: including x without y
        avg_32_40 = filter_data_recalculation(y_axis_value_list_32_40, uniq_all_remove_tone_list, 32, 41, "avg")
        avg_40_80 = filter_data_recalculation(y_axis_value_list_40_80, uniq_all_remove_tone_list, 41, 80, "avg")
        avg_80_120 = filter_data_recalculation(y_axis_value_list_80_120, uniq_all_remove_tone_list, 80, 121, "avg")
        var_80_120 = filter_data_recalculation(y_axis_value_list_80_120, uniq_all_remove_tone_list, 80, 121, "var")

    obj_logger_printer.info(r"var_80_120: %f." % var_80_120)
    obj_logger_printer.info(r"avg_32_40: %f, avg_40_80: %f, avg_80_120: %f." % (avg_32_40, avg_40_80, avg_80_120))
    dict_filter_data_info[obj_gpio_value] = (var_80_120, avg_32_40, avg_40_80, avg_80_120)
    return Err_ok


@timeout_set(5, time_out_queue)
def flatness_test(pser, phase_s, p_str, label_str, v_gpio,
                  logger_printer, loop_cnt, to_queue, log_fold):
    global first_cur_gain
    str_tx_psg_sof_3_a = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                         r"03 00 00 00 04 00 00 00 0f 00 00 00 04 00 09 00 09 00 " + \
                         p_str + r" 10 01 00 03 00 00 00 10 40 40"
    command_str_tx_psg_sof_3_a = str_tx_psg_sof_3_a.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_tx_psg_sof_3_a)
    pser.write(binascii.a2b_hex(command_str_tx_psg_sof_3_a))
    return_list, cs_info = [], ''
    cur_spur_cnt, cur_spur_list = 0, []

    m_spur_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"14001400(\w{40})4040")
    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"\w{4}\w{4}((\w{2})+?)4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_spur = m_spur_comp.search(cs_info.encode("hex"))
        if m_spur:
            spur_data_raw_info = m_spur.group(1)
            spur_data_info = spur_data_raw_info.decode("hex")
            data_fmt = '10H'
            ss = struct.Struct(data_fmt)
            undata_spur = ss.unpack(spur_data_info)
            cur_spur_cnt = undata_spur[1]
            cur_spur_list = list(undata_spur[2:])
            if cur_spur_cnt:
                logger_printer.info("Spur detected, cnt: %d, pos: %s..." % (cur_spur_cnt, str(cur_spur_list)))
            else:
                logger_printer.info("No spur detected...")

            cs_info = cs_info.replace(m_spur.group(0).decode("hex"), "")

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            qinfo = m_tt.group(0)
            sinfo = qinfo.decode("hex")
            total_data = sinfo[2:-2]
            head_fmt = '6B6B2H2I'  # 24
            len_head_fmt = struct.calcsize(head_fmt)
            data_head = total_data[0:len_head_fmt]
            ss = struct.Struct(head_fmt)
            undata_head = ss.unpack(data_head)
            # (addr_1, addr_2, addr_3, addr_4, addr_5, addr_6, addr_1, addr_2, addr_3, addr_4, addr_5, addr_6,
            #  module_id, crc_2bytes, message_id, length)

            r_module_id = undata_head[-4]
            r_msg_id = undata_head[-2]
            if (r_module_id == 3 and r_msg_id == 1):
                r_msg_len = undata_head[-1]
                data_msg = total_data[-r_msg_len:]

                base_msg = data_msg[0:6]
                b_fmt = struct.Struct('<HHH')
                r_base_msg = b_fmt.unpack(base_msg)
                rid = r_base_msg[0]
                tlen = r_base_msg[1]
                dlen = r_base_msg[2]

                if (rid == 0x04 and tlen == dlen):
                    try:
                        pure_data_msg = data_msg[6:]
                        csi_data_collect_return_str = csi_dump_data_collect(pure_data_msg)
                        if Err_fail == csi_data_collect_return_str:
                            logger_printer.info(r"Collecting CSI Dump Data Error, please check...")
                            return Err_fail
                        elif not csi_data_collect_return_str:
                            logger_printer.info("Collecting CSI Dump Data, please wait...")
                            cs_info = cs_info.replace(m_tt.group(0).decode("hex"), "")
                            continue
                        else:
                            logger_printer.info("Collecting CSI Dump Data Completes...")
                            csi_dump_data_str_len = len(csi_data_collect_return_str)
                            fmt_scan_csi = str(csi_dump_data_str_len / 2) + 'H'
                            fs_scan_csi = struct.Struct('<' + fmt_scan_csi)
                            undata_msg = fs_scan_csi.unpack(csi_data_collect_return_str)
                            csi_dump_info_i, csi_dump_info_q, csi_dump_info_amp_avg, i_index = 0, 0, 0, 0
                            csi_dump_amp_avg_info_list = []
                            while 1:
                                csi_dump_info_i = c_int16(undata_msg[i_index]).value  # signed number
                                i_index += 1
                                csi_dump_info_q = c_int16(undata_msg[i_index]).value  # signed number
                                i_index += 1
                                if csi_dump_info_i == csi_dump_info_q == 0:
                                    csi_dump_info_amp_avg = 0
                                else:
                                    csi_dump_info_amp_avg = 10 * math.log10(csi_dump_info_i ** 2 +
                                                                            csi_dump_info_q ** 2)

                                csi_dump_amp_avg_info_list.append(csi_dump_info_amp_avg)
                                if i_index == len(undata_msg) - 4:
                                    csi_dump_amp_avg_info_list.append(undata_msg[-4])  # start tone
                                    csi_dump_amp_avg_info_list.append(undata_msg[-3])  # end tone
                                    csi_dump_amp_avg_info_list.append(first_cur_gain)  # gain value
                                    csi_dump_amp_avg_info_list.append(c_int16(undata_msg[-1]).value)  # packet info
                                    return_list.append(c_int16(undata_msg[-1]).value)
                                    break

                        return_filter_check_value = filter_data_inspection(csi_dump_amp_avg_info_list[0: -4],
                                                                           undata_msg[-4],
                                                                           undata_msg[-3],
                                                                           v_gpio,
                                                                           cur_spur_cnt, cur_spur_list,
                                                                           logger_printer)

                        var_dump_value = data_matplot_diagram(csi_dump_amp_avg_info_list,
                                                              "Tone_number", "Amp_avg(db)",
                                                              label_str, v_gpio, phase_s, loop_cnt, log_fold)
                        return_list.append(var_dump_value)
                        logger_printer.info("Matplot complete, please check the diagram!")

                        if Err_fail == return_filter_check_value:
                            logger_printer.info("Error: Csi Dump Data Inspection Failed...")
                            return Err_fail

                        return return_list
                    except Exception, e:
                        print str(e)
                        print ("Error in flatness detection, skip this test!")
                        return Err_fail

        if not to_queue.empty():
            return Err_timeout


@timeout_set(4, time_out_queue)
def sen_csr_detection(pser, p_str, tmi_num, pwr_att, to_queue):
    hex_tmi = (struct.pack('<B', tmi_num)).encode("hex")
    hex_pwr_att = (struct.pack('<B', pwr_att)).encode("hex")
    str_sen_csr = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                  r"03 00 00 00 04 00 00 00 10 00 00 00 04 00 0a 00 0a 00 " + \
                  p_str + r" 10 01 00 04 00 00 00 " + hex_tmi + " " + hex_pwr_att + r" 40 40"
    command_str_sen_csr = str_sen_csr.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_sen_csr)
    pser.write(binascii.a2b_hex(command_str_sen_csr))
    return_value, cs_info = 0, ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"01000100(\w{2})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            hex_str = r"0x" + m_tt.group(1)
            return_value = int(hex_str, 16)
            return return_value

        if not to_queue.empty():
            return Err_timeout


@timeout_set(4, time_out_queue)
def txrx_process(p_str, dt_queue, g_ppm, logger_printer, to_queue):
    global tx_power_threshold
    global rx_rssi_threshold
    global dut_real_ppm_max
    global dut_real_ppm_min
    global rx_snr_threshold

    # golden ppm(int16_t) format: parameter
    little_endian_g_ppm = struct.pack("<h", g_ppm).encode("hex")
    temp_str, temp_index = '', 0
    for each_l in little_endian_g_ppm:
        temp_index += 1
        if 2 == temp_index:
            temp_str += each_l + " "
            temp_index = 0
        else:
            temp_str += each_l
    rf_little_endian_g_ppm = temp_str.strip()

    # dtest tx psg sof 2 a/b/c 0 : data field info
    str_cli_data_field = r"04 00 0b 00 0b 00 " + p_str + " 10 01 00 02 00 00 00 10 " + rf_little_endian_g_ppm
    str_cli_data_field = str_cli_data_field.replace(" ", '')
    command_str = command_line_build(str_cli_data_field)
    logger_printer.debug("Command Line str: %s" % command_str)

    cmd_send(ser, command_str, dt_queue, logger_printer, to_queue)
    return_value, dut_real_ppm, tx_info_list, rd_info = 0, 0, [], None
    try:
        rd_info = dt_queue.get()
        if Err_timeout == rd_info:
            logger_printer.info("Error: Receving Data Time out, please check...")
            return Err_timeout
    except Exception:
        logger_printer.info("Error: Receving Data Time out, please check...")
    tx_info_list = return_list_from_structure(_tx_rx_loopback, rd_info)

    if ('accurate_indication', '0xff') in tx_info_list or ('accurate_indication', '0x4') in tx_info_list:
        logger_printer.info("TXRX loopback SUCCESSFUL!!")
        tx_power_gain, tx_power_rmi, rx_power_gain, rx_power_rmi, = 0, 0, 0, 0
        tx_power, rx_rssi, tx_ppm, rx_dc, rx_ppm, rx_snr = 0, 0, 0, 0, 0, 0
        for each_info in tx_info_list:
            if each_info[0] == "tx_gain":
                tx_power_gain = int(each_info[1], 16)
                logger_printer.info("tx_gain : %d" % (tx_power_gain - 24))
            elif each_info[0] == "tx_adc_power":
                tx_power_rmi = int(each_info[1], 16)
                logger_printer.info("tx_adc_power : %d" % tx_power_rmi)
                tx_power = tx_power_rmi - (tx_power_gain - 24)
                logger_printer.info("tx_power : %s" % tx_power)
            elif each_info[0] == "tx_dc":
                tx_dc = int(each_info[1], 16)
                logger_printer.info("tx_dc : %d" % tx_dc)
            elif each_info[0] == "tx_ppm":
                tx_ppm = int(each_info[1], 16)
                logger_printer.info("tx_ppm : %d" % tx_ppm)
            elif each_info[0] == "dut_real_ppm":
                dut_real_ppm = int(each_info[1], 16)
                if dut_real_ppm > 0:
                    ppm_info = r"Faster than reference frequency!"
                elif dut_real_ppm < 0:
                    ppm_info = r"Slower than reference frequency!"
                else:
                    ppm_info = r"Match reference frequency!"
                logger_printer.info("Dut_real_ppm: %d (%s)" % (dut_real_ppm, ppm_info))
            elif each_info[0] == "rx_dc":
                rx_dc = int(each_info[1], 16)
                logger_printer.info("rx_dc : %d" % rx_dc)
            elif each_info[0] == "reserver":
                pass
            elif each_info[0] == "rx_ppm":
                pass
                # rx_ppm = int(each_info[1], 16)
                # logger_printer.info("rx_ppm : %d" % rx_ppm)
            elif each_info[0] == "rx_snr":
                rx_snr = int(each_info[1], 16)
                logger_printer.info("rx_snr : %d" % rx_snr)
            elif each_info[0] == "rx_gain":
                rx_power_gain = int(each_info[1], 16)
                logger_printer.info("rx_gain : %d" % (rx_power_gain - 24))
            elif each_info[0] == "rx_adc_power":
                rx_power_rmi = int(each_info[1], 16)
                logger_printer.info("rx_adc_power : %d" % rx_power_rmi)
                rx_rssi = rx_power_rmi - (rx_power_gain - 24)
                logger_printer.info("rx_rssi : %s" % rx_rssi)
            elif each_info[0] == "accurate_indication":
                accurate_indication = each_info[1]
                logger_printer.info("accurate_indication : %s" % accurate_indication)
            elif each_info[0] == "w_character":
                w_character = int(each_info[1], 16)
                logger_printer.info("w_character : %c" % w_character)
            elif each_info[0] == "q_character":
                q_character = int(each_info[1], 16)
                logger_printer.info("q_character : %c" % q_character)
            else:
                tmp_printer_str = each_info[0] + r" : " + str(int(each_info[1], 16))
                logger_printer.info(tmp_printer_str)

        if(tx_power < tx_power_threshold):
            logger_printer.info("tx_power(%d) is less than %f" % (tx_power, tx_power_threshold))
            return_value = -1

        if (rx_rssi < rx_rssi_threshold):
            logger_printer.info("rx_rssi(%d) is less than %f" % (rx_rssi, rx_rssi_threshold))
            return_value = -1

        if(dut_real_ppm > dut_real_ppm_max):
            logger_printer.info("DUT_real_ppm(%d) is larger than %f" % (dut_real_ppm, dut_real_ppm_max))
            return_value = -1
        elif(dut_real_ppm < dut_real_ppm_min):
            logger_printer.info("DUT_real_ppm(%d) is less than %f" % (dut_real_ppm, dut_real_ppm_min))
            return_value = -1

        if(rx_snr < rx_snr_threshold):
            logger_printer.info("rx_snr(%d) is less than %f" % (rx_snr, rx_snr_threshold))
            return_value = -1

    else:
        logger_printer.info("TXRX loopback FAIL!")
        logger_printer.info("Response as below: ")
        for each_tx_info in tx_info_list[0:3]:
            logger_printer.info(each_tx_info)
        if ('accurate_indication', '0x0') in tx_info_list:
            logger_printer.info(r"Error: real ppm value over range!")
        elif ('accurate_indication', '0x1') in tx_info_list:
            logger_printer.info(r"Error: golden unit is not online!")
        elif ('accurate_indication', '0x2') in tx_info_list:
            logger_printer.info(r"Error: snr check failed!")
        elif ('accurate_indication', '0x3') in tx_info_list:
            logger_printer.info(r"Error: ppm calibration burned failed!")
        else:
            pass
        return_value = -1

    if -1 == return_value:
        logger_printer.info("TEST Result =================> FAIL!!!!")
    else:
        logger_printer.info("TEST Result =================> PASS!!!!")

    return return_value


@timeout_set(2, time_out_queue)
def gpio_level_set(pser, obj_gpio_num, obj_set_level, to_queue):
    cmd_gpio_num_str = command_foramt_convert(obj_gpio_num, "<", "B")
    cmd_set_level_str = command_foramt_convert(obj_set_level, "<", "B")
    str_gpio_level_set = (r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 "
                          r"03 00 00 00 21 00 00 00 08 00 00 00 21 00 02 00 02 00 %s %s 40 40" %
                          (cmd_gpio_num_str, cmd_set_level_str))
    command_str_gpio_level_set = str_gpio_level_set.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_gpio_level_set)
    pser.write(binascii.a2b_hex(command_str_gpio_level_set))
    return_value, cs_info = 0, ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"02000200%s%s4040" %
                           (cmd_gpio_num_str, cmd_set_level_str))

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))

        if m_tt:
            return Err_ok

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def gpio_level_get(pser, obj_gpio_list, to_queue):
    cs_info, return_dict = '', {}
    len_gpio_list = len(obj_gpio_list)
    total_cmd_len = len_gpio_list + 6
    cmd_len_gpio_list_str = command_foramt_convert(len_gpio_list, "<", "H")
    cmd_total_len_str = command_foramt_convert(total_cmd_len, "<", "I")
    cmd_gpio_set_data_str = r"%s %s" % (cmd_len_gpio_list_str, cmd_len_gpio_list_str)
    for each_gpio_num in obj_gpio_list:
        cmd_gpio_set_data_str += " "
        cmd_gpio_set_data_str += command_foramt_convert(each_gpio_num, "<", "B")
    str_gpio_level_get = (r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 "
                          r"03 00 00 00 22 00 00 00 %s 22 00 %s 40 40" % (cmd_total_len_str, cmd_gpio_set_data_str))
    command_str_gpio_level_get = str_gpio_level_get.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_gpio_level_get)
    pser.write(binascii.a2b_hex(command_str_gpio_level_get))

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"\w{4}\w{4}(\w+)4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))

        if m_tt:
            return_str = m_tt.group(1)
            reformat_str, obj_cnt = '', 0
            for each_i in return_str:
                obj_cnt += 1
                reformat_str += each_i
                if 2 == obj_cnt:
                    reformat_str += " "
                    obj_cnt = 0
            reformat_str = reformat_str.strip()
            return_list = reformat_str.split(" ")
            len_return_list = len(return_list)
            if 0 == len_return_list % 2:  # even number
                for each_index in range(len_return_list / 2):
                    # dict: gpio num -> gpio status string
                    return_dict[int(return_list[2 * each_index], 16)] = str(
                        int(return_list[2 * each_index + 1], 16)
                    )
                return return_dict
            else:  # odd number
                return Err_fail

        if not to_queue.empty():
            return Err_timeout


def led_control(pser, logger_printer):
    logger_info = ""
    for each_gpio_num in DictGpioSetLevel.keys():
        each_gpio_level = DictGpioSetLevel[each_gpio_num]
        return_gpio_set = gpio_level_set(pser, each_gpio_num, 0, time_out_queue)
        if not return_gpio_set:
            logger_info += r"GPIO %d set level %d successfully. " % (each_gpio_num, each_gpio_level)
        else:
            logger_printer.info(logger_info)
            return logger_info
        time.sleep(0.5)
    logger_printer.info(logger_info)
    return Err_ok


@timeout_set(2, time_out_queue)
def zero_cross_detection(pser, to_queue):
    str_zero_cross = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 " \
                     r"03 00 00 00 39 00 00 00 06 00 00 00 39 00 00 00 00 00 40 40"
    command_str_zero_cross = str_zero_cross.replace(" ", "")
    cmd_id_str = cmd_id_get(command_str_zero_cross)
    pser.write(binascii.a2b_hex(command_str_zero_cross))
    return_str, cs_info = '', ''

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}" + cmd_id_str + r"01000100(\w{2})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))
        if m_tt:
            return_str = m_tt.group(1)
            if "01" == return_str:
                return Err_ok  # zero cross detection passed
            else:
                return Err_fail  # zero cross detection failed

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def channel_voltage_detection(pser, logger_printer, to_queue):
    global ch0_voltage_ADC_12mV
    global ch0_voltage_lower_limit
    global ch0_voltage_upper_limit
    global ch1_voltage_ADC_3_3mV
    global ch1_voltage_lower_limit
    global ch1_voltage_upper_limit
    global ch2_voltage_ADC_1_2mV
    global ch2_voltage_lower_limit
    global ch2_voltage_upper_limit
    global ch3_voltage_ADC_5mV
    global ch3_voltage_lower_limit
    global ch3_voltage_upper_limit

    return_str, cs_info = '', ''
    str_voltage_check = r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 04 00 00 00 0A 00 00 00 00 00 00 00 40 40"
    command_str_voltage_check = str_voltage_check.replace(" ", "")
    pser.write(binascii.a2b_hex(command_str_voltage_check))

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}100008000800(\w{16})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))

        if m_tt:
            return_str = m_tt.group(1)
            return_raw_data_str = return_str.decode("hex")
            channel_voltage_list = structure_info_parse_bytes(DictStructChannelVoltage, return_raw_data_str, '<')
            # [('channel_0_ADC_12mV', 10556),
            #  ('channel_1_ADC_3.3mV', 3125),
            #  ('channel_2_ADC_1.2mV', 1170),
            #  ('channel_3_ADC_5mV', 0)]
            ch0_voltage_ADC_12mV = channel_voltage_list[0][1]
            ch1_voltage_ADC_3_3mV = channel_voltage_list[1][1]
            ch2_voltage_ADC_1_2mV = channel_voltage_list[2][1]
            ch3_voltage_ADC_5mV = channel_voltage_list[3][1]

            ch0_voltage_adc_12v = ch0_voltage_ADC_12mV / 1000.0
            ch1_voltage_adc_3_3v = ch1_voltage_ADC_3_3mV / 1000.0
            ch2_voltage_adc_1_2v = ch2_voltage_ADC_1_2mV / 1000.0
            ch3_voltage_adc_5v = ch3_voltage_ADC_5mV / 1000.0

            logger_info = (r"Voltage(V): "
                           r"ch0_ADC_12V = %f  ch1_ADC_3.3V = %f  ch2_ADC_1.2V = %f  ch3_ADC_5V = %f" %
                           (ch0_voltage_adc_12v,
                            ch1_voltage_adc_3_3v,
                            ch2_voltage_adc_1_2v,
                            ch3_voltage_adc_5v))
            logger_printer.info(logger_info)

            error_info = ''
            if ch0_voltage_lower_limit <= ch0_voltage_adc_12v <= ch0_voltage_upper_limit:
                pass
            else:
                error_info += (r"Channel 0 ADC 12V Voltage %fV is beyond range[%fV : %fV]   " %
                               (ch0_voltage_adc_12v,
                                ch0_voltage_lower_limit,
                                ch0_voltage_upper_limit))

            if ch1_voltage_lower_limit <= ch1_voltage_adc_3_3v <= ch1_voltage_upper_limit:
                pass
            else:
                error_info += (r"Channel 1 ADC 3.3V Voltage %fV is beyond range[%fV : %fV]   " %
                               (ch1_voltage_adc_3_3v,
                                ch1_voltage_lower_limit,
                                ch1_voltage_upper_limit))

            if ch2_voltage_lower_limit <= ch2_voltage_adc_1_2v <= ch2_voltage_upper_limit:
                pass
            else:
                error_info += (r"Channel 2 ADC 1.2V Voltage %fV is beyond range[%fV : %fV]   " %
                               (ch2_voltage_adc_1_2v,
                                ch2_voltage_lower_limit,
                                ch2_voltage_upper_limit))

            # if ch3_voltage_lower_limit <= ch3_voltage_adc_5v <= ch3_voltage_upper_limit:
            #     pass
            # else:
            #     error_info += (r"Channel 3 ADC 5V Voltage %fV is beyond range[%fV : %fV]   " %
            #                    (ch3_voltage_adc_5v,
            #                     ch3_voltage_lower_limit,
            #                     ch3_voltage_upper_limit))

            if not error_info:
                logger_info = r"Channel voltage detection pass"
                logger_printer.info(logger_info)
                return Err_ok
            else:
                logger_info = r"Channel voltage detection fail"
                logger_printer.info(logger_info)
                logger_printer.info(error_info)
                return Err_fail

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def k48_low_voltage_pin_status_set(pser, obj_set_level, to_queue):
    global device_type

    return_str, cs_info = '', ''
    cmd_device_type_str = command_foramt_convert(DictGPIODeviceTypeMapping[device_type], "<", "B")
    cmd_set_level_str = command_foramt_convert(obj_set_level, "<", "B")
    str_low_voltage_pin_set = (r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 "
                               r"04 00 00 00 0B 00 00 00 02 00 00 00 %s %s 40 40" %
                               (cmd_device_type_str, cmd_set_level_str))
    command_str_low_voltage_pin_set = str_low_voltage_pin_set.replace(" ", "")
    pser.write(binascii.a2b_hex(command_str_low_voltage_pin_set))

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}0b0002000200%s%s4040" %
                           (cmd_device_type_str, cmd_set_level_str))

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))

        if m_tt:
            return Err_ok

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def k48_low_voltage_pin_status_get(pser, obj_get_gpio_num, obj_get_gpio_port, to_queue):
    return_str, cs_info = '', ''
    cmd_get_gpio_num_str = command_foramt_convert(obj_get_gpio_num, "<", "B")
    cmd_get_gpio_port_str = command_foramt_convert(obj_get_gpio_port, "<", "B")
    str_low_voltage_pin_get = (r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 "
                               r"04 00 00 00 0C 00 00 00 02 00 00 00 %s %s 40 40" %
                               (cmd_get_gpio_num_str, cmd_get_gpio_port_str))
    command_str_low_voltage_pin_get = str_low_voltage_pin_get.replace(" ", "")
    pser.write(binascii.a2b_hex(command_str_low_voltage_pin_get))

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}0c0001000100(\w{2})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))

        if m_tt:
            return m_tt.group(1)

        if not to_queue.empty():
            return Err_timeout


@timeout_set(2, time_out_queue)
def disable_gpio_rst(pser, en_flag, to_queue):
    return_str, cs_info = '', ''
    # 0: disable, 1: enable
    cmd_en_flag_str = command_foramt_convert(en_flag, "<", "B")
    str_disable_gpio_rst = (r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 "
                            r"03 00 00 00 3a 00 00 00 07 00 00 00 3a 00 01 00 01 00 %s 40 40" % cmd_en_flag_str)
    command_str_disable_gpio_rst = str_disable_gpio_rst.replace(" ", "")
    pser.write(binascii.a2b_hex(command_str_disable_gpio_rst))

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}3a0001000100(\w{2})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))

        if m_tt:
            # 00: disable
            return m_tt.group(1)

        if not to_queue.empty():
            return Err_timeout


def low_voltage_pin_status_detection(pser, logger_printer):
    global device_type

    if 2 == device_type:  # Dut 13 CCO only check ste0 status
        state0_dut_13cco_num, gpio_ex_port_a = 3, 1
        return_status_get = k48_low_voltage_pin_status_get(pser, state0_dut_13cco_num, gpio_ex_port_a, time_out_queue)
        if "00" == return_status_get:
            logger_info = r"GPIO STATE0 0 Status Detection pass"
            logger_printer.info(logger_info)
            return Err_ok
        elif "01" == return_status_get:
            logger_info = r"GPIO STATE0 0 Status Detection 1 fail"
            logger_printer.info(logger_info)
            return Err_fail
        else:
            logger_info = r"GPIO STATE0 0 Status Detection TimeOut"
            logger_printer.info(logger_info)
            return Err_timeout
    else:
        if "00" == disable_gpio_rst(pser, 0, time_out_queue):
            logger_info = r"Disable GPIO RST pass"
            logger_printer.info(logger_info)
        else:
            logger_info = r"Disable GPIO RST TimeOut"
            logger_printer.info(logger_info)
            return Err_timeout
        check_cnt = 0
        gpio_set_status_list = range(2)  # [0, 1]
        for each_status in gpio_set_status_list:
            return_status_set = k48_low_voltage_pin_status_set(pser, each_status, time_out_queue)
            if not return_status_set:  # Err_ok
                return_level_get = gpio_level_get(pser, DictGPIOLevelSetList[device_type], time_out_queue)
                if isinstance(return_level_get, dict) and return_level_get:
                    logger_info = (r"GPIO set status %d and get status {gpio_num: gpio_level} = %s" %
                                   (each_status, str(return_level_get)))
                    logger_printer.info(logger_info)
                    num_gpio = len(return_level_get)
                    if [str(each_status)] * num_gpio == return_level_get.values():
                        check_cnt += 1
                    else:
                        logger_info = r"GPIO Status %d Detection fail" % each_status
                        logger_printer.info(logger_info)
                        return Err_fail
                elif Err_fail == return_level_get:
                    logger_info = r"GPIO set status %d and get status fail" % each_status
                    logger_printer.info(logger_info)
                    return Err_fail
                else:
                    logger_info = r"GPIO set status %d and get status TimeOut" % each_status
                    logger_printer.info(logger_info)
                    return Err_timeout
            else:
                logger_info = r"GPIO set status %d TimeOut" % each_status
                logger_printer.info(logger_info)
                return Err_timeout

        if "01" == disable_gpio_rst(pser, 1, time_out_queue):
            logger_info = r"Enable GPIO RST pass"
            logger_printer.info(logger_info)
        else:
            logger_info = r"Enable GPIO RST TimeOut"
            logger_printer.info(logger_info)
            return Err_timeout

        if 2 == check_cnt:
            logger_info = r"GPIO Status Detection pass"
            logger_printer.info(logger_info)
            return Err_ok


@timeout_set(2, time_out_queue)
def dut_charge_voltage_detection(pser, logger_printer, to_queue, charge_mode=3, init_flag=1):
    global voltage_factor
    global charge_timespan
    global pre_charge_voltage
    global pro_charge_voltage
    global voltage_rise
    global charge_voltage_threshold
    global tdsb_charge_time_interval

    if 3 == charge_mode:
        tmp_tdsb_now_time_interval = datetime.datetime.now()
        tmp_time_interval = (tmp_tdsb_now_time_interval - tdsb_charge_time_interval).seconds
        if tmp_time_interval < charge_timespan:
            logger_printer.info("TDSB charge time interval %ds not enough to %ds, auto sleep %ds." %
                                (tmp_time_interval, charge_timespan, charge_timespan - tmp_time_interval))
            time.sleep(charge_timespan - tmp_time_interval)
    elif 2 == charge_mode:
        tdsb_charge_time_interval = datetime.datetime.now()
    else:
        pass

    return_str, cs_info = '', ''
    cmd_charge_mode_str = command_foramt_convert(charge_mode, "<", "B")
    cmd_dut_charge_timespan_str = command_foramt_convert(charge_timespan, "<", "B")
    str_dut_charge_voltage_get = (r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 "
                                  r"03 00 00 00 3b 00 00 00 08 00 00 00 3b 00 02 00 02 00 %s %s 40 40" %
                                  (cmd_charge_mode_str, cmd_dut_charge_timespan_str))
    command_str_dut_charge_voltage_get = str_dut_charge_voltage_get.replace(" ", "")
    pser.write(binascii.a2b_hex(command_str_dut_charge_voltage_get))

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}3b0005000500(\w{10})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))

        if m_tt:
            return_str = m_tt.group(1)
            return_raw_hex_str = return_str.decode("hex")
            unpack_format = struct.Struct("<iB")  # int32_t and uint8_t: voltage and charge_status
            # return_charge_status: 0=starts, 1=charging, 2=done
            return_voltage_value, return_charge_status = unpack_format.unpack(return_raw_hex_str)
            actual_voltage = float(return_voltage_value * voltage_factor)

            if not init_flag:  # function enter first time
                pre_charge_voltage = actual_voltage
                logger_info = (r"Dut charge %ds voltage inital %fV" % (charge_timespan, pre_charge_voltage))
                logger_printer.info(logger_info)
                return Err_ok
            else:  # function enter next time
                if 1 == return_charge_status:  # charge done
                    pro_charge_voltage = actual_voltage
                    voltage_rise = pro_charge_voltage - pre_charge_voltage
                    if charge_voltage_threshold <= voltage_rise:
                        logger_info = (r"Dut charge %ds voltage from %fV to %fV rise %fV" %
                                       (charge_timespan, pre_charge_voltage, pro_charge_voltage, voltage_rise))
                        logger_printer.info(logger_info)
                        return Err_ok
                    else:
                        logger_info = (r"Dut charge %ds voltage from %fV to %fV rise %fV less than %fV" %
                                       (charge_timespan, pre_charge_voltage, pro_charge_voltage, voltage_rise,
                                        charge_voltage_threshold))
                        logger_printer.info(logger_info)
                        return Err_fail
                elif 0 == return_charge_status:  # charging
                    logger_info = r"Dut charging TimeOut"
                    logger_printer.info(logger_info)
                    return Err_timeout
                else:  # charge starts but should not be received here
                    logger_info = r"Dut charging failed"
                    logger_printer.info(logger_info)
                    return Err_fail

        if not to_queue.empty():
            return Err_timeout


@timeout_set(5, time_out_queue)
def init_send(pser, to_queue, logger_printer):
    s_info = ''
    while 1:
        pser.write("WQKL")
        s_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        s_info += tmp
        m_ram = re.search("C", s_info)

        if m_ram:
            logger_printer.info("-" * 50)
            logger_printer.info(m_ram.group(0))
            logger_printer.info("Program enters transmission mode...")
            return Err_ok

        if not to_queue.empty():
            return Err_timeout


def getc(size, timeout=1):
    time.sleep(0.1)
    return ser.read(size) or None


def putc(data, timeout=1):
    return ser.write(data) or None


def status_update_0(total_packets, success_count, error_count):
    if total_packets % 10 == 0:
        print '.',


def status_update_1(total_packets, success_count, error_count):
    if total_packets % 10 == 0:
        print '.',


@timeout_set(15, time_out_queue)
def burn_test_bin(s_port, r_file, to_queue, logger_printer):
    logger_printer.info("Transferring %s..." % r_file)

    try:
        stream = open(r_file, 'rb')
    except Exception, e_info:
        logger_printer.info(str(e_info))
        logger_printer.info("Cannot load file, please check the file path and retry. Press <enter> to exit")
        return Err_fail

    x_modem = xmodem.XMODEM(getc, putc, mode='xmodem1k')
    xmodem_send = x_modem.send(stream, callback=status_update_0)
    logger_printer.info("Transmit result: %s" % str(xmodem_send))

    s_info = ''
    while 1:
        s_info += s_port.read(1)
        bytes2read = s_port.inWaiting()
        tmp = s_port.read(bytes2read)
        s_info += tmp

        m_test_pass = re.search(r"test passed", s_info)
        m_test_fail = re.search(r"failed:(.*)", s_info)

        if m_test_pass:
            logger_printer.info("Pass mem check...")
            return Err_ok

        if m_test_fail:
            logger_printer.info("Mem check failed: %s" % m_test_fail.group(1))
            return (Err_fail, m_test_fail.group(1))

        if not to_queue.empty():
            return Err_timeout


def psram_mem_check(pser, to_queue, logger_printer):
    test_bin = "memtest.bin"

    power_down_up(pser)
    if init_send(pser, to_queue, logger_printer):
        logger_info = (r"Failed enter transmission mode")
        logger_printer.info(logger_info)
        return Err_fail
    logger_printer.info(r"Transmission mode enter successfully.")

    return_value = burn_test_bin(pser, test_bin, to_queue, logger_printer)
    if Err_ok == return_value:
        logger_info = (r"Psram Mem Check Pass")
        logger_printer.info(logger_info)
        return Err_ok
    elif isinstance(return_value, tuple):
        err_code, err_info = return_value[0], return_value[1]
        logger_info = (r"Psram Mem Check Fail <%s>" % err_info)
        logger_printer.info(logger_info)
        return Err_fail
    else:
        logger_info = (r"Psram Mem Check Failed, error code <%s>" % str(return_value))
        logger_printer.info(logger_info)
        return Err_fail


@timeout_set(5, time_out_queue)
def ktj_dut_gpio_check(pser, to_queue, logger_printer):
    check_done_cnt = 0
    gpio_set_status_list = range(2)  # [0, 1]
    for each_status in gpio_set_status_list:
        gpio_get_list, gpio_num_list, gpio_status_list = [], [], []
        for each_dut_gpio in DictKTJGPIOMapping.keys():
            gpio_num_list.append(each_dut_gpio)
            gpio_status_list.append(each_status)

            ret_dut_gpio_set = gpio_level_set(pser, each_dut_gpio, each_status, to_queue)
            if ret_dut_gpio_set:
                logger_printer.info("Error info in ktj dut gpio set: %s" % str(ret_dut_gpio_set))
                logger_info = (r"KTJ dut gpio %d set status %d failed" % (each_dut_gpio, each_status))
                logger_printer.info(logger_info)
                return Err_fail

            each_ptk48_gpa_index = DictKTJGPIOMapping[each_dut_gpio]
            ret_ptk48_gpio_get = k48_low_voltage_pin_status_get(pser, each_ptk48_gpa_index, 1, to_queue)
            if ret_ptk48_gpio_get not in ["00", "01"]:
                logger_info = ("Error info in ktj ptk48 gpio get: %s" % str(ret_ptk48_gpio_get))
                logger_printer.info(logger_info)
                return Err_fail
            gpio_get_list.append(int(ret_ptk48_gpio_get, 16))

        if gpio_status_list == gpio_get_list:
            check_done_cnt += 1
            logger_info = r"KTJ GPIO %s check status %s pass" % (str(gpio_num_list), str(gpio_status_list))
        else:
            logger_info = (r"KTJ GPIO %s check status %s fail to status %s" %
                           (str(gpio_num_list), str(gpio_status_list), str(gpio_get_list)))
        logger_printer.info(logger_info)

    if 2 == check_done_cnt:
        logger_info = (r"KTJ GPIO Check Pass")
        logger_printer.info(logger_info)
        return Err_ok
    else:
        logger_info = (r"KTJ GPIO Check Fail")
        logger_printer.info(logger_info)
        return Err_fail


@timeout_set(2, time_out_queue)
def ktj_dut_channel_voltage_adc_data_get(pser, adc_voltage_channel, to_queue):
    return_str, cs_info = '', ''
    cmd_ktj_dut_channel_voltage_get_str = command_foramt_convert(adc_voltage_channel, "<", "I")
    str_ktj_dut_channel_voltage_get = (r"23 23 00 00 00 00 00 00 00 00 00 00 00 00 "
                                       r"03 00 00 00 42 00 00 00 0a 00 00 00 42 00 04 00 04 00 %s 40 40" %
                                       cmd_ktj_dut_channel_voltage_get_str)
    command_str_ktj_dut_channel_voltage_get = str_ktj_dut_channel_voltage_get.replace(" ", "")

    pser.write(binascii.a2b_hex(command_str_ktj_dut_channel_voltage_get))

    m_tt_comp = re.compile(r"2323[0]{24}\w{8}01[0]{6}\w{8}420004000400(\w{8})4040")

    while 1:
        cs_info += pser.read(1)
        bytes2read = pser.inWaiting()
        tmp = pser.read(bytes2read)
        cs_info += tmp

        m_tt = m_tt_comp.search(cs_info.encode("hex"))

        if m_tt:
            return_str = m_tt.group(1)
            return_raw_hex_str = return_str.decode("hex")
            unpack_format = struct.Struct("<i")  # int32_t
            return_voltage_value = (unpack_format.unpack(return_raw_hex_str))[0]
            actual_voltage = float(return_voltage_value * voltage_factor)
            return actual_voltage

        if not to_queue.empty():
            return Err_timeout


def ktj_dut_channel_voltage_check(pser, to_queue, logger_printer):
    check_done_cnt, list_channel_voltage = 0, []
    for each_channel_num in ListKTJVoltageChannel:
        each_channel_voltage = ktj_dut_channel_voltage_adc_data_get(pser, each_channel_num, to_queue)
        if isinstance(each_channel_voltage, float):
            list_channel_voltage.append(each_channel_voltage)
            logger_info = r"KTJ channel %d voltage get %fV" % (each_channel_num, each_channel_voltage)
            logger_printer.info(logger_info)
        else:
            logger_info = ("Error info in ktj dut channel voltage get: <%s>" % str(each_channel_voltage))
            logger_printer.info(logger_info)
            return Err_fail

    for each_index in range(len(list_channel_voltage)):
        each_channel_voltage = list_channel_voltage[each_index]
        each_channel_voltage_range_list = ktj_channel_range_list[each_index]
        if each_channel_voltage_range_list[0] <= each_channel_voltage <= each_channel_voltage_range_list[1]:
            check_done_cnt += 1
        else:
            logger_info = (r"KTJ channel %d voltage %fV out of range %s" %
                           (ListKTJVoltageChannel[each_index],
                            each_channel_voltage,
                            str(each_channel_voltage_range_list)))
            logger_printer.info(logger_info)

    if check_done_cnt == len(ListKTJVoltageChannel):
        logger_info = (r"KTJ Channel Voltage Check Pass")
        logger_printer.info(logger_info)
        return Err_ok
    else:
        logger_info = (r"KTJ Channel Voltage Check Fail")
        logger_printer.info(logger_info)
        return Err_fail


def pass_printer():
    pass_printer_list = [
        "  # # #                   #                  # # #                # # #          ",
        " #      #               #   #              #                    #                ",
        " #       #             #     #            #                    #                 ",
        " #      #             #       #            #                    #                ",
        " # # #               # # # # # #            # # # #              # # # #         ",
        " #                   #         #                   #                    #        ",
        " #                   #         #                    #                    #       ",
        " #                   #         #                   #                    #        ",
        " #                   #         #             # # #                # # #          "
    ]
    print ("-" * 100)
    for each_line in pass_printer_list:
        if 100 > len(each_line):
            each_line += " " * (100 - len(each_line))
        print (each_line)
    print ("-" * 100)


def fail_printer():
    fail_printer_list = [
        " # # # # #                #                  # # #                  # #          ",
        " #                      #   #                  #                    #            ",
        " #                     #     #                 #                    #            ",
        " #                    #       #                #                    #            ",
        " # # # #             # # # # # #               #                    #            ",
        " #                   #         #               #                    #            ",
        " #                   #         #               #                    #            ",
        " #                   #         #               #                    #       #    ",
        " #                   #         #             # # #                  # # # # #    "
    ]
    print ("-" * 100)
    for each_line in fail_printer_list:
        if 100 > len(each_line):
            each_line += " " * (100 - len(each_line))
        print (each_line)
    print ("-" * 100)


if __name__ == '__main__':

    loop_times = 0
    board_lable = ''

    while 1:

        signal.signal(signal.SIGINT, signal_exit)
        signal.signal(signal.SIGTERM, signal_exit)

        config_file = r"config_production_test.ini"
        data_trans_queue = Queue.Queue(maxsize=10)
        init_str = "entry_sbl_cli"
        base_str = "bootm fw_mode=1"
        voltage_factor = (3.2 / 512)
        dict_filter_data_info = collections.OrderedDict()
        dict_results_summary, dump_data_str = {}, ''
        nf_detection_times, csr_retry_cnt, cur_gain_cnt, tdsb_charge_time_interval = 3, 3, 0, 0
        tmi_list, ktj_channel_range_list = [], []
        first_cur_gain, return_result = None, None
        str_vendor_id, str_chip_code, str_module_type, str_chip_mmid = None, None, None, None
        csr_threshold, pre_charge_voltage, pro_charge_voltage, voltage_rise = None, None, None, None

        config_handler = configobj.ConfigObj(config_file)

        sport_num = config_handler["serial config"]["serial_port_num"]
        baudrate_value = int(config_handler["serial config"]["baud_rate"])

        label_enable = int(config_handler["test config"]["label_enable"])
        loop_mode = int(config_handler["test config"]["loop_mode"])
        reset_mode = config_handler["test config"]["reset_mode"]
        reboot_method = config_handler["test config"]["reboot_method"]

        vendor_id_enable = int(config_handler["test parameters config"]["vendor_id_enable"])
        vendor_id = config_handler["test parameters config"]["vendor_id"]
        str_mac_addr_burn = config_handler["test parameters config"]["burned_mac_address"]

        phase_list = list(config_handler["test parameters config"]["phase"])
        gold_ppm = int(float(config_handler["test parameters config"]["gold_ppm"]))
        phy_power_att = int(config_handler["test parameters config"]["phy_power_att"])
        device_type = int(config_handler["test parameters config"]["device_type"])
        filter_gpio_num = int(DictFilterGpio[device_type])
        software_version = config_handler["test parameters config"]["software_version"]
        filter_type = int(config_handler["test parameters config"]["filter_type"])
        global_nid = int(config_handler["test parameters config"]["global_nid"])

        noise_floor_threshold = float(config_handler["threshold config"]["noise_floor_threshold"])
        tx_power_threshold = float(config_handler["threshold config"]["tx_power_threshold"])
        rx_rssi_threshold = float(config_handler["threshold config"]["rx_rssi_threshold"])
        dut_real_ppm_max = float(config_handler["threshold config"]["dut_real_ppm_max"])
        dut_real_ppm_min = float(config_handler["threshold config"]["dut_real_ppm_min"])
        rx_snr_threshold = float(config_handler["threshold config"]["rx_snr_threshold"])
        hpf_700k_threshold = float(config_handler["threshold config"]["hpf_700k_threshold"])
        hpf_2m_threshold = float(config_handler["threshold config"]["hpf_2m_threshold"])
        hpf_flat_threshold = float(config_handler["threshold config"]["hpf_flat_threshold"])

        tmi4_csr_enable = int(config_handler["threshold config"]["tmi4_csr_enable"])
        tmi4_csr_threshold = int(config_handler["threshold config"]["tmi4_csr_threshold"])
        ext_tmi3_csr_enable = int(config_handler["threshold config"]["ext_tmi3_csr_enable"])
        ext_tmi3_csr_threshold = int(config_handler["threshold config"]["ext_tmi3_csr_threshold"])

        charge_timespan = int(float(config_handler["threshold config"]["charge_timespan"]))
        charge_voltage_threshold = float(config_handler["threshold config"]["charge_voltage_threshold"])

        spur_max_limit_cnt = int(config_handler["threshold config"]["spur_max_limit_cnt"])
        spur_remove_tone_cnt = int(config_handler["threshold config"]["spur_remove_tone_cnt"])

        channel_0_voltage_list = config_handler["threshold config"]["channel_0_range"]
        ch0_voltage_lower_limit = float(channel_0_voltage_list[0])
        ch0_voltage_upper_limit = float(channel_0_voltage_list[1])

        channel_1_voltage_list = config_handler["threshold config"]["channel_1_range"]
        ch1_voltage_lower_limit = float(channel_1_voltage_list[0])
        ch1_voltage_upper_limit = float(channel_1_voltage_list[1])

        channel_2_voltage_list = config_handler["threshold config"]["channel_2_range"]
        ch2_voltage_lower_limit = float(channel_2_voltage_list[0])
        ch2_voltage_upper_limit = float(channel_2_voltage_list[1])

        channel_3_voltage_list = config_handler["threshold config"]["channel_3_range"]
        ch3_voltage_lower_limit = float(channel_3_voltage_list[0])
        ch3_voltage_upper_limit = float(channel_3_voltage_list[1])

        ktj_gpio_check_enable = int(float(config_handler["ktj pt config"]["ktj_gpio_check_enable"]))
        ktj_channel_voltage_check_enable = int(float(config_handler["ktj pt config"]
                                                     ["ktj_channel_voltage_check_enable"]))

        channel_0_voltage_list = config_handler["ktj pt config"]["ktj_channel_0_range"]
        ktj_channel_range_list.append([float(channel_0_voltage_list[0]),
                                       float(channel_0_voltage_list[1])])

        channel_1_voltage_list = config_handler["ktj pt config"]["ktj_channel_1_range"]
        ktj_channel_range_list.append([float(channel_1_voltage_list[0]),
                                       float(channel_1_voltage_list[1])])

        channel_2_voltage_list = config_handler["ktj pt config"]["ktj_channel_2_range"]
        ktj_channel_range_list.append([float(channel_2_voltage_list[0]),
                                       float(channel_2_voltage_list[1])])

        channel_3_voltage_list = config_handler["ktj pt config"]["ktj_channel_3_range"]
        ktj_channel_range_list.append([float(channel_3_voltage_list[0]),
                                       float(channel_3_voltage_list[1])])

        channel_5_voltage_list = config_handler["ktj pt config"]["ktj_channel_5_range"]
        ktj_channel_range_list.append([float(channel_5_voltage_list[0]),
                                       float(channel_5_voltage_list[1])])

        read_fw_ver_flag = int(config_handler["test case flag config"]["read_fw_ver_flag"])
        read_chip_id_flag = int(config_handler["test case flag config"]["read_chip_id_flag"])
        read_mac_address_flag = int(config_handler["test case flag config"]["read_mac_address_flag"])
        burned_mac_address_flag = int(config_handler["test case flag config"]["burned_mac_address_flag"])
        noise_floor_detection_flag = int(config_handler["test case flag config"]["noise_floor_detection_flag"])
        tx_rx_loopback_detection_flag = int(config_handler["test case flag config"]["tx_rx_loopback_detection_flag"])
        flatness_detection_flag = int(config_handler["test case flag config"]["flatness_detection_flag"])
        sen_csr_detection_flag = int(config_handler["test case flag config"]["sen_csr_detection_flag"])
        led_control_flag = int(config_handler["test case flag config"]["led_control_flag"])
        zero_cross_detection_flag = int(config_handler["test case flag config"]["zero_cross_detection_flag"])
        channel_voltage_detection_flag = int(config_handler["test case flag config"]["channel_voltage_detection_flag"])
        gpio_status_detection_flag = int(config_handler["test case flag config"]["gpio_status_detection_flag"])
        tdsb_voltage_detection_flag = int(config_handler["test case flag config"]["tdsb_voltage_detection_flag"])
        psram_mem_detection_flag = int(config_handler["test case flag config"]["psram_mem_detection_flag"])

        if 1 <= loop_times and 2 == loop_mode:  # loop mode only enable 1st time label here
            pass
        else:
            if label_enable:
                board_lable = raw_input("Test starts...\nPlease input board label: ")
            else:
                board_lable = "test"

        time_stamp = time.strftime("%Y-%m-%d %X")
        time_stamp = time_stamp.replace(" ", "-")
        time_stamp = time_stamp.replace(":", "-")

        log_folder = r".\log_production_test" + "\\" + board_lable + "_" + time_stamp
        if not os.path.exists(log_folder):
            os.makedirs(log_folder)

        try:
            ser = serial.Serial(port='com' + sport_num, baudrate=baudrate_value, timeout=0.3)
        except Exception, ser_info:
            print str(ser_info)
            raw_input("Error open Serial Port COM%s!!! Press <enter> to Close it and retry..." % sport_num)
            sys.exit()
        print("Serial port COM%s opened, please press <RST> button on the chip..." % sport_num)

        if reset_mode == "1":  # soft reset
            if reboot_method == "1":
                print ("Power Reboot...")
                power_down_up(ser)
            else:
                print ("Soft Reset...")
                rst_low_high(ser)
        elif reset_mode == "0":  # hard reset
            print ("Hard Reset, Please Press <RST> Button On The Chip To Continue The Operation...")
        else:
            raw_input("Please specified the reset mode...<enter> to exit!")
            sys.exit()

        mode_str = base_str + '\n'
        return_result = enter_test_mode(ser, init_str, mode_str, time_out_queue)
        if return_result:
            raw_input("TimeOut Error: Enter Test Mode Failed...<enter> to exit!")
            sys.exit()

        # --------------------------------------------------------------------------------read chip id
        list_chip_info = read_chip_info(ser, time_out_queue)
        if isinstance(list_chip_info, int):  # Err code returned
            sys.exit()
        chip_type_str = list_chip_info[0][1]  # "chip type", ****)
        chip_id_str = list_chip_info[1][1]  # "chip id", ****)

        log_name = board_lable + "_" + chip_id_str + "_" + chip_type_str + "_" + time_stamp
        logger = logging.getLogger(sport_num)
        logger.setLevel(logging.DEBUG)  # logging level: debug < info < warning < error < critical
        logfile = log_folder + "\\" + log_name + ".log"
        fh = logging.FileHandler(logfile, mode='a')
        fh.setLevel(logging.DEBUG)  # file level
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)  # console level: DEBUG\INFO
        formatter = logging.Formatter("%(asctime)s - %(levelname)s: %(message)s")
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(ch)

        # Entry of Test
        # --------------------------------------------------------------------------------efuse lock
        print ("\r\n" + "-" * 30 + "Efuse Lock" + r"-" * 30 + "\r\n")
        str_efuse_prog_lock = efuse_prog_bit_lock(ser, time_out_queue)
        if Err_timeout == str_efuse_prog_lock:
            dict_results_summary["Test: efuse_lock"] = "fail"
            str_efuse_check_result = ("Test <efuse_lock> TimeOut...")
        elif str_efuse_prog_lock == "00":
            str_efuse_check_result = ("Efuse Program Done Bit already 1, Check Complete!")
        elif str_efuse_prog_lock == "01":
            str_efuse_check_result = ("Efuse Program Done Bit original 0, Write Bit 1, Lock Complete!")
        else:
            str_efuse_check_result = ("Return Value Error : %s , Please Check..." % str_efuse_prog_lock)
        logger.info(str_efuse_check_result)

        if tdsb_voltage_detection_flag:
            print ("\r\n" + "-" * 30 + "TDSB Voltage Detection" + r"-" * 30 + "\r\n")

            # for tdsb initial charge
            tdsb_return_value = dut_charge_voltage_detection(ser, logger, time_out_queue, 2, 0)
            if Err_fail == tdsb_return_value:
                logger.info("TDSB Voltage Detection Failed")
                dict_results_summary["Test: tdsb_voltage_detection"] = "fail"
            elif Err_timeout == tdsb_return_value:
                logger.info("TDSB Voltage Detection TimeOut")
                dict_results_summary["Test: tdsb_voltage_detection"] = "fail"
            else:
                logger.info("TDSB Voltage Detection passed")

        # --------------------------------------------------------------------------------vendor id set
        if vendor_id_enable:
            print ("\r\n" + "-" * 30 + "Vendor ID Set" + r"-" * 30 + "\r\n")
            vid_return_value = vendor_id_set(ser, vendor_id, time_out_queue)
            if Err_fail == vid_return_value:
                dict_results_summary["Test: vendor_id_set"] = "fail"
                str_vendor_id_set_result = ("Test <vendor_id_set> Failed...")
            elif Err_timeout == vid_return_value:
                dict_results_summary["Test: vendor_id_set"] = "fail"
                str_vendor_id_set_result = ("Test <vendor_id_set> TimeOut...")
            else:
                str_vendor_id_set_result = ("Set vendor id: %s completes." % vendor_id)
            logger.info(str_vendor_id_set_result)

        # --------------------------------------------------------------------------------read fw version, id info
        # read vendor id, chip code, module type, chip mmid
        try:
            print ("\r\n" + "-" * 30 + "Read ID Info" + r"-" * 30 + "\r\n")
            str_vendor_id = vendor_id_get(ser, time_out_queue)
            logger.info(r"Read Vendor_id: %s" % str_vendor_id)
            str_chip_code = chip_code_get(ser, time_out_queue)
            logger.info(r"Read Chip_code: %s" % str_chip_code)
            str_module_type = module_type_get(ser, time_out_queue)
            logger.info(r"Read Module_type: %s" % DictModuleType.setdefault(str_module_type, "Null"))
            str_chip_mmid = chip_mmid_get(ser, time_out_queue)
            logger.info(r"Read Chip_mmid: %s" % str_chip_mmid)
        except Exception, excp_info:
            logger.info(str(excp_info))

        if read_fw_ver_flag:
            print ("\r\n" + "-" * 30 + "Read FW Version" + r"-" * 30 + "\r\n")
            str_fw_ver = read_fw_ver(ser, time_out_queue)
            if Err_timeout == str_fw_ver:
                dict_results_summary["Test: read_fw_version"] = "fail"
                logger.info("Test <read_fw_version> TimeOut...")
            else:
                logger.info(("fw version", str_fw_ver))
                # fw version check
                fw_version_pattern = re.match(r"(\w+)-(\w+)-(\d+.\d+.\d+.\d+)", str_fw_ver)
                if fw_version_pattern:
                    device_name = DictModuleType[DictDeviceTypeNumMapping[device_type]]
                    read_module_type_ver_str = fw_version_pattern.group(2)
                    read_software_ver_str = fw_version_pattern.group(3)
                    if (software_version == read_software_ver_str and
                            read_module_type_ver_str.find(device_name) > 0):
                        logger.info(r"Software version <%s> <%s> check complete!" %
                                    (device_name,
                                     software_version))
                    else:
                        logger.info(r"Software version <%s> <%s> mismatched, please check..." %
                                    (device_name,
                                     software_version))
                        sys.exit()
                else:
                    logger.info(r"Fw version format <%s> mismatched, please check..." % str_fw_ver)
                    sys.exit()
            print

        if read_chip_id_flag:
            for each_chip_info in list_chip_info:
                logger.info(each_chip_info)

        # --------------------------------------------------------------------------------Read Original Mac Address
        if read_mac_address_flag:
            print ("\r\n" + "-"*30 + "Read Original Mac Address" + r"-"*30 + "\r\n")
            read_origin_ma_str = mac_addr_read(ser, time_out_queue)
            if Err_timeout == read_origin_ma_str:
                dict_results_summary["Test: read_mac_addr_1"] = "fail"
                logger.info("Test <read_mac_addr> TimeOut...")
            else:
                logger.info("Original Mac Address %s" % read_origin_ma_str)
            time.sleep(0.5)

        # --------------------------------------------------------------------------------Burned Mac Address
        if burned_mac_address_flag:
            print ("\r\n" + "-" * 30 + "Burned and Read Mac Address" + r"-" * 30 + "\r\n")
            # Burn Mac Address
            burn_ma_str = mac_addr_burn(ser, str_mac_addr_burn, time_out_queue)
            if Err_timeout == burn_ma_str:
                dict_results_summary["Test: burn_mac_addr"] = "fail"
                logger.info("Test <burn_mac_addr> TimeOut...")
            else:
                logger.info("Burned Mac Address %s" % burn_ma_str)
            time.sleep(0.5)
            # Read Mac Address
            read_ma_str = mac_addr_read(ser, time_out_queue)
            if Err_timeout == read_ma_str:
                dict_results_summary["Test: read_mac_addr_2"] = "fail"
                logger.info("Test <read_mac_addr> TimeOut...")
            else:
                logger.info("Read Mac Address %s" % read_ma_str)
            time.sleep(0.5)

        # --------------------------------------------------------------------------------noise floor calculate
        if noise_floor_detection_flag:
            print ("\r\n" + "-"*30 + "Calculate Noise Floor" + r"-"*30 + "\r\n")
            nf_list = []
            for d_i in range(nf_detection_times):
                value_of_nf = calc_noise_floor(ser, time_out_queue)
                time.sleep(0.4)
                if value_of_nf > 0:
                    nf_list.append(value_of_nf)
                elif Err_timeout == value_of_nf:
                    logger.info("Test <noise_floor_calculate> TimeOut...")
                    break

            if nf_detection_times == len(nf_list):
                min_nf_value = min(nf_list)
                if noise_floor_threshold >= min_nf_value:
                    logger.info("Value of Noise Floor is %d" % min_nf_value)
                else:
                    logger.info("Value of Noise Floor(%f) is large than %f" % (min_nf_value, noise_floor_threshold))
                    dict_results_summary["Test: noise_floor_calculate"] = "fail"
                    logger.info("Test <noise_floor_calculate> Failed...")
            else:
                dict_results_summary["Test: noise_floor_calculate"] = "fail"

        # --------------------------------------------------------------------------------set global nid for txrx
        print ("\r\n" + "-" * 30 + "Global Nid Set" + r"-" * 30 + "\r\n")
        return_nid_value = global_nid_set(ser, global_nid, time_out_queue)
        if int(0xff) == return_nid_value:
            logger.info("Set global nid failed, please check.")
            sys.exit()
        elif Err_timeout == return_nid_value:
            logger.info("Set global nid TimeOut, please check.")
            sys.exit()
        else:
            logger.info("Set global nid to %d for communication test." % return_nid_value)

        for each_phase in phase_list:
            phase_str = DictPhase[each_phase]
            print("\r\n" + "-" * 30 + ("Channel %s Test" % each_phase) + "-" * 30 + "\r\n")
        # --------------------------------------------------------------------------------Tx Rx Loopback Test
            if tx_rx_loopback_detection_flag:
                logger.info("-* " * 20)
                logger.info("Channel %s TXRX Loopback Test" % each_phase)
                logger.info("-* " * 20)

                return_result = txrx_process(phase_str, data_trans_queue, gold_ppm, logger, time_out_queue)
                if Err_timeout == return_result:
                    dict_results_summary["Test: txrx_loopback_phase_%s" % each_phase] = "fail"
                    logger.info("Test <txrx_loopback_phase_%s> TimeOut..." % each_phase)
                elif Err_fail == return_result:
                    dict_results_summary["Test: txrx_loopback_phase_%s" % each_phase] = "fail"
                    logger.info("Test <txrx_loopback_phase_%s> Failed..." % each_phase)
                time.sleep(1)

        for each_phase in phase_list:
            phase_str = DictPhase[each_phase]
            print("\r\n" + "-" * 30 + ("Channel %s Test" % each_phase) + "-" * 30 + "\r\n")
        # ---------------------------------------------------------------------------flatness detection tx psg sof 3 a
            if flatness_detection_flag:
                print
                logger.info("-* " * 20)
                logger.info("Channel %s Flatness Detection Test" % each_phase)
                logger.info("-* " * 20)

                for gpio_value in range(2):  # 0 or 1
                    print
                    if filter_type:  # fixed 700K filter: 0 / dynamic filter(700K/2M): 1
                        phase_filter_gpio_control(ser, gpio_value, filter_gpio_num, logger)

                    return_flatness_test = flatness_test(ser, each_phase, phase_str, board_lable,
                                                         gpio_value, logger, loop_times,
                                                         time_out_queue, log_folder)

                    if isinstance(return_flatness_test, list):
                        var_value_of_csi_dump = return_flatness_test[1]

                        # differentiate band 32-120: 700K and 2M spectrogram
                        cur_filter_info_tuple = dict_filter_data_info[gpio_value]
                        cur_var_80_120, cur_avg_32_40, cur_avg_40_80, cur_avg_80_120 = cur_filter_info_tuple

                        if 0 == gpio_value:  # differentiate 700K filter
                            if ((hpf_700k_threshold <= cur_avg_80_120 - cur_avg_32_40 <= hpf_2m_threshold) and
                                    (hpf_flat_threshold >= cur_var_80_120) and
                                    (cur_avg_32_40 < cur_avg_40_80 < cur_avg_80_120)):
                                filter_type_value = "700"
                            else:
                                filter_type_value = "Unknown "

                        else:  # differentiate 2M filter
                            if ((hpf_2m_threshold <= cur_avg_80_120 - cur_avg_32_40) and
                                    (hpf_flat_threshold >= cur_var_80_120) and
                                    (cur_avg_32_40 < cur_avg_40_80 < cur_avg_80_120)):
                                filter_type_value = "2000"
                            else:
                                filter_type_value = "Unknown "

                        logger.info("GPIO %d, Status: %d, Filter Type is %sK" %
                                    (filter_gpio_num, gpio_value, filter_type_value))
                        logger.info("Variance of Flatness Test is %f" % var_value_of_csi_dump)

                        # results summary
                        logger_flatness_info = ''
                        if not filter_type:  # 0 == filter_type  # fixed 700K filter
                            if "700" == filter_type_value:
                                logger_flatness_info = r"Differentiate 700K Filter ===> PASS!!!!"
                            else:
                                logger_flatness_info = r"Differentiate 700K Filter ===> FAIL!!!!"
                        else:  # 1 == filter_type  # dynamic filter(700K/2M)
                            if 0 == gpio_value:
                                if "700" == filter_type_value:
                                    logger_flatness_info = r"Differentiate 700K Filter ===> PASS!!!!"
                                else:
                                    logger_flatness_info = r"Differentiate 700K Filter ===> FAIL!!!!"
                            elif 1 == gpio_value:
                                if "2000" == filter_type_value:
                                    logger_flatness_info = r"Differentiate 2M Filter ===> PASS!!!!"
                                else:
                                    logger_flatness_info = r"Differentiate 2M Filter ===> FAIL!!!!"

                        if logger_flatness_info.find(r"FAIL") >= 0:
                            dict_results_summary["Test: gpio_%d_status_%d_flatness_detection_phase_%s" %
                                                 (filter_gpio_num, gpio_value, each_phase)] = "fail"
                            logger.info("Test <gpio_%d_status_%d_flatness_detection_phase_%s> Failed..." %
                                        (filter_gpio_num, gpio_value, each_phase))
                        logger.info(logger_flatness_info)

                    elif Err_fail == return_flatness_test:
                        dict_results_summary["Test: gpio_%d_status_%d_flatness_detection_phase_%s" %
                                             (filter_gpio_num, gpio_value, each_phase)] = "fail"
                        logger.info("Test <gpio_%d_status_%d_flatness_detection_phase_%s> Failed..." %
                                    (filter_gpio_num, gpio_value, each_phase))
                    elif Err_timeout == return_flatness_test:
                        dict_results_summary["Test: gpio_%d_status_%d_flatness_detection_phase_%s" %
                                             (filter_gpio_num, gpio_value, each_phase)] = "fail"
                        logger.info("Test <gpio_%d_status_%d_flatness_detection_phase_%s> TimeOut..." %
                                    (filter_gpio_num, gpio_value, each_phase))
                    else:
                        pass

                    if not filter_type:  # Only test once when fixed filter
                        break
                    time.sleep(1)

        for each_phase in phase_list:
            tmi_list = []
            phase_str = DictPhase[each_phase]
            print("\r\n" + "-" * 30 + ("Channel %s Test" % each_phase) + "-" * 30 + "\r\n")
        # --------------------------------------------------------------------------------sen/csr tx sg sof 4 a
            if sen_csr_detection_flag:
                print
                logger.info("-* " * 20)
                logger.info("Channel %s Sensitivity and Communication Success Rate Detection Test" % each_phase)
                logger.info("-* " * 20)

                if tmi4_csr_enable:
                    tmi_list.append(4)
                if ext_tmi3_csr_enable:
                    tmi_list.append(18)

                for tmi_value in tmi_list:
                    if 4 == tmi_value:
                        csr_threshold = tmi4_csr_threshold
                    elif 18 == tmi_value:
                        csr_threshold = ext_tmi3_csr_threshold

                    for retry_i in range(csr_retry_cnt):
                        logger.info("CSR Test %d time, Down %d dB Power: %s" %
                                    (retry_i + 1, phy_power_att, DictTmi[tmi_value]))
                        time.sleep(0.5)
                        value_of_sen_csr = sen_csr_detection(ser, phase_str, tmi_value, phy_power_att, time_out_queue)
                        if Err_timeout == value_of_sen_csr:
                            dict_results_summary["Test: sensitivity_csr_phase_%s" % each_phase] = "fail"
                            logger.info("Test <sensitivity_csr_phase_%s> TimeOut..." % each_phase)
                            break
                        elif csr_threshold > value_of_sen_csr:
                            if csr_retry_cnt == retry_i + 1:
                                dict_results_summary["Test: sensitivity_csr_phase_%s: %d%% less than %d%%" %
                                                     (each_phase, value_of_sen_csr, csr_threshold)] = "fail"
                            else:
                                logger.info("Test: sensitivity_csr_phase_%s: %d%% less than %d%%" %
                                            (each_phase, value_of_sen_csr, csr_threshold))
                        else:
                            logger.info("Sensitivity and Communication Success Rate is %d%%" % value_of_sen_csr)
                            break
                    print

        # --------------------------------------------------------------------------------Tx Rx LED lights on and out
        if led_control_flag:
            print ("\r\n" + "-" * 30 + "Tx Rx LED Contorl" + r"-" * 30 + "\r\n")
            led_control(ser, logger)

        # --------------------------------------------------------------------------------zero cross detection
        if zero_cross_detection_flag:
            print ("\r\n" + "-" * 30 + "Zero Cross Detection" + r"-" * 30 + "\r\n")

            zc_return_value = zero_cross_detection(ser, time_out_queue)
            if not zc_return_value:
                logger.info("Zero Cross Detection passed")
            elif Err_timeout == zc_return_value:
                logger.info("Zero Cross Detection TimeOut")
                dict_results_summary["Test: zero_cross_detection"] = "fail"
            elif Err_fail == zc_return_value:
                logger.info("Zero Cross Detection Failed")
                dict_results_summary["Test: zero_cross_detection"] = "fail"

        # --------------------------------------------------------------------------------channel voltage detection
        if channel_voltage_detection_flag:
            print ("\r\n" + "-" * 30 + "Channel Voltage Detection" + r"-" * 30 + "\r\n")

            cv_return_value = channel_voltage_detection(ser, logger, time_out_queue)
            if Err_fail == cv_return_value:
                logger.info("Channel Voltage Detection Failed")
                dict_results_summary["Test: channel_volatge_detection"] = "fail"
            elif Err_timeout == cv_return_value:
                logger.info("Channel Voltage Detection TimeOut")
                dict_results_summary["Test: channel_volatge_detection"] = "fail"
            else:
                logger.info("Channel Voltage Detection passed")

        # --------------------------------------------------------------------------------gpio status detection
        if gpio_status_detection_flag:
            print ("\r\n" + "-" * 30 + "GPIO Status Detection" + r"-" * 30 + "\r\n")

            gpio_return_value = low_voltage_pin_status_detection(ser, logger)
            if Err_fail == gpio_return_value:
                logger.info("GPIO Status Detection Failed")
                dict_results_summary["Test: gpio_status_detection"] = "fail"
            elif Err_timeout == gpio_return_value:
                logger.info("GPIO Status Detection TimeOut")
                dict_results_summary["Test: gpio_status_detection"] = "fail"
            else:
                logger.info("GPIO Status Detection passed")

        # --------------------------------------------------------------------------------tdsb voltage detection
        if tdsb_voltage_detection_flag:
            print ("\r\n" + "-" * 30 + "TDSB Voltage Detection" + r"-" * 30 + "\r\n")

            tdsb_return_value = dut_charge_voltage_detection(ser, logger, time_out_queue)
            if Err_fail == tdsb_return_value:
                logger.info("TDSB Voltage Detection Failed")
                dict_results_summary["Test: tdsb_voltage_detection"] = "fail"
            elif Err_timeout == tdsb_return_value:
                logger.info("TDSB Voltage Detection TimeOut")
                dict_results_summary["Test: tdsb_voltage_detection"] = "fail"
            else:
                logger.info("TDSB Voltage Detection passed")

        # --------------------------------------------------------------------------------Psram Mem detection
        if psram_mem_detection_flag:
            print ("\r\n" + "-" * 30 + "Psram Mem Detection" + r"-" * 30 + "\r\n")
            if device_type in [2, 3]:  # only CCO has psram for this detection
                psram_check_return_val = psram_mem_check(ser, time_out_queue, logger)
                if psram_check_return_val:
                    dict_results_summary["Test: psram_mem_detection"] = "fail"
        
        # --------------------------------------------------------------------------------KTJ dut detection
        if ktj_gpio_check_enable:
            print ("\r\n" + "-" * 30 + "KTJ GPIO Detection" + r"-" * 30 + "\r\n")
            ktj_gpio_check_return_val = ktj_dut_gpio_check(ser, time_out_queue, logger)
            if ktj_gpio_check_return_val:
                dict_results_summary["Test: ktj_gpio_detection"] = "fail"

        if ktj_channel_voltage_check_enable:
            print ("\r\n" + "-" * 30 + "KTJ Channnel Voltage Detection" + r"-" * 30 + "\r\n")
            ktj_channel_voltage_check_return_val = ktj_dut_channel_voltage_check(ser, time_out_queue, logger)
            if ktj_channel_voltage_check_return_val:
                dict_results_summary["Test: ktj_channel_voltage_detection"] = "fail"

        print ("\r\n" + "#" * 100 + "\r\n")
        print ("#" * 4 + " " * 40 + r"Test Summary" + " " * 40 + "#" * 4)
        print ("\r\n" + "#" * 100)
        if not dict_results_summary:
            logger.info("Pass: Production Test all pass!")
            pass_printer()
        else:
            logger.info("Fail: Production Test fail!")
            fail_printer()
            for key_str in dict_results_summary.keys():
                logger.info("   >>> %s : %s" % (key_str, dict_results_summary[key_str]))

        print
        fh.close()
        ch.close()
        logger.removeHandler(fh)
        logger.removeHandler(ch)
        ser.close()

        if 1 == loop_mode:
            raw_input("Test completes...\nPress <Enter> to continue and <Ctrl Z + Ctrl C> + <Enter> to exit...\r\n")
            plt.clf()
            plt.close()
            loop_times += 1
        elif 2 == loop_mode:
            if label_enable:
                board_lable = raw_input("Test starts...\nPlease input board label: ")
            else:
                board_lable = "test"
            plt.clf()
            plt.close()
            loop_times += 1
            print ("   ------------>>>   Loop time %d...\n" % loop_times)
        elif 3 == loop_mode:
            plt.clf()
            plt.close()
            break
        else:
            plt.clf()
            plt.close()
            print ("Error loop mode, please check...\n")
            sys.exit()
