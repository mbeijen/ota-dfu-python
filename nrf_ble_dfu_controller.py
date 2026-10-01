import os
import asyncio
from abc import ABCMeta, abstractmethod
import logging

from bleak import BleakClient, BleakScanner, BleakGATTCharacteristic

from util import *

logger = logging.getLogger(__name__)

class NrfBleDfuController(object, metaclass=ABCMeta):
    ctrlpt_handle = None
    data_handle = None

    pkt_receipt_interval = 10
    pkt_payload_size = 20

    def __init__(self, target_mac, firmware_path, datfile_path):
        self.target_mac = target_mac
        self.firmware_path = firmware_path
        self.datfile_path = datfile_path
        self.client = None
        self.notification_event = asyncio.Event()
        self.notification_data = None

    @abstractmethod
    def start(self):
        '''Start the firmware update process.'''
        pass

    @abstractmethod
    def check_dfu_mode(self):
        '''
        Check if the peripheral is running in bootloader (DFU) or application mode.
        Returns True if the peripheral is in DFU mode
        '''
        pass

    @abstractmethod
    def switch_to_dfu_mode(self):
        '''Switch from application to bootloader (DFU).'''
        pass

    @abstractmethod
    def _dfu_parse_notify(self, notify):
        '''Parse notification status results'''
        pass

    @abstractmethod
    async def _on_connected(self):
        pass

    def input_setup(self):
        '''
        Initialize:
            Hex: read and convert hexfile into bin_array
            Bin: read binfile into bin_array
        '''
        logger.info('Sending file %s to %s', os.path.split(self.firmware_path)[1], self.target_mac)

        if self.firmware_path is None:
            raise Exception("Input invalid")

        name, extent = os.path.splitext(self.firmware_path)

        if extent == ".bin":
            with open(self.firmware_path, 'rb') as f:
                self.bin_array = f.read()
            self.image_size = len(self.bin_array)
            logger.info('Binary image size: %d', self.image_size)
            logger.info('Binary CRC32: %08X', crc32_unsigned(self.bin_array))
            return

        if extent == ".hex":
            from intelhex import IntelHex
            intelhex = IntelHex(self.firmware_path)
            self.bin_array = intelhex.tobinarray()
            self.image_size = len(self.bin_array)
            logger.info('Bin array size: %d', self.image_size)
            return

        raise Exception("Input invalid")

    # --------------------------------------------------------------------------
    # Perform a scan and connect via bleak.
    # Will return True if a connection was established, False otherwise
    # --------------------------------------------------------------------------
    async def scan_and_connect(self, timeout=10):
        logger.info('Connecting to %s', self.target_mac)

        device = await BleakScanner.find_device_by_address(
            self.target_mac,
            timeout=timeout,
        )

        if not device:
            logger.warning(f"Device {self.target_mac} not found")
            return False

        return await self.connect(timeout=timeout)

    async def connect(self, timeout=10):
        ''' Connect to the peripheral. '''
        logger.info('Connecting to %s', self.target_mac)

        self.client = BleakClient(self.target_mac, timeout=timeout)
        try:
            await self.client.connect(timeout=timeout)
        except asyncio.TimeoutError:
            logger.error('Timeout connecting')
            return False
        except Exception as e:
            logger.error(str(e))
            return False

        if not self.client.is_connected:
            logger.warning('Device %s not connected', self.target_mac)
            return False

        await self._on_connected()
        return True

    async def disconnect(self):
        ''' Disconnect from the peripheral. '''

        if self.client and self.client.is_connected:
            await self.client.disconnect()
            logger.debug('Disconnected from %s', self.target_mac)

    def dfu_mac(self, inc=1):
        ''' Return the DFU MAC address. This is the target MAC + 1. '''
        return uint_to_mac_string(mac_string_to_uint(self.target_mac) + inc)

    async def target_mac_increase_and_connect(self, inc=1):
        '''
        Increase the target MAC address by 1 and try to connect to it.

        This is used to switch from application mode to DFU mode.
        The DFU MAC address is the target MAC + 1.
        '''
        await self.disconnect()
        self.target_mac = self.dfu_mac(inc)
        await self.connect()


    async def _dfu_wait_for_notify(self, timeout=10):
        '''Wait for notification to arrive.'''

        logger.debug("dfu_wait_for_notify")

        try:
            await asyncio.wait_for(self.notification_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        self.notification_event.clear()
        return self.notification_data

    async def _dfu_send_command(self, procedure, params=[]):
        '''
        Send a procedure + any parameters required.
        '''

        command = bytes([procedure] + params)
        logger.debug('_dfu_send_command %s', command)

        await self.client.write_gatt_char(self.ctrlpt_handle, command)

    async def _dfu_send_data(self, data: bytes):
        '''Send an array of bytes.'''
        await self.client.write_gatt_char(self.data_handle, data)

    async def _wait_and_parse_notify(self):
        '''Wait for a notification and parse the response.'''
        notif = await self._dfu_wait_for_notify()

        if notif is None:
            raise Exception("No notification received")

        result = self._dfu_parse_notify(notif)
        return result

    async def _enable_notifications(self, char: BleakGATTCharacteristic):
        '''Enable notifications from Characteristic.'''
        logger.debug('_enable_notifications')

        await self.client.start_notify(char, self._notification_handler)

    def _notification_handler(self, sender, data):
        logger.debug('Notification received from %s: %s', sender, data)
        # store data in the class and use asyncio Event to notify
        self.notification_data = data
        self.notification_event.set()
