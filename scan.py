#!/usr/bin/env python3
"""
Device scan using bleak.
"""

import asyncio
from bleak import BleakScanner

class BleScanner:
    """
    Bluetooth LE scan for advertising peripheral devices.
    """

    def __init__(self, advert_name=None):
        """
        Initialize the scanner with an optional advertisement name filter.
        """
        self.advert_name = advert_name

    async def scan(self):
        """
        Perform a BLE scan and return a list of devices.
        """
        try:
            print("Starting BLE scan...")
            devices = await BleakScanner.discover()

            # Filter devices by advertisement name if specified
            if self.advert_name:
                devices = [device for device in devices if self.advert_name in device.name]

            # Format the results
            scan_list = [f"{device.address} - {device.name}" for device in devices if device.name]

            # Print the results
            for device in scan_list:
                print(device)

            return scan_list

        except Exception as e:
            print(f"Scan failed: {e}")
            return []
        finally:
            print("Scan complete")


if __name__ == '__main__':

    # scanner = BleScanner("DfuTarg")  # specific advertisement name
    scanner = BleScanner(None)  # any advertising name    
    asyncio.run(scanner.scan())

