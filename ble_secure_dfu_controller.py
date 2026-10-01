import asyncio
import math

import time

import bleak
from util import *

import logging

from bleak.uuids import normalize_uuid_str

from nrf_ble_dfu_controller import NrfBleDfuController

logger = logging.getLogger(__file__)


class Procedures:
    CREATE          = 0x01
    SET_PRN         = 0x02
    CALC_CHECKSUM   = 0x03
    EXECUTE         = 0x04
    SELECT          = 0x06
    RESPONSE        = 0x60

    PARAM_COMMAND   = 0x01
    PARAM_DATA      = 0x02

    string_map = {
        CREATE          : "CREATE",
        SET_PRN         : "SET_PRN",
        CALC_CHECKSUM   : "CALC_CHECKSUM",
        EXECUTE         : "EXECUTE",
        SELECT          : "SELECT",
        RESPONSE        : "RESPONSE",
    }

    @staticmethod
    def to_string(proc):
        return Procedures.string_map[proc]

    @staticmethod
    def from_string(proc_str):
        return int(proc_str, 16)

class Results:
    INVALID_CODE                = 0x00
    SUCCESS                     = 0x01
    OPCODE_NOT_SUPPORTED        = 0x02
    INVALID_PARAMETER           = 0x03
    INSUFF_RESOURCES            = 0x04
    INVALID_OBJECT              = 0x05
    UNSUPPORTED_TYPE            = 0x07
    OPERATION_NOT_PERMITTED     = 0x08
    OPERATION_FAILED            = 0x0A

    string_map = {
        INVALID_CODE            : "INVALID_CODE",
        SUCCESS                 : "SUCCESS",
        OPCODE_NOT_SUPPORTED    : "OPCODE_NOT_SUPPORTED",
        INVALID_PARAMETER       : "INVALID_PARAMETER",
        INSUFF_RESOURCES        : "INSUFFICIENT_RESOURCES",
        INVALID_OBJECT          : "INVALID_OBJECT",
        UNSUPPORTED_TYPE        : "UNSUPPORTED_TYPE",
        OPERATION_NOT_PERMITTED : "OPERATION_NOT_PERMITTED",
        OPERATION_FAILED        : "OPERATION_FAILED",
    }

    @staticmethod
    def to_string(res):
        return Results.string_map[res]

    @staticmethod
    def from_string(res_str):
        return int(res_str, 16)


class BleDfuControllerSecure(NrfBleDfuController):
    UUID_DFU = normalize_uuid_str("FE59")
    UUID_BUTTONLESS = "8e400001-f315-4f60-9fb8-838830daea50"
    UUID_CONTROL_POINT = "8ec90001-f315-4f60-9fb8-838830daea50"
    UUID_PACKET = "8ec90002-f315-4f60-9fb8-838830daea50"

    def __init__(self, target_mac, firmware_path, datfile_path):
        super().__init__(target_mac, firmware_path, datfile_path)
        self.ctrlpt_uuid = self.UUID_CONTROL_POINT
        self.packet_uuid = self.UUID_PACKET

    async def _on_connected(self):
        pass


    async def start(self):
        dfus = [s for s in self.client.services if s.uuid.upper() == self.UUID_DFU.upper() ]
        if not dfus:
            raise Exception('No DFU service')
        self.service = dfus[0]

        chars = { c.uuid.upper(): c for c in self.service.characteristics}

        self.ctrlpt_handle = chars[self.UUID_CONTROL_POINT.upper()]
        self.data_handle = chars[self.UUID_PACKET.upper()]

        logger.debug('Control Point Char: %s', self.ctrlpt_handle)
        logger.debug('Packet Char: %s', self.data_handle)

        await self._enable_notifications(self.ctrlpt_handle)

        # Set the Packet Receipt Notification interval
        prn = uint16_to_bytes_le(self.pkt_receipt_interval)

        await self._dfu_send_command(Procedures.SET_PRN, prn)
        await self._wait_and_parse_notify()

        await self._dfu_send_init()
        await self._dfu_send_image()


    # --------------------------------------------------------------------------
    #  Check if the peripheral is running in bootloader (DFU) or application mode
    #  Returns True if the peripheral is in DFU mode
    # --------------------------------------------------------------------------
    async def check_dfu_mode(self):
        """Returns True if already in DFU mode, False otherwise"""
        logger.debug('Services in device: %s', [s.uuid for s in self.client.services])
        for s in self.client.services:
            if s.uuid.upper() == self.UUID_DFU.upper():
                return True
        return False

    async def switch_to_dfu_mode(self):
        """Send buttonless DFU mode entry command"""

        try:
            await self.client.write_gatt_char(
                self.UUID_BUTTONLESS, b'\x01', response=True)
        except bleak.BleakError:
            logger.exception('Switching to DFU failed')
            return False

        # Wait some time for board to reboot
        await asyncio.sleep(0.5)

        # Increase the mac address by one and reconnect
        return await self.target_mac_increase_and_connect(1)

    # --------------------------------------------------------------------------
    #  Parse notification status results
    # --------------------------------------------------------------------------

    def _dfu_parse_notify(self, notif: bytes):
        if len(notif) < 3:
            logger.error("notify data length error")
            return None

        logger.debug('RX: %s', notif)

        opcode = notif[0]
        if opcode == Procedures.RESPONSE:

            proc = notif[1]
            res = notif[2]

            logger.debug(
                "RESPONSE for %s = %s",
                Procedures.to_string(proc),
                Results.to_string(res))

            # Packet Receipt notifications are sent in the exact same format
            # as responses to the CALC_CHECKSUM procedure.
            if (proc == Procedures.CALC_CHECKSUM and res == Results.SUCCESS):
                offset = bytes_to_uint32_le(notif[3:7])
                crc32 = bytes_to_uint32_le(notif[7:11])

                logger.debug('CALC_CHECKSUM, res:%s, offset:%X, crc:%X', Results.to_string(res), offset, crc32)

                return (proc, res, offset, crc32)

            elif(proc == Procedures.SELECT and res == Results.SUCCESS):
                max_size = bytes_to_uint32_le(notif[3:7])
                offset = bytes_to_uint32_le(notif[7:11])
                crc32 = bytes_to_uint32_le(notif[11:15])

                logger.debug('SELECT, res:%s, max_size:%s, offset:%X, crc:%X', Results.to_string(res), max_size, offset, crc32)

                return (proc, res, max_size, offset, crc32)

            else:
                logger.debug('%s, res:%s', Procedures.to_string(proc), Results.to_string(res))
                return (proc, res)


    async def _dfu_send_init(self):
        '''
        Send the Init info (*.dat file contents) to peripheral device.
        '''

        with open(self.datfile_path, 'rb') as df:
            init_bin_array = df.read()
        init_size = len(init_bin_array)
        init_crc = 0

        # Select command
        await self._dfu_send_command(Procedures.SELECT, [Procedures.PARAM_COMMAND])
        _, _, max_size, offset, crc32 = await self._wait_and_parse_notify()

        if offset != init_size or crc32 != init_crc:
            if offset == 0 or offset > init_size:
                # Create command
                await self._dfu_send_command(Procedures.CREATE, [Procedures.PARAM_COMMAND] + uint32_to_bytes_le(init_size))
                await self._wait_and_parse_notify()
            segment_count = 0
            for i in range(0, init_size, self.pkt_payload_size):
                segment = init_bin_array[i:i + self.pkt_payload_size]
                await self._dfu_send_data(segment)
                segment_count += 1
                if (segment_count % self.pkt_receipt_interval) == 0:
                    (proc, res, offset, crc32) = await self._wait_and_parse_notify()

            # Calculate CRC
            await self._dfu_send_command(Procedures.CALC_CHECKSUM)
            await self._wait_and_parse_notify()

        # Execute command
        await self._dfu_send_command(Procedures.EXECUTE)
        await self._wait_and_parse_notify()

        logger.debug('Init packet successfully transferred')

    # --------------------------------------------------------------------------
    #  Send the Firmware image to peripheral device.
    # --------------------------------------------------------------------------
    async def _dfu_send_image(self):
        logger.debug('dfu_send_image')

        # Select Data Object
        await self._dfu_send_command(Procedures.SELECT, [Procedures.PARAM_DATA])
        _, _, max_size, offset, crc32 = await self._wait_and_parse_notify()

        # Split the firmware into multiple objects
        num_objects = int(math.ceil(self.image_size / float(max_size)))
        logger.debug(
            'Max object size: %d, num objects: %d, offset: %d, total size: %d',
            max_size, num_objects, offset, self.image_size)

        time_start = time.monotonic()
        obj_offset = (offset // max_size) * max_size
        while obj_offset < self.image_size:
            obj_offset += await self._dfu_send_object(obj_offset, max_size)
        # Image uploaded successfully, update the progress bar
        print_progress(self.image_size, self.image_size)

        duration = time.monotonic() - time_start
        logger.info('Upload complete in %02d:%02ds', int(duration / 60), int(duration % 60))

    async def _dfu_send_object(self, offset, obj_max_size):
        '''
        Send a single data object of given size and offset.
        '''
        if offset != self.image_size:
            if offset == 0 or offset >= obj_max_size or crc32 != crc32_unsigned(self.bin_array[0:offset]):
                # Create Data Object
                size = min(obj_max_size, self.image_size - offset)
                await self._dfu_send_command(Procedures.CREATE, [Procedures.PARAM_DATA] + uint32_to_bytes_le(size))
                await self._wait_and_parse_notify()

            segment_count = 0
            segment_total = int(math.ceil(min(obj_max_size, self.image_size-offset)/float(self.pkt_payload_size)))

            segment_begin = offset
            segment_end = min(offset+obj_max_size, self.image_size)

            for i in range(segment_begin, segment_end, self.pkt_payload_size):
                num_bytes = min(self.pkt_payload_size, segment_end - i)
                segment = self.bin_array[i:i + num_bytes]
                await self._dfu_send_data(segment)
                segment_count += 1

                # print "j: {} i: {}, end: {}, bytes: {}, size: {} segment #{} of {}".format(
                #     offset, i, segment_end, num_bytes, self.image_size, segment_count, segment_total)

                if (segment_count % self.pkt_receipt_interval) == 0:
                    try:
                        (proc, res, offset, crc32) = await self._wait_and_parse_notify()
                    except Exception as e:
                        logger.warning('err, need to re-transmit object, %s', e)
                        return 0

                    if res != Results.SUCCESS:
                        raise Exception("bad notification status: {}".format(Results.to_string(res)))

                    local_crc = crc32_unsigned(self.bin_array[0:offset])
                    if crc32 != local_crc:
                        logger.warning('crc mismatch: %X != %X', crc32, local_crc)
                        # Something went wrong, need to re-transmit this object
                        return 0

                    print_progress(offset, self.image_size)

            # Calculate CRC
            await self._dfu_send_command(Procedures.CALC_CHECKSUM)
            _, _, offset, crc32 = await self._wait_and_parse_notify()
            local_crc = crc32_unsigned(self.bin_array[0:offset])
            if crc32 != local_crc:
                logger.warning('crc mismatch: %X != %X', crc32, local_crc)
                return 0
        # Execute command
        await self._dfu_send_command(Procedures.EXECUTE)
        await self._wait_and_parse_notify()

        # If everything executed correctly, return amount of bytes transferred
        return obj_max_size
