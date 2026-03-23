"""LeCroy oscilloscope device server using epicsdev module."""
# pylint: disable=invalid-name
__version__ = 'v1.0.0 26-02-15'  # Initial version adapted from epicsdev_rigol_scope

import sys
import time
from time import perf_counter as timer
import argparse
import threading
import numpy as np

import pyvisa as visa
from pyvisa.errors import VisaIOError

from epicsdev import epicsdev as edev

#``````````````````PVs defined here```````````````````````````````````````````
def myPVDefs():
    """PV definitions"""
    SET,U,LL,LH,SCPI = 'setter','units','limitLow','limitHigh','scpi'
    alarm = {'valueAlarm':{'lowAlarmLimit':-9., 'highAlarmLimit':9.}}
    pvDefs = [
# instruments's PVs
['setup', 'Save/recall instrument state to/from latest or operational setup',
    edev.SPV(['Setup','Store Panel','Recall Panel'],'WD'),
    {SET:set_setup}],
['visaResource', 'VISA resource to access the device', edev.SPV(pargs.resource,'R'), {}],
['dateTime',    'Scope`s date & time', edev.SPV('N/A'), {}],
['acqCount',    'Number of acquisition recorded', edev.SPV(0), {}],
['scopeAcqCount',  'Acquisition count of the scope', edev.SPV(0), {}],
['lostTrigs',   'Number of triggers lost',  edev.SPV(0), {}],
['instrCtrl',   'Scope control commands',
    edev.SPV('*IDN?,*RST,*CLS,*ESR?,*OPC?,*STB?'.split(','),'WD'), {}],
['instrCmdS',   'Execute a scope command. Features: RWE',  edev.SPV('*IDN?','W'), {
    SET:set_instrCmdS}],
['instrCmdR',   'Response of the instrCmdS',  edev.SPV(''), {}],
#``````````````````Horizontal PVs
['recLengthS',   'Number of points per waveform',
    edev.SPV(['AUTO','500','1k','2.5k','5k','10k','25k','50k','100k','250k','500k','1M','2.5M','5M','10M'],'WD'), {
    SET:set_recLengthS}],
['recLengthR',   'Number of points per waveform read', edev.SPV(0.), {}],
['samplingRate', 'Sampling Rate',  edev.SPV(0.), {U:'Hz',
    SCPI:'!VBS? return=app.Acquisition.Horizontal.SampleRate'}],
['timePerDiv', f'Horizontal scale (1/{NDIVSX} of full scale)', edev.SPV(2.e-6,'W'), {U:'S/du',
    SCPI: 'TIME_DIV', SET:set_scpi}],
['tAxis',       'Horizontal axis array', edev.SPV([0.]), {U:'S'}],

#``````````````````Trigger PVs
['trigger',     'Click to force trigger event to occur',
    edev.SPV(['Trigger','Force!'],'WD'), {SET:set_trigger}],
['trigType',   'Trigger type', edev.SPV(['EDGE','DROP','GLIT','INTV','QUAL','RUNT','SLEW','TV'],'WD'),{
    SCPI:'!VBS? return=app.Acquisition.Trigger.Type', SET:set_vbs}],
['trigCoupling',   'Trigger coupling', edev.SPV(['DC','AC','HFREJ','LFREJ'],'WD'),{
    SCPI:'!VBS? return=app.Acquisition.Trigger.Edge.Coupling', SET:set_vbs}],
['trigState',   'Current trigger status: Ready, Armed, Triggered, Auto', edev.SPV('?'),{
    SCPI:'!TRIG_SELECT'}],
['trigMode',   'Trigger mode', edev.SPV(['AUTO','NORM','SINGLE','STOP'],'WD'),{
    SCPI:'TRIG_MODE', SET:set_scpi}],
['trigDelay',   'Trigger delay/position', edev.SPV(0.,'W'), {U:'S',
    SCPI:'TRIG_DELAY', SET:set_scpi}],
['trigSource', 'Trigger source',
    edev.SPV('C1,C2,C3,C4,LINE,EXT'.split(','),'WD'),{
    SCPI:'TRIG_SELECT', SET:set_scpi}],
['trigSlope',  'Trigger slope', edev.SPV(['POS','NEG'],'WD'),{
    SCPI:'!VBS? return=app.Acquisition.Trigger.Edge.Slope', SET:set_vbs}],
['trigLevel', 'Trigger level', edev.SPV(0.,'W'), {U:'V',
    SCPI:'!TRIG_LEVEL', SET:set_scpi}],
#``````````````````Auxiliary PVs
['timing',  'Performance timing', edev.SPV([0.]), {U:'S'}],
    ]

    #``````````````Templates for channel-related PVs.
    # The <n> in the name will be replaced with channel number.
    # Important: SPV cannot be used in this list!
    ChannelTemplates = [
['c<n>OnOff', 'Enable/disable channel', (['1','0'],'WD'),{
    SCPI:'C<n>:TRACE', SET:set_scpi}],
['c<n>Coupling', 'Channel coupling', (['D1M','D50','GND','A1M'],'WD'),{
    SCPI:'C<n>:COUPLING', SET:set_scpi}],
['c<n>VoltsPerDiv',  'Vertical scale',  (1E-3,'W'), {U:'V/du',
    SCPI:'C<n>:VOLT_DIV', SET:set_scpi, LL:500E-6, LH:10.}],
['c<n>VoltOffset',  'Vertical offset',  (0.,'W'), {U:'V',
    SCPI:'C<n>:OFFSET', SET:set_scpi}],
['c<n>Termination', 'Input termination', (['1M','50'],'WD'), {U:'Ohm',
    SCPI:'C<n>:IMPEDANCE', SET:set_scpi}],
['c<n>Waveform', 'Waveform array',           ([0.],), {U:'du'}],
['c<n>Mean',     'Mean of the waveform',     (0.,'A'), {U:'V'}],
['c<n>Peak2Peak','Peak-to-peak amplitude',   (0.,'A'), {U:'V',**alarm}],
    ]
    # extend PvDefs with channel-related PVs
    for ch in range(pargs.channels):
        for pvdef in ChannelTemplates:
            newpvdef = pvdef.copy()
            newpvdef[0] = pvdef[0].replace('<n>',f'{ch+1:02}')
            newpvdef[2] = edev.SPV(*pvdef[2])
            pvDefs.append(newpvdef)
    return pvDefs
#,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
#``````````````````Constants
Threadlock = threading.Lock()
OK = 0
NotOK = -1
IF_CHANGED = True
ElapsedTime = {}
NDIVSX = 10  # number of horizontal divisions of the scope display
NDIVSY = 10  # number of vertical divisions
# LeCroy waveform format constants
LECROY_DESCRIPTOR_SIZE = 346  # Typical LeCroy WAVEDESC header size
# Note: VERTICAL_RESOLUTION is approximate. For accurate conversion, parse VERTICAL_GAIN
# and VERTICAL_OFFSET from the WAVEDESC structure (see LeCroy Remote Control manual)
LECROY_VERTICAL_RESOLUTION = 25.0  # Approximate vertical resolution (full scale / max ADC value)
DEFAULT_TIMEBASE_DIVISIONS = 50  # Default divisions for timebase calculation
DEFAULT_NPOINTS = 1000  # Default number of points when not parsed from descriptor
#,,,,,,,,,,,,,,,,,,
class C_():
    """Namespace for module properties"""
    scope = None
    scpi = {}# {pvName:SCPI} map
    setterMap = {}
    PvDefs = []
    readSettingQuery = None
    exceptionCount = {}
    numacq = 0
    triggersLost = 0
    trigTime = 0
    previousScopeParametersQuery = ''
    channelsTriggered = []
    xorigin = 0.
    xincrement = 0.
    npoints = 0
    ypars = None
#``````````````````Setters````````````````````````````````````````````````````
def scopeCmd(cmd):
    """Send command to scope, return reply if any."""
    edev.printv(f'>scopeCmd: {cmd}')
    reply = None
    try:
        with Threadlock:
            if '?' in cmd:
                reply = C_.scope.query(cmd)
            else:
                C_.scope.write(cmd)
    except Exception:
        handle_exception(f'in scopeCmd{cmd}')
    return reply

def set_instrCmdS(cmd, *_):
    """Setter for the instrCmdS PV"""
    edev.publish('instrCmdR','')
    reply = scopeCmd(cmd)
    if reply is not None:
        edev.publish('instrCmdR',reply)
    edev.publish('instrCmdS',cmd)

def serverStateChanged(newState:str):
    """Start device function called when server is started"""
    if newState == 'Start':
        edev.printi('start_device called')
        configure_scope()
        adopt_local_setting()
        C_.scope.write('TRIG_MODE AUTO')
        wait_for_scopeReady()

    elif newState == 'Stop':
        edev.printi('stop_device called')
    elif newState == 'Clear':
        edev.printi('clear_device called')

def set_setup(action_slot, *_):
    """setter for the setup PV"""
    if action_slot == 'Setup':
        return
    action = str(action_slot)
    status = f'Panel setup action: {action}'
    if action == 'Store Panel':
        with Threadlock:
            C_.scope.write('PANEL_SETUP STORE,"LATEST"')
    elif action == 'Recall Panel':
        status = 'Panel setup recalled'
        if str(edev.pvv('server')).startswith('Start'):
            edev.printw('Please set server to Stop before Recalling')
            edev.publish('setup','Setup')
            return NotOK
        with Threadlock:
            C_.scope.write('PANEL_SETUP RECALL,"LATEST"')
    edev.publish('setup','Setup')
    edev.publish('status', status)
    if action == 'Recall Panel':
        adopt_local_setting()

def set_trigger(value, *_):
    """setter for the trigger PV"""
    edev.printv(f'set_trigger: {value}')
    if str(value) == 'Force!':
        with Threadlock:
            C_.scope.write('ARM')
        edev.publish('trigger','Trigger')

def set_recLengthS(value, *_):
    """setter for the recLengthS PV"""
    edev.printv(f'set_recLengthS: {value}')
    # LeCroy uses MEMORY_SIZE command
    mem_map = {
        'AUTO': 'AUTO',
        '500': '500',
        '1k': '1K',
        '2.5k': '2.5K',
        '5k': '5K',
        '10k': '10K',
        '25k': '25K',
        '50k': '50K',
        '100k': '100K',
        '250k': '250K',
        '500k': '500K',
        '1M': '1M',
        '2.5M': '2.5M',
        '5M': '5M',
        '10M': '10M'
    }
    mem_size = mem_map.get(value, value)
    with Threadlock:
        C_.scope.write(f'MEMORY_SIZE {mem_size}')
    edev.publish('recLengthS', value)
    update_scopeParameters()

def set_scpi(value, pv, *_):
    """setter for SCPI-associated PVs"""
    print(f'set_scpi({value},{pv.name})')
    scpi = C_.scpi.get(pv.name,None)
    if scpi is None:
        edev.printe(f'No SCPI defined for PV {pv.name}')
        return
    scpi = scpi.replace('<n>',pv.name[2])# replace <n> with channel number
    print(f'set_scpi: {scpi} {value}')
    scpi += f' {value}' if pv.writable else '?'
    edev.printv(f'set_scpi command: {scpi}')
    reply = scopeCmd(scpi)
    if reply is not None:
        edev.publish(pv.name, reply)
    edev.publish(pv.name, value)

def set_vbs(value, pv, *_):
    """setter for VBS script commands"""
    print(f'set_vbs({value},{pv.name})')
    scpi = C_.scpi.get(pv.name,None)
    if scpi is None:
        edev.printe(f'No SCPI defined for PV {pv.name}')
        return
    # Convert VBS query to VBS assignment
    vbs_path = scpi.replace('!VBS? return=', '').strip()
    vbs_cmd = f'VBS {vbs_path} = "{value}"'
    edev.printv(f'set_vbs command: {vbs_cmd}')
    scopeCmd(vbs_cmd)
    edev.publish(pv.name, value)

#``````````````````Instrument communication functions`````````````````````````
def query(pvnames, explicitSCPIs=None):
    """Execute query request of the instrument for multiple PVs"""
    scpis = [C_.scpi[pvname] for pvname in pvnames]
    if explicitSCPIs:
        scpis += explicitSCPIs
    combinedScpi = ';'.join(scpis) + '?'
    print(f'combinedScpi: {combinedScpi}')
    with Threadlock:
        r = C_.scope.query(combinedScpi)
    return r.split(';')

def configure_scope():
    """Send commands to configure data transfer"""
    edev.printi('configure_scope')
    with Threadlock:
        # Configure for binary data transfer (WORD format)
        C_.scope.write("COMM_FORMAT DEF9,WORD,BIN")
        C_.scope.write("COMM_ORDER HI")  # Big-endian byte order

def wait_for_scopeReady():
    """Wait for scope to be in ready state after acquisition"""
    for attempt in range(5):
        time.sleep(0.1)
        try:
            with Threadlock:
                trigStatus = C_.scope.query('TRIG_MODE?')
            if trigStatus.strip() in ['AUTO', 'NORM']:
                break
        except Exception:
            pass
    if attempt == 4:
        edev.printw(f'Scope may not be ready after {attempt*0.1} seconds')

def update_scopeParameters():
    """Update scope timing PVs"""
    # Query horizontal parameters
    try:
        with Threadlock:
            # Query waveform description for first enabled channel
            enabled_ch = None
            for ch in range(1, pargs.channels+1):
                trace = C_.scope.query(f'C{ch}:TRACE?')
                if 'ON' in trace:
                    enabled_ch = ch
                    break
            
            if enabled_ch is None:
                return
                
            # Get waveform descriptor
            C_.scope.write(f'C{enabled_ch}:WF? DESC')
            desc = C_.scope.read_raw()
            
            # Parse descriptor to get timing information
            # LeCroy descriptor format is complex, simplified here
            # In practice, need to parse the WAVEDESC structure
            
            # For now, query basic parameters
            # TODO: Parse WAVEDESC structure for accurate timing parameters
            timebase = C_.scope.query('TIME_DIV?')
            C_.xincrement = float(timebase) / DEFAULT_TIMEBASE_DIVISIONS  # Approximate
            C_.npoints = DEFAULT_NPOINTS  # Default, should parse from descriptor
            
            taxis = np.arange(0, C_.npoints) * C_.xincrement
            edev.publish('tAxis', taxis)
            edev.publish('recLengthR', C_.npoints, IF_CHANGED)
            edev.publish('timePerDiv', float(timebase), IF_CHANGED)
            if C_.xincrement > 0:
                edev.publish('samplingRate', 1./C_.xincrement, IF_CHANGED)
            
            # Update channel enable status
            C_.channelsTriggered = []
            for ch in range(1, pargs.channels+1):
                trace = C_.scope.query(f'C{ch}:TRACE?')
                is_on = 'ON' in trace
                edev.publish(f'c{ch:02}OnOff', '1' if is_on else '0', IF_CHANGED)
                if is_on:
                    C_.channelsTriggered.append(ch)
    except Exception as e:
        edev.printw(f'Error updating scope parameters: {e}')

def init_visa():
    '''Init VISA interface to device'''
    try:
        rm = visa.ResourceManager('@py')
    except ModuleNotFoundError as e:
        edev.printe(f'in visa.ResourceManager: {e}')
        sys.exit(1)

    resourceName = pargs.resource.upper()
    edev.printv(f'Opening resource {resourceName}')
    try:
        C_.scope = rm.open_resource(resourceName)
    except visa.errors.VisaIOError as e:
        edev.printe(f'Could not open resource {resourceName}: {e}')
        sys.exit(1)
    
    C_.scope.timeout = 5000 # ms
    C_.scope.read_termination = '\n'
    C_.scope.write_termination = '\n'
    
    try:
        C_.scope.clear()
        print("Instrument buffer cleared successfully.")
    except Exception as e:
        print(f"An error occurred during clearing the buffer: {e}")
        sys.exit(1)

    try:
        idn = C_.scope.query('*IDN?')
    except Exception as e:
        edev.printe(f"An error occurred during IDN query: {e}")
        sys.exit(1)
    edev.printi(f'IDN: {idn}')
    if not ('LECROY' in idn.upper() or 'TELEDYNE' in idn.upper()):
        edev.printw('WARNING: instrument may not be a LeCroy/Teledyne oscilloscope')

    try:
        C_.scope.write('*CLS') # clear ESR, previous error messages will be cleared
    except Exception as e:
        edev.printe(f'Resource {resourceName} not responding: {e}')
        sys.exit()

#``````````````````````````````````````````````````````````````````````````````
def handle_exception(where):
    """Handle exception"""
    exceptionText = str(sys.exc_info()[1])
    tokens = exceptionText.split()
    msg = 'ERR:'+tokens[0] if tokens[0] == 'VI_ERROR_TMO' else exceptionText
    msg = msg+': '+where
    edev.printe(msg)
    with Threadlock:
        C_.scope.write('*CLS')
    return -1

def adopt_local_setting():
    """Read scope setting and update PVs"""
    edev.printi('adopt_local_setting')
    ct = time.time()
    nothingChanged = True
    try:
        edev.printvv(f'readSettingQuery: {C_.readSettingQuery}')
        # For LeCroy, we query parameters individually
        for parname in C_.scpi:
            scpi = C_.scpi[parname]
            scpi = scpi.replace('<n>', parname[2] if len(parname) > 2 and parname[1].isdigit() else '1')
            
            if scpi.startswith('!'):
                # Skip special commands
                continue
                
            try:
                with Threadlock:
                    v = C_.scope.query(scpi + '?').strip()
                
                pv = edev.pvobj(parname)
                pvValue = pv.current()
                
                if pv.discrete:
                    pvValue = str(pvValue)
                else:
                    try:
                        v = type(pvValue.raw.value)(v)
                    except (ValueError, AttributeError):
                        continue
                
                valueChanged = pvValue != v
                if valueChanged:
                    edev.printv(f'posting {pv.name}={v}')
                    pv.post(v, timestamp=ct)
                    nothingChanged = False
            except Exception as e:
                edev.printvv(f'Error reading {parname}: {e}')
                continue

    except visa.errors.VisaIOError as e:
        edev.printe('VisaIOError in adopt_local_setting:'+str(e))
    if nothingChanged:
        edev.printi('Local setting did not change.')

#,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
#``````````````````Acquisition-related functions``````````````````````````````
def trigger_is_detected():
    """check if scope was triggered"""
    ts = timer()
    try:
        with Threadlock:
            # LeCroy: Check trigger state
            trigStatus = C_.scope.query('TRIG_MODE?').strip()
            
            # Check if stopped externally
            if trigStatus == 'STOP':
                edev.set_server('Stop')
                edev.printw('Scope was stopped externally. Server stopped.')
                return False
    except visa.errors.VisaIOError as e:
        edev.printe(f'VisaIOError in query for trigger: {e}')
        for exc in C_.exceptionCount:
            if exc in str(e):
                C_.exceptionCount[exc] += 1
                errCountLimit = 2
                if C_.exceptionCount[exc] >= errCountLimit:
                    edev.printe(f'Processing stopped due to {exc} happened {errCountLimit} times')
                    edev.set_server('Exit')
                else:
                    edev.printw(f'Exception  #{C_.exceptionCount[exc]} during processing: {exc}')
        return False
    except Exception as e:
        edev.printe(f'Exception in query for trigger: {e}')
        return False

    # last query was successfull, clear error counts
    for i in C_.exceptionCount:
        C_.exceptionCount[i] = 0
    edev.publish('trigState', trigStatus, IF_CHANGED)

    # LeCroy doesn't have the same trigger detection as RIGOL
    # We'll check if we can acquire data (always return True in AUTO mode)
    if trigStatus in ['AUTO', 'NORM']:
        C_.numacq += 1
        C_.trigTime = time.time()
        ElapsedTime['trigger_detection'] = round(timer() - ts,6)
        edev.printv(f'Ready for acquisition {C_.numacq}')
        return True

    return False

#``````````````````Acquisition-related functions``````````````````````````````
def acquire_waveforms():
    """Acquire waveforms from the device and publish them."""
    edev.printv(f'>acquire_waveform for channels {C_.channelsTriggered}')
    edev.publish('acqCount', edev.pvv('acqCount') + 1, t=C_.trigTime)
    ElapsedTime['acquire_wf'] = timer()
    ElapsedTime['preamble'] = 0.
    ElapsedTime['query_wf'] = 0.
    ElapsedTime['publish_wf'] = 0.
    
    for ch in C_.channelsTriggered:
        try:
            ts = timer()
            operation = 'getting waveform'
            
            with Threadlock:
                # Request waveform data from LeCroy
                C_.scope.write(f'C{ch}:WF? DAT1')
                # Read binary data
                raw_data = C_.scope.read_raw()
            
            ElapsedTime['query_wf'] += timer() - ts
            
            # Parse LeCroy waveform data
            # The format starts with a descriptor header
            # Simplified parsing - in production would need full WAVEDESC parsing
            try:
                # Skip header and extract data
                # LeCroy format: DESC header followed by data
                # For now, use simplified approach
                if len(raw_data) > 100:
                    # Try to extract 16-bit signed integers
                    # Skip header (approximate)
                    if len(raw_data) > LECROY_DESCRIPTOR_SIZE:
                        waveform = np.frombuffer(raw_data[LECROY_DESCRIPTOR_SIZE:], dtype=np.int16)
                        
                        # Get vertical scaling
                        with Threadlock:
                            vdiv = float(C_.scope.query(f'C{ch}:VOLT_DIV?'))
                            offset = float(C_.scope.query(f'C{ch}:OFFSET?'))
                        
                        # Convert to voltage (simplified)
                        # TODO: For production use, parse VERTICAL_GAIN and VERTICAL_OFFSET from
                        # WAVEDESC structure for accurate voltage conversion
                        v = waveform * vdiv / LECROY_VERTICAL_RESOLUTION  # Approximate scaling
                        
                        # publish
                        ts = timer()
                        operation = 'publishing'
                        edev.publish(f'c{ch:02}Waveform', v+offset, t=C_.trigTime)
                        edev.publish(f'c{ch:02}Peak2Peak', np.ptp(v), t = C_.trigTime)
                        edev.publish(f'c{ch:02}Mean', v.mean(), t = C_.trigTime)
                        ElapsedTime['publish_wf'] += timer() - ts
            except Exception as e:
                edev.printe(f'Error parsing waveform data for channel {ch}: {e}')
                
        except visa.errors.VisaIOError as e:
            edev.printe(f'Visa exception in {operation} for {ch}:{e}')
            break
        except Exception as e:
            edev.printe(f'Exception in {operation} of channel {ch}: {e}')

    ElapsedTime['acquire_wf'] = timer() - ElapsedTime['acquire_wf']
    edev.printvv(f'elapsedTime: {ElapsedTime}')

def make_readSettingQuery():
    """Create SCPI map for reading settings"""
    for pvdef in C_.PvDefs:
        pvname = pvdef[0]
        # if setter is defined, add it to the setterMap
        setter = pvdef[3].get('setter',None)
        if setter is not None:
            C_.setterMap[pvname] = setter
        # if SCPI is defined, add it to the scpi map
        scpi = pvdef[3].get('scpi',None)
        if scpi is None:
            continue
        scpi = scpi.replace('<n>',pvname[2] if len(pvname) > 2 else '1')
        scpi = ''.join([char for char in scpi if not char.islower()])# remove lowercase letters
        
        # For LeCroy, we don't validate all commands at startup
        # as some VBS queries may not be supported on all models
        if not scpi.startswith('!'):
            C_.scpi[pvname] = scpi
        
    edev.printv(f'SCPI map created with {len(C_.scpi)} entries')
    edev.printv(f'setterMap: {C_.setterMap}')

def init():
    """Module initialization"""
    init_visa()
    make_readSettingQuery()
    adopt_local_setting()

def periodicUpdate():
    """Called for infrequent updates"""
    while Threadlock.locked():
        edev.printi('periodicUpdate waiting for lock to be released')
        time.sleep(0.1)
    try:
        update_scopeParameters()
    except Exception:
        handle_exception('in update_scopeParameters')
    edev.publish('lostTrigs', C_.triggersLost, IF_CHANGED)
    edev.publish('timing', [(round(i,6)) for i in ElapsedTime.values()])

def poll():
    """Instrument polling function"""
    if trigger_is_detected():
        time.sleep(0.1)  # Small delay for LeCroy to complete acquisition
        with Threadlock:
            acquire_waveforms()

#``````````````````Main```````````````````````````````````````````````````````
if __name__ == "__main__":
    # Argument parsing
    parser = argparse.ArgumentParser(description = __doc__,
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    epilog=f'{__version__}')
    parser.add_argument('-c', '--channels', type=int, default=4, help=
    'Number of channels per device')
    parser.add_argument('-d', '--device', default='lecroy', help=
    'Device name, the PV name will be <device><index>:')
    parser.add_argument('-i', '--index', default='0', help=
    'Device index, the PV name will be <device><index>:') 
    parser.add_argument('-r', '--resource', default='TCPIP::192.168.1.100::INSTR', help=
    'Resource string to access the device, e.g. TCPIP::192.168.1.100::1861::SOCKET')
    parser.add_argument('-v', '--verbose', action='count', default=0, help=
    'Show more log messages (-vv: show even more)') 
    pargs = parser.parse_args()
    print(f'pargs: {pargs}')

    # Initialize epicsdev and PVs
    pargs.prefix = f'{pargs.device}{pargs.index}:'
    C_.PvDefs = myPVDefs()
    PVs = edev.init_epicsdev(pargs.prefix, C_.PvDefs, pargs.verbose, serverStateChanged)

    # Initialize the device, using pargs if needed.
    init()

    # Start the Server.
    edev.set_server('Start')

    # Main loop
    server = edev.Server(providers=[PVs])
    edev.printi(f'Server for {pargs.prefix} started. Sleeping per cycle: {repr(edev.pvv("sleep"))} S.')
    while True:
        state = edev.serverState()
        if state.startswith('Exit'):
            break
        if not state.startswith('Stop'):
            poll()
        if not edev.sleep():
            periodicUpdate()
    edev.printi('Server is exited')
