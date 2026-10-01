# Python nRF5 OTA DFU Controller

This my attempt at fork of wasp-os fork of dingara's fork of astronomer80's fork of
foldedtoad's Python OTA DFU utility. 

Now it is a Python-native (OTA) Device Firmware Update (DFU) utility for Nordic Semiconductor nRF5 (nRF51/nRF52) devices. It has been updated to use the cross-platform `bleak` library for Bluetooth Low Energy (BLE) communication, replacing the Linux-only `gattool`. 
Which makes it possible to use it on Windows machines, as well as Linux and others where bleak library runs.

## What does it do?

This program performs Over The Air (OTA) Device Firmware Updates (DFU) to a Nordic Semiconductor nRF5 (either nRF51 or nRF52) device via Bluetooth Low Energy (BLE).

### Main features:

* Perform OTA DFU to an nRF5 peripheral without an external USB BLE dongle.
* Ability to detect if the peripheral is running in application mode or bootloader mode, and automatically switch if needed (buttonless).
* Support for both Legacy (SDK <= 11) and Secure (SDK >= 12) bootloader.
* Cross-platform support using the `bleak` library for BLE communication.

Before using this utility, the nRF5 peripheral device needs to be programmed with a DFU bootloader (see Nordic Semiconductor documentation/examples for instructions on that).
For switching to DFU mode, the bootloader must be compiled with BUTTONLESS DFU feature.

## Prerequisites

* Python 3.8 or higher
* `bleak` library (available via pip)
* `intelhex` library (available via pip)

## Firmware Build Requirement

* Your nRF5 peripheral firmware build method will produce a firmware file ending with either `*.hex` or `*.bin`.
* Your nRF5 firmware build method will produce an Init file ending with `.dat`.
* The program will also accept a ZIP archive with both .bin and .dat files.
* The typical naming convention is `application.bin` and `application.dat`, but this utility will accept other names.

## Generating Init Files

### Legacy Bootloader

Use the `gen_dat` application (you need to compile it with `gcc gen_dat.c -o gen_dat` on first run) to generate a `.dat` file from your `.bin` file. Example:

    ./gen_dat application.bin application.dat

Note: The `gen_dat` utility expects a `.bin` file input, so you'll get Cyclic Redundancy Check (CRC) errors during DFU using a `.dat` file generated from a `.hex` file.

An alternative is to use `nrfutil` from Nordic Semiconductor, but I've found this method to be easier. You may need to edit the `gen_dat` source to fit your specific application.

### Secure Bootloader

You need to use `nrfutil` to generate firmware packages for the new secure bootloader (SDK > 12) as the package needs to be signed with a private/public key pair. Note that the bootloader will need to be programmed with the corresponding public key. See the [nrfutil repo](https://github.com/NordicSemiconductor/pc-nrfutil) for details.

Note: I've had problems with the pip version of `nrfutil`. I recommend [installing from source](https://github.com/NordicSemiconductor/pc-nrfutil#running-and-installing-from-source) instead.

## Usage

There are two ways to specify firmware files for this utility. Either by specifying both the `.hex` or `.bin` file with the `.dat` file, or more easily by the `.zip` file, which contains both the hex and dat files.

The new `.zip` file form is encouraged by Nordic, but the older hex/bin + dat file methods should still work.

## Usage Examples

    > python3 dfu.py -f ~/application.hex -d ~/application.dat -a CD:E3:4A:47:1C:E4

or:

    > python3 dfu.py -z ~/application.zip -a CD:E3:4A:47:1C:E4

You can use the `hcitool lescan` to figure out the address of a DFU target, for example:

    $ sudo hcitool -i hci0 lescan
    LE Scan ...
    CD:E3:4A:47:1C:E4 <TARGET_NAME>
    CD:E3:4A:47:1C:E4 (unknown)

You can also use the `scan.py` utility (included in this repository)

## Example Output

        ================================
        ==                            ==
        ==         DFU Server         ==
        ==                            ==
        ================================ 

    Sending file application.bin to CD:E3:4A:47:1C:E4
    bin array size:  60788
    Checking DFU State...
    Board needs to switch in DFU mode
    Switching to DFU mode
    Enable Notifications in DFU mode
    Sending hex file size
    Waiting for Image Size notification
    Waiting for INIT DFU notification
    Begin DFU
    Progress: |xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx| 100.0% Complete (60788 of 60788 bytes)

    Upload complete in 0 minutes and 14 seconds
    segments sent: 3040
    Waiting for DFU complete notification
    Waiting for Firmware Validation notification
    Activate and reset
    DFU Server done

## TODO:

* Implement link-loss procedure for Legacy Controller.
* Update example output in readme.
* Add makefile examples.
* More code cleanup.

## Info & References

* [Nordic Legacy DFU Service](http://infocenter.nordicsemi.com/topic/com.nordic.infocenter.sdk5.v11.0.0/bledfu_transport_bleservice.html?cp=4_0_3_4_3_1_4_1)
* [Nordic Legacy DFU sequence diagrams](http://infocenter.nordicsemi.com/topic/com.nordic.infocenter.sdk5.v11.0.0/bledfu_transport_bleprofile.html?cp=4_0_3_4_3_1_4_0_1_6#ota_profile_pkt_rcpt_notif)
* [Nordic Secure DFU bootloader](http://infocenter.nordicsemi.com/topic/com.nordic.infocenter.sdk5.v12.2.0/lib_dfu_transport_ble.html?cp=4_0_1_3_5_2_2)
* [nrfutil](https://github.com/NordicSemiconductor/pc-nrfutil)
* [Bleak Library](https://github.com/hbldh/bleak)
