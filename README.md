# epicsdev_lecroy
Python-based EPICS PVAccess server for LeCroy oscilloscopes.

It is based on [p4p](https://epics-base.github.io/p4p/) and [epicsdev](https://github.com/ASukhanov/epicsdev) packages 
and it can run standalone on Linux, OSX, and Windows platforms.

It was developed using the [MAUI Remote Control and Automation Manual](https://cdn.teledynelecroy.com/files/manuals/maui-remote-control-and-automation-manual.pdf) and tested with WAVERUNNER 6100 oscilloscope.

## Features

- Remote control of LeCroy oscilloscopes via EPICS PVAccess
- Support for multiple channels (configurable, default 4)
- Waveform acquisition and real-time data streaming
- Trigger control and configuration
- Horizontal and vertical scale adjustments
- Panel setup save/recall functionality
- VBS (Visual Basic Scripting) support for advanced control

## Installation

```bash
pip install epicsdev_lecroy
```

For control GUI and plotting:
```bash
pip install pypeto pvplot
```

## Usage

To start the server:
```bash
python -m epicsdev_lecroy -r 'TCPIP::192.168.1.100::INSTR'
```

### Command-line Arguments

- `-r, --resource`: VISA resource string to access the device (default: `TCPIP::192.168.1.100::INSTR`)
- `-d, --device`: Device name for PV prefix (default: `lecroy`)
- `-i, --index`: Device index for PV prefix (default: `0`)
- `-c, --channels`: Number of channels (default: `4`)
- `-v, --verbose`: Increase verbosity (`-v` or `-vv`)

### Examples

Connect via TCP/IP socket:
```bash
python -m epicsdev_lecroy -r 'TCPIP::192.168.1.100::1861::SOCKET'
```

Control GUI:
```bash
python -m pypeto -c path_to_repository/config -f epicsScope -i lecroy0:
```

## Supported Models

This driver should work with LeCroy oscilloscopes that support the MAUI remote control interface, including:
- WaveSurfer series
- WaveRunner series
- WavePro series
- HDO series
- Other Teledyne LeCroy scopes with MAUI interface

## SCPI Commands

The driver uses LeCroy SCPI commands and VBS (Visual Basic Scripting) for device control. Key commands include:
- `C<n>:TRACE` - Enable/disable channel display
- `C<n>:VOLT_DIV` - Set vertical scale
- `C<n>:OFFSET` - Set vertical offset
- `TIME_DIV` - Set horizontal scale
- `TRIG_MODE` - Set trigger mode (AUTO, NORM, SINGLE, STOP)
- `TRIG_SELECT` - Set trigger source
- VBS commands for advanced control

## Performance

Performance depends on the oscilloscope model, network interface (1GbE vs 10GbE), and memory depth. LeCroy scopes typically provide high-speed data transfer over their network interfaces.

## Notes

- The driver uses binary data transfer (WORD format) for efficient waveform acquisition
- Big-endian byte order is used for compatibility
- VBS scripting allows advanced control of scope features not available through standard SCPI
- Some features may vary depending on the specific LeCroy model

## License

BSD 3-Clause LicenseLicense - see LICENSE file for details.

## Author

Andrey Sukhanov (sukhanov@bnl.gov)
