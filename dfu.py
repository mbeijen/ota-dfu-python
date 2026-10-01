#!/usr/bin/env python3
"""
DFU Server for Nordic nRF51/nRF52 based systems.

Conforms to nRF51_SDK 11.0 BLE_DFU requirements.
"""
import os
import argparse
import traceback
import asyncio
import logging

from bleak import BleakScanner

from unpacker import Unpacker

from ble_secure_dfu_controller import BleDfuControllerSecure
from ble_legacy_dfu_controller import BleDfuControllerLegacy

logger = logging.getLogger(__name__)

async def main():

    logging.basicConfig(level=logging.INFO)

    try:
        parser = argparse.ArgumentParser(
            description="DFU Server for Nordic nRF51/nRF52 based systems.",
            usage='%(prog)s -f <hex_file> -a <dfu_target_address>\n\nExample:\n\tdfu.py -f application.hex -d application.dat -a cd:e3:4a:47:1c:e4'
        )

        parser.add_argument('-a', '--address',
                            type=str,
                            required=True,
                            help='DFU target address.')
        parser.add_argument('-u', '--auto-switch',
                            type=bool,
                            default=True,
                            help='Try to switch to DFU')
        parser.add_argument('-f', '--file',
                            type=str,
                            dest='hexfile',
                            help='Hex file to be uploaded.')

        parser.add_argument('-d', '--dat',
                            type=str,
                            dest='datfile',
                            help='DAT file to be uploaded.')

        parser.add_argument('-z', '--zip',
                            type=str,
                            dest='zipfile',
                            help='Zip file to be used.')

        parser.add_argument('--secure',
                            action='store_true',
                            default=True,
                            help='Use secure bootloader (Nordic SDK > 12).')

        parser.add_argument('--legacy',
                            action='store_false',
                            dest='secure_dfu',
                            help='Use legacy bootloader (Nordic SDK < 12).')

        parser.add_argument('-v', '--verbose',
                            action='store_true',
                            help='Increase verbosity.')

        options = parser.parse_args()

        if options.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

    except Exception as e:
        logger.exception('Argument error')
        parser.print_usage()
        exit(2)

    unpacker = None

    try:
        # Validate input parameters
        hexfile = None
        datfile = None

        if options.zipfile:
            if options.hexfile or options.datfile:
                logger.error("Cannot use ZIP file with HEX or DAT file.")
                parser.print_usage()
                exit(2)

            unpacker = Unpacker()
            try:
                hexfile, datfile = unpacker.unpack_zipfile(options.zipfile)
            except Exception:
                logger.error('Error unpacking ZIP file', exc_info=True)

        else:
            if not options.hexfile or not options.datfile:
                logger.error('HEX file and DAT file are needed.')
                parser.print_help()
                exit(2)

            if not os.path.isfile(options.hexfile):
                logger.error("Error: HEX file doesn't exist")
                exit(2)

            if not os.path.isfile(options.datfile):
                logger.error("Error: DAT file doesn't exist")
                exit(2)

            hexfile = options.hexfile
            datfile = options.datfile

        # Start of Device Firmware Update processing
        if options.secure_dfu:
            ble_dfu = BleDfuControllerSecure(options.address.upper(), hexfile, datfile)
        else:
            ble_dfu = BleDfuControllerLegacy(options.address.upper(), hexfile, datfile)

        # Initialize inputs
        ble_dfu.input_setup()

        dfu_addr = ble_dfu.dfu_mac()

        device = await BleakScanner.find_device_by_filter(
            lambda d, _: d.address == ble_dfu.target_mac or d.address == dfu_addr,
            timeout=10,
        )

        if device is None:
            logger.error('Devices not found')
            return False

        if device.address != ble_dfu.target_mac:
            logger.info(f"Device address changed to {device.address}")
            ble_dfu.target_mac = device.address

        # Connect to peer device.
        if not await ble_dfu.connect():
            logger.error('Could not connect!')
            return

        if not await ble_dfu.check_dfu_mode():
            logger.info('Device not in DFU mode')
            if not options.auto_switch:
                logger.info('Auto switch to DFU mode disabled')
                return
            success = await ble_dfu.switch_to_dfu_mode()
            if not success:
                logger.error("Couldn't switch")
                return

        await ble_dfu.start()

    except Exception:
        logger.exception('Error during DFU process')
    finally:
        # Disconnect from peer device if not done already and clean up.
        await ble_dfu.disconnect()

        # If Unpacker for zipfile used then delete Unpacker
        if unpacker is not None:
            unpacker.delete()


if __name__ == '__main__':
    asyncio.run(main())
