import os
import pexpect
import re
import subprocess

from abc   import ABCMeta, abstractmethod
from array import array
from util  import *

verbose = False

# the exchanges will be logged to allow looking back for answers
# by the device that we missed
import tempfile
backlogger = tempfile.NamedTemporaryFile("wb")

def resolve_interface(interface):
    """Accept either an adapter name or the address of the adapter to use.

    A USB dongle does not keep the same hci number across a replug, or across
    a reboot, so naming one by number means finding it again by hand every
    time. Give the address instead and it is looked up here.

    :param interface: An adapter name such as hci0, or a BD address
    """
    if not interface or not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$',
                                     interface):
        return interface

    try:
        listing = subprocess.check_output(['hciconfig'],
                                          universal_newlines=True)
    except (OSError, subprocess.CalledProcessError):
        raise Exception('Cannot list Bluetooth adapters to find ' + interface)

    device = None
    for line in listing.splitlines():
        if line and not line[0].isspace():
            device = line.split(':')[0]
        elif interface.upper() in line.upper():
            return device
    raise Exception('No Bluetooth adapter has the address ' + interface)


class NrfBleDfuController(object, metaclass=ABCMeta):
    ctrlpt_handle        = 0
    ctrlpt_cccd_handle   = 0
    data_handle          = 0

    pkt_receipt_interval = 10
    pkt_payload_size     = 20

    # --------------------------------------------------------------------------
    #  Start the firmware update process
    # --------------------------------------------------------------------------
    @abstractmethod
    def start(self):
        pass

    # --------------------------------------------------------------------------
    #  Check if the peripheral is running in bootloader (DFU) or application mode
    #  Returns True if the peripheral is in DFU mode
    # --------------------------------------------------------------------------
    @abstractmethod
    def check_DFU_mode(self):
        pass

    @abstractmethod
    # --------------------------------------------------------------------------
    #  Switch from application to bootloader (DFU)
    # --------------------------------------------------------------------------
    def switch_to_dfu_mode(self):
        pass

    # --------------------------------------------------------------------------
    #  Parse notification status results
    # --------------------------------------------------------------------------
    @abstractmethod
    def _dfu_parse_notify(self, notify):
        pass

    # --------------------------------------------------------------------------
    #  Wait for a notification and parse the response
    # --------------------------------------------------------------------------
    @abstractmethod
    def _wait_and_parse_notify(self):
        pass

    def __init__(self, target_mac, firmware_path, datfile_path, interface=None):
        self.target_mac = target_mac

        self.firmware_path = firmware_path
        self.datfile_path = datfile_path
        self.interface = resolve_interface(interface)

        self.ble_conn = self._spawn_gatttool()
        self.ble_conn.delaybeforesend = 0

    def _spawn_gatttool(self):
        """Start gatttool, on a named adapter if one was asked for."""
        adapter = "-i %s " % self.interface if self.interface else ""
        # The session log lets _dfu_wait_for_notify() find a notification
        # that arrived before it started waiting.
        return pexpect.spawn("gatttool %s-b '%s' -t random --interactive"
                             % (adapter, self.target_mac), logfile=backlogger)

    # --------------------------------------------------------------------------
    #  Start the firmware update process
    # --------------------------------------------------------------------------
    def start(self):
        (_, self.ctrlpt_handle, self.ctrlpt_cccd_handle) = self._get_handles(self.UUID_CONTROL_POINT)
        (_, self.data_handle, _) = self._get_handles(self.UUID_PACKET)

        if verbose:
            print('Control Point Handle: 0x%04x, CCCD: 0x%04x' % (self.ctrlpt_handle, self.ctrlpt_cccd_handle))
            print('Packet handle: 0x%04x' % (self.data_handle))

        # Subscribe to notifications from Control Point characteristic
        self._enable_notifications(self.ctrlpt_cccd_handle)

        # Set the Packet Receipt Notification interval
        prn = uint16_to_bytes_le(self.pkt_receipt_interval)
        self._dfu_send_command(Procedures.SET_PRN, prn)

        self._dfu_send_init()

        self._dfu_send_image()

    # --------------------------------------------------------------------------
    # Initialize: 
    #    Hex: read and convert hexfile into bin_array 
    #    Bin: read binfile into bin_array
    # --------------------------------------------------------------------------
    def input_setup(self):
        print("Sending file " + os.path.split(self.firmware_path)[1] + " to " + self.target_mac)

        if self.firmware_path == None:
            raise Exception("input invalid")

        name, extent = os.path.splitext(self.firmware_path)

        if extent == ".bin":
            self.bin_array = array('B', open(self.firmware_path, 'rb').read())

            self.image_size = len(self.bin_array)
            print("Binary imge size: %d" % self.image_size)
            print("Binary CRC32: %d" % crc32_unsigned(array_to_hex_string(self.bin_array)))

            return

        if extent == ".hex":
            intelhex = IntelHex(self.firmware_path)
            self.bin_array = intelhex.tobinarray()
            self.image_size = len(self.bin_array)
            print("bin array size: ", self.image_size)
            return

        raise Exception("input invalid")

    # --------------------------------------------------------------------------
    # Perform a scan and connect via gatttool.
    # Will return True if a connection was established, False otherwise
    # --------------------------------------------------------------------------
    def scan_and_connect(self, timeout=25):
        if verbose: print("scan_and_connect")

        print("Connecting to %s" % (self.target_mac))

        try:
            self.ble_conn.expect(r'\[LE\]>', timeout=timeout)
        except pexpect.TIMEOUT as e:
            return False

        self.ble_conn.sendline('connect')

        try:
            res = self.ble_conn.expect('.*Connection successful.*', timeout=timeout)
        except pexpect.TIMEOUT as e:
            return False

        return True

    # --------------------------------------------------------------------------
    #  Disconnect from the peripheral and close the gatttool connection
    # --------------------------------------------------------------------------
    def disconnect(self):
        self.ble_conn.sendline('exit')
        self.ble_conn.close()

    def target_mac_increase(self, inc):
        self.target_mac = uint_to_mac_string(mac_string_to_uint(self.target_mac) + inc)

        # Re-start gatttool with the new address
        self.disconnect()
        self.ble_conn = self._spawn_gatttool()
        self.ble_conn.delaybeforesend = 0

    # --------------------------------------------------------------------------
    #  Fetch handles for a given UUID.
    #  Will return a three-tuple: (char handle, value handle, CCCD handle)
    #  Will raise an exception if the UUID is not found
    # --------------------------------------------------------------------------
    def _get_handles(self, uuid):
        self.ble_conn.before = b""
        self.ble_conn.sendline('characteristics')

        try:
            self.ble_conn.expect([uuid], timeout=20)
            handles = re.findall(b'.*handle: (0x....),.*char value handle: (0x....)', self.ble_conn.before)
            (handle, value_handle) = handles[-1]
        except pexpect.TIMEOUT as e:
            raise Exception("UUID not found: {}".format(uuid))

        return (int(handle, 16), int(value_handle, 16), int(value_handle, 16)+1)

    # --------------------------------------------------------------------------
    #  Wait for notification to arrive.
    #  Example format: "Notification handle = 0x0019 value: 10 01 01"
    # --------------------------------------------------------------------------
    def _dfu_wait_for_notify(self):
        # gatttool does not report a lost link directly, and the prompt it
        # leaves behind is not always readable, so cap how long we sit here.
        silent = 0

        while True:
            if verbose: print("dfu_wait_for_notify")

            if not self.ble_conn.isalive():
                print("connection not alive")
                return None

            try:
                index = self.ble_conn.expect('Notification handle = .*? \r\n', timeout=120)

            except pexpect.TIMEOUT:
                #
                # The gatttool does not report link-lost directly.
                # The only way found to detect it is monitoring the prompt '[CON]'
                # and if it goes to '[   ]' this indicates the connection has
                # been broken.
                # In order to get a updated prompt string, issue an empty
                # sendline('').  If it contains the '[   ]' string, then
                # raise an exception. Otherwise, if not a link-lost condition,
                # continue to wait.
                #
                self.ble_conn.sendline('')
                string = self.ble_conn.before
                if isinstance(string, bytes) and b'[   ]' in string:
                    print('Connection lost! ')
                    raise Exception('Connection Lost')
                else:
                    # The notification might have arrived before we started
                    # waiting, and been consumed by an earlier expect():
                    # take the most recent one from the session log.
                    with open(backlogger.name, "rb") as f:
                        content = f.read()
                    last = None
                    for last in re.finditer(rb'Notification handle = 0x[0-9a-fA-F]+ value: ([0-9a-fA-F ]+)', content):
                        pass
                    if last is None:
                        # no notification received
                        return None
                    return last.group(1).split()

            if index == 0:
                after = self.ble_conn.after
                hxstr = after.split()[3:]
                handle = int(float.fromhex(hxstr[0].decode('UTF-8')))
                return hxstr[2:]

            else:
                print("unexpeced index: {0}".format(index))
                return None

    # --------------------------------------------------------------------------
    #  Send a procedure + any parameters required
    # --------------------------------------------------------------------------
    def _dfu_send_command(self, procedure, params=[]):
        if verbose: print('_dfu_send_command')

        cmd  = 'char-write-req 0x%04x %02x' % (self.ctrlpt_handle, procedure)
        cmd += array_to_hex_string(params)

        if verbose: print(cmd)

        self.ble_conn.sendline(cmd)

        # Verify that command was successfully written
        try:
            res = self.ble_conn.expect('Characteristic value was written successfully', timeout=10)
        except pexpect.TIMEOUT as e:
            print("State timeout")

    # --------------------------------------------------------------------------
    #  Send an array of bytes
    # --------------------------------------------------------------------------
    def _dfu_send_data(self, data):
        cmd  = 'char-write-cmd 0x%04x' % (self.data_handle)
        cmd += ' '
        cmd += array_to_hex_string(data)

        if verbose: print(cmd)

        self.ble_conn.sendline(cmd)

    # --------------------------------------------------------------------------
    #  Enable notifications from the Control Point Handle
    # --------------------------------------------------------------------------
    def _enable_notifications(self, cccd_handle):
        if verbose: print('_enable_notifications')

        cmd  = 'char-write-req 0x%04x %s' % (cccd_handle, '0100')

        if verbose: print(cmd)

        self.ble_conn.sendline(cmd)

        # Verify that command was successfully written
        try:
            res = self.ble_conn.expect('Characteristic value was written successfully', timeout=10)
        except pexpect.TIMEOUT as e:
            print("State timeout")
