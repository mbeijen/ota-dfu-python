import sys
import binascii
import re

def bytes_to_uint32_le(bytes):
    return  (bytes[3] << 24) | (bytes[2] << 16) | (bytes[1] <<  8) | (bytes[0] <<  0)

def uint32_to_bytes_le(uint32):
    return [(uint32 >> 0)  & 0xff,
            (uint32 >> 8)  & 0xff,
            (uint32 >> 16) & 0xff,
            (uint32 >> 24) & 0xff]

def uint16_to_bytes_le(value):
    return [(value >> 0 & 0xFF),
            (value >> 8 & 0xFF)]

def zero_pad_array_le(data, padsize):
    for i in range(0, padsize):
        data.insert(0, 0)

def crc32_unsigned(data: bytes):
    return binascii.crc32(data) % (1 << 32)

def mac_string_to_uint(mac):
    parts = mac.split(':')
    ints = [int(x, 16) for x in parts]

    res = 0
    for i in range(0, len(ints)):
        res += (ints[len(ints)-1 - i] << 8*i)

    return res

def uint_to_mac_string(mac):
    ints = [0, 0, 0, 0, 0, 0]
    for i in range(0, len(ints)):
        ints[len(ints)-1 - i] = (mac >> 8*i) & 0xff

    return ':'.join(['{:02x}'.format(x).upper() for x in ints])



def print_progress(iteration, total, prefix='', suffix='', decimals=1, barLength=50):
    """
    Print a nice console progress bar.

    Call in a loop to create terminal progress bar
    @params:
        iteration : current iteration (Int)
        total : total iterations (Int)
        prefix : prefix string (Str)
        suffix  : suffix string (Str)
        decimals : positive number of decimals in percent complete (Int)
        barLength : character length of bar (Int)
    """
    formatStr       = "{0:." + str(decimals) + "f}"
    percents        = formatStr.format(100 * (iteration / float(total)))
    filledLength    = int(round(barLength * iteration / float(total)))
    bar             = '#' * filledLength + '.' * (barLength - filledLength)
    if len(prefix):
        prefix = prefix + ' '
    sys.stdout.write('\r%s[%s] %s%% %s (%d of %d kb)' % (prefix, bar, percents, suffix, iteration/1024, total/1024)),
    if iteration == total:
        sys.stdout.write('\n')
    sys.stdout.flush()
