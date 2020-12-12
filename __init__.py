#!/usr/bin/env python
#########################################################################
# Copyright 2020 Michael Wenzel
#########################################################################
#  Viessmann-Plugin for SmartHomeNG.  https://github.com/smarthomeNG//
#
#  This plugin is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This plugin is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this plugin. If not, see <http://www.gnu.org/licenses/>.
#########################################################################

import logging
import socket
import time
import serial
import re
import threading
from datetime import datetime
import dateutil.parser
import cherrypy

from . import commands

from lib.item import Items
from lib.model.smartplugin import *
from bin.smarthome import VERSION


class Viessmann(SmartPlugin):
    '''
    Main class of the plugin. Provides communication with Viessmann heating systems
    via serial / USB-to-serial connections to read values and set operating parameters.

    Supported device types must be defined in "commands.py".
    '''
    ALLOW_MULTIINSTANCE = False

    PLUGIN_VERSION = '1.1.0'

    #
    # public methods
    #

    def __init__(self, sh, *args, **kwargs):

        # Get plugin parameter
        self._serialport = self.get_parameter_value('serialport')
        self._heating_type = self.get_parameter_value('heating_type')
        self._protocol = self.get_parameter_value('protocol')
        self._timeout = self.get_parameter_value('timeout')

        # Set variables
        self._params = {}                                                   # Item dict
        self._init_cmds = []                                                # List of command codes for read at init
        self._cyclic_cmds = {}                                              # Dict of command codes with cylce-times for cyclic readings
        self._application_timer = {}                                        # Dict of application timer with command codes and values
        self._timer_cmds = []                                               # List of command codes for timer
        self._viess_timer_dict = {}
        self._lock = threading.Lock()
        self._initread = False
        self._timerread = False
        self._connected = False
        self._initialized = False
        self._lastbyte = b''
        self._lastbytetime = 0
        self._cyclic_update_active = False
        self._wochentage = {
            'MO': ['mo', 'montag', 'monday'],
            'TU': ['di', 'dienstag', 'tuesday'],
            'WE': ['mi', 'mittwoch', 'wednesday'],
            'TH': ['do', 'donnerstag', 'thursday'],
            'FR': ['fr', 'freitag', 'friday'],
            'SA': ['sa', 'samstag', 'saturday'],
            'SU': ['so', 'sonntag', 'sunday']}

        # initialize logger if necessary
        if '.'.join(VERSION.split('.', 2)[:2]) <= '1.5':
            self.logger = logging.getLogger(__name__)

        # Load protocol dependent sets
        if self._protocol in commands.controlset and self._protocol in commands.errorset and self._protocol in commands.unitset and self._protocol in commands.returnstatus and self._protocol in commands.setreturnstatus:
            self._controlset = commands.controlset[self._protocol]
            self.logger.info('Loaded controlset for protocol \'{}\''.format(self._controlset))
            self._errorset = commands.errorset[self._protocol]
            self.logger.info('Loaded errors for protocol \'{}\''.format(self._errorset))
            self._unitset = commands.unitset[self._protocol]
            self.logger.info('Loaded units for protocol \'{}\''.format(self._unitset))
            self._devicetypes = commands.devicetypes
            self.logger.info('Loaded device types for protocol \'{}\''.format(self._devicetypes))
            self._returnstatus = commands.returnstatus[self._protocol]
            self.logger.info('Loaded return status for protocol \'{}\''.format(self._returnstatus))
            self._setreturnstatus = commands.setreturnstatus[self._protocol]
            self.logger.info('Loaded set return status for protocol \'{}\''.format(self._setreturnstatus))
        else:
            self.logger.error('Sets for protocol {} could not be found or incomplete!'.format(self._protocol))
            return None

        # Load device dependent sets
        if self._heating_type in commands.commandset and self._heating_type in commands.operatingmodes and self._heating_type in commands.systemschemes:
            self._commandset = commands.commandset[self._heating_type]
            self.logger.info('Loaded commands for heating type \'{}\''.format(self._commandset))
            self._operatingmodes = commands.operatingmodes[self._heating_type]
            self.logger.info('Loaded operating modes for heating type \'{}\''.format(self._operatingmodes))
            self._systemschemes = commands.systemschemes[self._heating_type]
            self.logger.info('Loaded system schemes for heating type \'{}\''.format(self._systemschemes))
        else:
            sets = []
            if self._heating_type not in commands.commandset:
                sets += 'command'
            if self._heating_type not in commands.operatingmodes:
                sets += 'operating modes'
            if self._heating_type not in commands.systemschemes:
                sets += 'system schemes'

            self.logger.error('Sets {} for heating type {} could not be found!'.format(", ".join(sets), self._heating_type))
            return None

        # Init web interface
        self.init_webinterface()

    def run(self):
        '''
        Run method for the plugin
        '''
        self._connect()
        self.alive = True
        self._read_initial_values()
        self._read_timers()

    def stop(self):
        '''
        Stop method for the plugin
        '''
        if self.scheduler_get('cyclic'):
            self.scheduler_remove('cyclic')
        self.alive = False
        self._disconnect()

    def parse_item(self, item):
        '''
        Method for parsing items.
        If the item carries any viess_* field, this item is registered to the plugin.

        :param item:    The item to process.
        :type item:     object

        :return:        The item update method to be triggered if the item is changed, or None.
        :rtype:         object
        '''

        # Process the update config
        if self.has_iattr(item.conf, 'viess_update'):
            self.logger.debug("Item for requesting update for all items triggered: {}".format(item))
            return self.update_item

        # Process the timer config and fill timer dict
        if self.has_iattr(item.conf, 'viess_timer'):
            timer_app = self.get_iattr_value(item.conf, 'viess_timer')
            for commandname in self._commandset:
                if commandname.startswith(timer_app):
                    commandconf = self._commandset[commandname]
                    self.logger.debug('Process the timer config, commandname: {}'.format(commandname))
                    # {'addr': '2100', 'len': 8, 'unit': 'CT', 'set': True}
                    commandcode = (commandconf['addr']).lower()
                    if timer_app not in self._application_timer:
                        self._application_timer[timer_app] = {'item': item, 'commandcodes': []}
                    if commandcode not in self._application_timer[timer_app]['commandcodes']:
                        self._application_timer[timer_app]['commandcodes'].append(commandcode)
                    self._application_timer[timer_app]['commandcodes'].sort()
            self.logger.info('Loaded Application Timer \'{}\''.format(self._application_timer))
            # self._application_timer: {'Timer_M2': {'item': Item: heizung.heizkreis_m2.schaltzeiten, 'commandcodes': ['3000', '3008', '3010', '3018', '3020', '3028', '3030']}, 'Timer_Warmwasser': {'item': Item: heizung.warmwasser.schaltzeiten, 'commandcodes': ['2100', '2108', '2110', '2118', '2120', '2128', '2130']}}

            for subdict in self._application_timer:
                for commandcode in self._application_timer[subdict]['commandcodes']:
                    if commandcode not in self._timer_cmds:
                        self._timer_cmds.append(commandcode)
            self._timer_cmds.sort()
            self.logger.debug('Loaded Timer commands \'{}\''.format(self._timer_cmds))
            return self.update_item

        # Process the read config
        if self.has_iattr(item.conf, 'viess_read'):
            commandname = self.get_iattr_value(item.conf, 'viess_read')
            if commandname is None or commandname not in self._commandset:
                self.logger.error('Item {} contains invalid read command \'{}\'!'.format(item, commandname))
                return None

            # Remember the read config to later update this item if the configured response comes in
            self.logger.info('Item {} reads by using command \'{}\'.'.format(item, commandname))
            commandconf = self._commandset[commandname]
            commandcode = (commandconf['addr']).lower()

            # Fill item dict
            self._params[commandcode] = {'item': item, 'commandname': commandname}
            self.logger.debug('Loaded params \'{}\''.format(self._params))  # Loaded params '# Loaded params '{'27A3': {'item': 'viessmann.heizkreis_a1m1.betriebsart.betriebsart', 'commandname': 'Betrierbsart_A1M1'}}'

            # Allow items to be automatically initiated on startup
            if self.has_iattr(item.conf, 'viess_init') and self.get_iattr_value(item.conf, 'viess_init'):
                self.logger.info('Item {} is initialized on startup.'.format(item))
                if commandcode not in self._init_cmds:
                    self._init_cmds.append(commandcode)
                self.logger.debug('CommandCodes should be read at init: {}'.format(self._init_cmds))

            # Allow items to be cyclically updated
            if self.has_iattr(item.conf, 'viess_read_cycle'):
                cycle = int(self.get_iattr_value(item.conf, 'viess_read_cycle'))
                self.logger.info('Item {} should read cyclic every {} seconds.'.format(item, cycle))
                nexttime = time.time() + cycle
                if commandcode not in self._cyclic_cmds:
                    self._cyclic_cmds[commandcode] = {'cycle': cycle, 'nexttime': nexttime}
                else:
                    # If another item requested this command already with a longer cycle, use the shorter cycle now
                    if self._cyclic_cmds[commandcode]['cycle'] > cycle:
                        self._cyclic_cmds[commandcode]['cycle'] = cycle
                self.logger.debug('CommandCodes should be read cyclic: {}'.format(self._cyclic_cmds))

        # Process the write config
        if self.has_iattr(item.conf, 'viess_send'):
            if self.get_iattr_value(item.conf, 'viess_send'):
                commandname = self.get_iattr_value(item.conf, 'viess_read')
            else:
                commandname = self.get_iattr_value(item.conf, 'viess_send')

            if commandname is None or commandname not in self._commandset:
                self.logger.error('Item {} contains invalid write command \'{}\'!'.format(item, commandname))
                return None
            else:
                self.logger.info('Item {} to be written by using command \'{}\''.format(item, commandname))
                return self.update_item

    def parse_logic(self, logic):
        pass

    def update_item(self, item, caller=None, source=None, dest=None):
        '''
        Callback method for sending values to the plugin when a registered item has changed

        :param item: item to be updated towards the plugin
        :param caller: if given it represents the callers name
        :param source: if given it represents the source
        :param dest: if given it represents the dest
        '''
        if self.alive and caller != self.get_shortname():
            self.logger.info("Update item: {}, item has been changed outside this plugin".format(item.id()))
            self.logger.debug("update_item was called with item '{}' from caller '{}', source '{}' and dest '{}'".format(item, caller, source, dest))

            if self.has_iattr(item.conf, 'viess_send'):
                # Send write command
                if self.get_iattr_value(item.conf, 'viess_send'):
                    commandname = self.get_iattr_value(item.conf, 'viess_read')
                else:
                    commandname = self.get_iattr_value(item.conf, 'viess_send')
                value = item()
                self.logger.debug('Got item value to be written: {} on command name {}.'.format(value, commandname))
                if not self._send_write_command(commandname, value):
                    # create_write_command() liefert False, wenn das Schreiben fehlgeschlagen ist
                    # -> dann auch keine weitere Verarbeitung
                    self.logger.debug("Write for {} with value {} failed, reverting value, canceling followup actions".format(commandname, value))
                    item(item.property.last_value, self.get_shortname())
                    return None

                # If a read command should be sent after write
                if self.has_iattr(item.conf, 'viess_read') and self.has_iattr(item.conf, 'viess_read_afterwrite'):
                    readcommandname = self.get_iattr_value(item.conf, 'viess_read')
                    readafterwrite = self.get_iattr_value(item.conf, 'viess_read_afterwrite')
                    self.logger.debug('Attempting read after write for item {}, command {}, delay {}'.format(item, readcommandname, readafterwrite))
                    if readcommandname is not None and readafterwrite is not None:
                        aw = float(readafterwrite)
                        time.sleep(aw)
                        self._send_read_command(readcommandname)

                # If commands should be triggered after this write
                if self.has_iattr(item.conf, 'viess_trigger'):
                    trigger = self.get_iattr_value(item.conf, 'viess_trigger')
                    if trigger is None:
                        self.logger.error('Item {} contains invalid trigger command list \'{}\'!'.format(item, trigger))
                    else:
                        tdelay = 5  # default delay
                        if self.has_iattr(item.conf, 'viess_trigger_afterwrite'):
                            tdelay = float(self.get_iattr_value(item.conf, 'viess_trigger_afterwrite'))
                        if type(trigger) != list:
                            trigger = [trigger]
                        for triggername in trigger:
                            triggername = triggername.strip()
                            if triggername is not None and readafterwrite is not None:
                                self.logger.debug('Triggering command {} after write for item {}'.format(triggername, item))
                                time.sleep(tdelay)
                                self._send_read_command(triggername)

            elif self.has_iattr(item.conf, 'viess_timer'):
                timer_app = self.get_iattr_value(item.conf, 'viess_timer')
                uzsu_dict = item()
                self.logger.debug('Got changed UZSU timer: {} on timer application {}.'.format(uzsu_dict, timer_app))
                self._uzsu_dict_to_viess_timer(timer_app, uzsu_dict)

            elif self.has_iattr(item.conf, 'viess_update'):
                if item():
                    self.logger.debug('Reading of all values/items has been requested')
                    self.update_all_read_items()

    def send_cyclic_cmds(self):
        '''
        Recall function for shng scheduler. Reads all values configured to be read cyclically.
        '''

        # check if another cyclic cmd run is still active
        if self._cyclic_update_active:
            self.logger.warning('Triggered cyclic command read, but previous cyclic run is still active. Check device and cyclic configuration (too much/too short?)')
            return

        # set lock
        self._cyclic_update_active = True
        currenttime = time.time()
        read_items = 0
        for commandcode in list(self._cyclic_cmds.keys()):
            entry = self._cyclic_cmds[commandcode]
            # Is the command already due?
            if entry['nexttime'] <= currenttime:
                commandname = self._commandname_by_commandcode(commandcode)
                self.logger.info('Triggering cyclic read command: {}'.format(commandname))
                self._send_read_command(commandname)
                entry['nexttime'] = currenttime + entry['cycle']
                read_items += 1
        self._cyclic_update_active = False
        if read_items:
            self.logger.debug("cyclic command read took {:.1f} seconds for {} items".format(time.time() - currenttime, read_items))

    def update_all_read_items(self):
        '''
        Read all values preset in "commands.py" as readable
        '''
        for commandcode in list(self._params.keys()):
            commandname = self._commandname_by_commandcode(commandcode)
            self.logger.debug('Triggering read command: {} for requested value update'.format(commandname))
            self._send_read_command(commandname)

    #
    # initialization methods
    #

    def _connect(self):
        '''
        Tries to establish a connection to the heating device. To prevent
        multiple concurrent connection locking is used.

        :return: Returns True if connection was established, False otherwise
        :rtype: bool
        '''
        if self._connected and self._serial:
            return True

        self._lock.acquire()
        try:
            self.logger.info('Connecting ...')
            self._serial = serial.Serial()
            self._serial.baudrate = self._controlset['Baudrate']
            self._serial.parity = self._controlset['Parity']
            self._serial.bytesize = self._controlset['Bytesize']
            self._serial.stopbits = self._controlset['Stopbits']
            self._serial.port = self._serialport
            self._serial.timeout = 1
            self._serial.open()
            self._connected = True
            self.logger.info('Connected to {}'.format(self._serialport))
            self._connection_attempts = 0

            if not self.scheduler_get('cyclic'):
                self._create_cyclic_scheduler()
            return True
        except Exception as e:
            self.logger.error('Could not _connect to {}; Error: {}'.format(self._serialport, e))
            return False
        finally:
            self._lock.release()

    def _disconnect(self):
        '''
        Disconnect any connected devices.
        '''
        self._connected = False
        self._initialized = False
        if self.scheduler_get('cyclic'):
            self.scheduler_remove('cyclic')
        try:
            self._serial.close()
            self._serial = None
            self.logger.info('Disconnected')
        except:
            pass

    def _init_communication(self):
        '''
        After connecting to the device, setup the communication protocol

        :return: Returns True, if communication was established successfully, False otherwise
        :rtype: bool
        '''

        # just try to connect anyway; if connected, this does nothing and no harm, if not, it connects
        if not self._connect():

            self.logger.error('Init communication not possible as connect failed.')
            return False

        # initialization only necessary for P300 protocol...

        if self._protocol == 'P300':

            # if device answers SYNC b'\x16\x00\x00' with b'\x06', comm is initialized
            self.logger.info('Init Communication....')
            is_initialized = False
            initstringsent = False
            self.logger.debug('send_bytes: Send reset command {}'.format(self._int2bytes(self._controlset['Reset_Command'], 1)))
            self._send_bytes(self._int2bytes(self._controlset['Reset_Command'], 1))
            readbyte = self._read_bytes(1)
            self.logger.debug('read_bytes: read {}, last byte is {}'.format(readbyte, self._lastbyte))

            for i in range(0, 10):
                if initstringsent and self._lastbyte == self._int2bytes(self._controlset['Acknowledge'], 1):
                    # Schnittstelle hat auf den Initialisierungsstring mit OK geantwortet. Die Abfrage von Werten kann beginnen. Diese Funktion meldet hierzu True zurück.
                    is_initialized = True
                    self.logger.debug('Device acknowledged initialization')
                    break
                if self._lastbyte == self._int2bytes(self._controlset['Not_initiated'], 1):
                    # Schnittstelle ist zurückgesetzt und wartet auf Daten; Antwort b'\x05' = Warten auf Initialisierungsstring oder Antwort b'\x06' = Schnittstelle initialisiert
                    self._send_bytes(self._int2bytes(self._controlset['Sync_Command'], 3))
                    self.logger.debug('send_bytes: Send sync command {}'.format(self._int2bytes(self._controlset['Sync_Command'], 3)))
                    initstringsent = True
                elif self._lastbyte == self._int2bytes(self._controlset['Init_Error'], 1):
                    self.logger.error('The interface has reported an error (\x15), loop increment {}'.format(i))
                    self._send_bytes(self._int2bytes(self._controlset['Reset_Command'], 1))
                    self.logger.debug('send_bytes: Send reset command {}'.format(self._int2bytes(self._controlset['Reset_Command'], 1)))
                    initstringsent = False
                else:
                    self._send_bytes(self._int2bytes(self._controlset['Reset_Command'], 1))
                    self.logger.debug('send_bytes: Send reset command {}'.format(self._int2bytes(self._controlset['Reset_Command'], 1)))
                    initstringsent = False
                readbyte = self._read_bytes(1)
                self.logger.debug('read_bytes: read {}, last byte is {}'.format(readbyte, self._lastbyte))

            self.logger.info('Communication initialized: {}'.format(is_initialized))
            self._initialized = is_initialized

        else:  # at the moment the only other supported protocol is 'KW' which is not stateful
            is_initialized = True
            self._initialized = is_initialized

        return is_initialized

    def _create_cyclic_scheduler(self):
        '''
        Setup the scheduler to handle cyclic read commands and find the proper time for the cycle.
        '''
        shortestcycle = -1
        for commandname in list(self._cyclic_cmds.keys()):
            entry = self._cyclic_cmds[commandname]
            if shortestcycle == -1 or entry['cycle'] < shortestcycle:
                shortestcycle = entry['cycle']
        # Start the worker thread
        if shortestcycle != -1:
            # Balance unnecessary calls and precision
            workercycle = int(shortestcycle / 2)
            # just in case it already exists...
            if self.scheduler_get('cyclic'):
                self.scheduler_remove('cyclic')
            self.scheduler_add('cyclic', self.send_cyclic_cmds, cycle=workercycle, prio=5, offset=0)
            self.logger.info('Added cyclic worker thread ({} sec cycle). Shortest item update cycle found: {} sec.'.format(workercycle, shortestcycle))

    def _read_initial_values(self):
        '''
        Read all values configured to be read at startup / connection
        '''
        if self._init_cmds != []:
            self.logger.info('Starting initial read commands.')
            for commandcode in self._init_cmds:
                commandname = self._commandname_by_commandcode(commandcode)
                self.logger.debug('send_init_commands {}.'.format(commandname))
                self._send_read_command(commandname)
            self._initread = True
            self.logger.debug('self._initread = {}.'.format(self._initread))

    #
    # send and receive commands
    #

    def _read_timers(self):
        '''
        Read all configured timer values from device and create uzsu timer dict
        '''
        if self._application_timer is not []:
            self.logger.info('Starting timer read commands.')
            for timer_app in self._application_timer:
                for commandcode in self._application_timer[timer_app]['commandcodes']:
                    commandname = self._commandname_by_commandcode(commandcode)
                    self.logger.debug('send_timer_commands {}.'.format(commandname))
                    self._send_read_command(commandname)
            self._timerread = True
            self.logger.debug('Timer Readout done = {}.'.format(self._timerread))
            self._viess_dict_to_uzsu_dict()

    def _send_read_command(self, commandname):
        '''
        Create formatted command sequence from command name and send to device

        :param commandname: Command for which to create command sequence as defined in "commands.py"
        :type commandname: str
        '''

        # A read_request telegram looks like this: ACK (1 byte), startbyte (1 byte), data length in bytes (1 byte), request/response (1 byte), read/write (1 byte), addr (2 byte), amount of value bytes expected in answer (1 byte), checksum (1 byte)
        self.logger.debug('Got a new read job: Command {}'.format(commandname))

        # Get command config
        commandconf = self._commandset[commandname]
        self.logger.debug('Command config: {}'.format(commandconf))
        commandcode = (commandconf['addr']).lower()
        commandvaluebytes = commandconf['len']

        # Build packet for read commands
        #
        # at the moment this only has to differentiate between protocols P300 and KW
        # these are basically similar, only P300 is an evolution of KW adding
        # stateful connections, command length and checksum
        #
        # so for the time being the easy way is one code path for both protocols which
        # omits P300 elements from the built byte string.
        # Later additions of other protocols (like GWG) might have to bring a second
        # code path for proper processing
        packet = bytearray()
        packet.extend(self._int2bytes(self._controlset['StartByte'], 1))
        if self._protocol == 'P300':
            packet.extend(self._int2bytes(self._controlset['Command_bytes_read'], 1))
            packet.extend(self._int2bytes(self._controlset['Request'], 1))
        packet.extend(self._int2bytes(self._controlset['Read'], 1))
        packet.extend(bytes.fromhex(commandcode))
        packet.extend(self._int2bytes(commandvaluebytes, 1))
        if self._protocol == 'P300':
            packet.extend(self._int2bytes(self._calc_checksum(packet), 1))
        self.logger.debug('Preparing command {} with packet to be sent as hexstring: {} and as bytes: {}'.format(commandname, self._bytes2hexstring(packet), packet))
        if self._protocol == 'P300':
            packetlen_response = int(self._controlset['Command_bytes_read']) + 4 + int(commandvaluebytes)
        else:
            packetlen_response = int(commandvaluebytes)

        # hand over built packet to send_command
        self._send_command(packet, packetlen_response, commandname)

    def _send_write_command(self, commandname, value=None):
        '''
        Create formatted command sequence from command name and send to device

        :param commandname: Command for which to create command sequence as defined in "commands.py"
        :type commandname: str
        :param value: Value to write to device, None if not applicable
        :return: Return True, if write was successfully acknowledged by device, False otherwise
        :rtype: bool
        '''

        # A write_request telegram looks like this: ACK (1 byte), startbyte (1 byte), data length in bytes (1 byte), request/response (1 byte), read/write (1 byte), addr (2 byte), amount of bytes to be written (1 byte), value (bytes as per last byte), checksum (1 byte)
        self.logger.debug('Got a new write job: Command {} with value {}'.format(commandname, value))

        # Get command config
        commandconf = self._commandset[commandname]
        self.logger.debug('Command config: {}'.format(commandconf))
        commandcode = (commandconf['addr']).lower()
        commandvaluebytes = commandconf['len']
        commandunit = commandconf['unit']

        if commandunit == 'BA':

            # try to convert BA string to byte value, setting str values will fail
            # this will not work properly if multiple entries have the same value!
            try:
                value = int(dict(map(reversed, self._operatingmodes.items()))[value])
                commandunit = 'IUNON'
                commandsigned = False
            except KeyError:
                # value doesn't exist in operatingmodes. don't know what to do
                self.logger.error('Value {} not defined in operating modes for device {}'.format(value, self._heating_type))
                return False

        set_allowed = bool(commandconf['set'])
        unitconf = self._unitset[commandunit]
        self.logger.debug('Unit defined to {} with config{}.'.format(commandunit, unitconf))
        commandvalueresult = unitconf['type']
        commandsigned = unitconf['signed']
        commandtransform = unitconf['read_value_transform']
        if 'min_value' in commandconf:
            min_allowed_value = commandconf['min_value']
        else:
            min_allowed_value = None
        if 'max_value' in commandconf:
            max_allowed_value = commandconf['max_value']
        else:
            max_allowed_value = None

        try:
            # check if command is allowed to write
            if set_allowed:
                # check, if value has content
                if value is not None and value != '':
                    # check, if values to be written are in allowed range or None
                    if (min_allowed_value is None or min_allowed_value <= value) and (max_allowed_value is None or max_allowed_value >= value):
                        # Create valuebytes
                        if commandvalueresult == 'datetime' or commandvalueresult == 'date':
                            try:
                                datestring = dateutil.parser.isoparse(value).strftime("%Y%m%d%w%H%M%S")
                                # Viessmann erwartet 2 digits für Wochentag, daher wird hier noch eine 0 eingefügt
                                datestring = datestring[:8] + '0' + datestring[8:]
                                valuebytes = bytes.fromhex(datestring)
                                self.logger.debug('Created value bytes for type {} as bytes: {}'.format(commandvalueresult, valuebytes))
                            except Exception as e:
                                self.logger.error('Incorrect data format, YYYY-MM-DD expected; Error: {}'.format(e))
                                return False
                        elif commandvalueresult == 'timer':
                            try:
                                times = ""
                                for switching_time in value:
                                    an = self._encode_timer(switching_time["An"])
                                    aus = self._encode_timer(switching_time["Aus"])
                                    # times += f"{an:02x}{aus:02x}"
                                    times += "{:02x}".format(an) + "{:02x}".format(aus)
                                valuebytes = bytes.fromhex(times)
                                self.logger.debug('Created value bytes for type {} as hexstring: {} and as bytes: {}'.format(commandvalueresult, self._bytes2hexstring(valuebytes), valuebytes))
                            except Exception as e:
                                self.logger.error('Incorrect data format, (An: hh:mm Aus: hh:mm) expected; Error: {}'.format(e))
                                return False
                        elif commandvalueresult == 'integer' or commandvalueresult == 'list':
                            if commandtransform == 'int':
                                value = self._value_transform_write(value, commandtransform)
                                self.logger.debug('Transformed value using method {} to {}'.format(commandtransform, value))
                            elif commandtransform == 'bool':
                                value = bool(value)
                            else:
                                value = int(value)
                            valuebytes = self._int2bytes(value, commandvaluebytes)
                            self.logger.debug('Created value bytes for type {} as hexstring: {} and as bytes: {}'.format(commandvalueresult, self._bytes2hexstring(valuebytes), valuebytes))
                        else:
                            self.logger.error('Type not definied for creating write command bytes')
                            return False

                        # Calculate length of payload (telegram header for write with 5 byte + amount of valuebytes)
                        payloadlength = int(self._controlset['Command_bytes_write']) + int(commandvaluebytes)
                        self.logger.debug('Payload length is: {} bytes.'.format(payloadlength))

                        # Build packet with value bytes for write commands
                        #
                        # at the moment this only has to differentiate between protocols P300 and KW
                        # these are basically similar, only P300 is an evolution of KW adding
                        # stateful connections, command length and checksum
                        #
                        # so for the time being the easy way is one code path for both protocols which
                        # omits P300 elements from the built byte string.
                        # Later additions of other protocols (like GWG) might have to bring a second
                        # code path for proper processing
                        packet = bytearray()
                        packet.extend(self._int2bytes(self._controlset['StartByte'], 1))
                        if self._protocol == 'P300':
                            packet.extend(self._int2bytes(payloadlength, 1))
                            packet.extend(self._int2bytes(self._controlset['Request'], 1))
                        packet.extend(self._int2bytes(self._controlset['Write'], 1))
                        packet.extend(bytes.fromhex(commandcode))
                        packet.extend(self._int2bytes(commandvaluebytes, 1, commandsigned))
                        packet.extend(valuebytes)
                        if self._protocol == 'P300':
                            packet.extend(self._int2bytes(self._calc_checksum(packet), 1))
                        self.logger.debug('Preparing command {} with value {} (transformed to value byte \'{}\') to be sent as packet {}.'.format(commandname, value, self._bytes2hexstring(valuebytes), self._bytes2hexstring(packet)))
                        if self._protocol == 'P300':
                            packetlen_response = int(self._controlset['Command_bytes_read']) + 4
                        else:
                            packetlen_response = 1

                        # hand over built packet to send_command
                        self._send_command(packet, packetlen_response, commandname, False)
                    else:
                        self.logger.error('No valid value to be sent')
                        return False
                else:
                    self.logger.error('No value handed over')
                    return False
            else:
                self.logger.error('Command at Heating is not allowed to be sent')
                return False

        except Exception as e:
            self.logger.debug('create_write_command failed with error: {}.'.format(e))
            return False

        return True

    def _send_command(self, packet, packetlen_response, rcommandcode='', read_response=True):
        '''
        Send command sequence to device

        :param packet: Command sequence to send
        :type packet: bytearray
        :param packetlen_response: number of bytes expected in reply
        :type packetlen_response: int
        :param rcommandcode: Commandcode used for request (only needed for KW protocol)
        :type rcommandcode: str
        :param read_response: True if command was read command and value is expected, False if only status byte is expected (only needed for KW protocol)
        :type read_response: bool
        '''
        if not self._connected:
            self.logger.error('Not connected, trying to reconnect.')
            if not self._connect():
                self.logger.error('Could not connect to serial device')
                return

        try:
            self._lock.acquire()
            if not self._initialized or (time.time() - 500) > self._lastbytetime:
                if self._initialized:
                    self.logger.info('Communication timed out, trying to reestablish communication.')
                else:
                    self.logger.warning('Communication no longer initialized, trying to reestablish.')
                self._init_communication()

            if self._initialized:
                # send query
                try:
                    if self._protocol == 'KW':
                        # wait for 0x05 from device
                        self._read_bytes(1)
                    self._send_bytes(packet)
                    self.logger.debug('Successfully sent packet: {}'.format(self._bytes2hexstring(packet)))
                    time.sleep(0.1)
                except IOError as io:
                    raise IOError('IO Error: {}'.format(io))
                except Exception as e:
                    raise Exception('Exception while sending: {}'.format(e))
                # receive response
                response_packet = bytearray()
                try:
                    self.logger.debug('Trying to receive {} bytes of the response.'.format(packetlen_response))
                    chunk = self._read_bytes(packetlen_response)

                    if self._protocol == 'P300':
                        time.sleep(0.1)
                        self.logger.debug('Received {} bytes chunk of response as hexstring {} and as bytes {}'.format(len(chunk), self._bytes2hexstring(chunk), chunk))
                        if len(chunk) != 0:
                            if chunk[:1] == self._int2bytes(self._controlset['Error'], 1):
                                self.logger.error('Interface returned error! response was: {}'.format(chunk))
                            elif len(chunk) == 1 and chunk[:1] == self._int2bytes(self._controlset['Not_initiated'], 1):
                                self.logger.error('Received invalid chunk, connection not initialized. Forcing re-initialize...')
                                self._initialized = False
                            elif chunk[:1] != self._int2bytes(self._controlset['Acknowledge'], 1):
                                self.logger.error('Received invalid chunk, not starting with ACK! response was: {}'.format(chunk))
                            else:
                                # self.logger.info('Received chunk! response was: {}, Hand over to parse_response now.format(chunk))
                                response_packet.extend(chunk)
                                self._parse_response(response_packet)
                        else:
                            self.logger.error('Received 0 bytes chunk - ignoring response_packet! chunk was: {}'.format(chunk))
                    elif self._protocol == 'KW':
                        self.logger.debug('Received {} bytes chunk of response as hexstring {} and as bytes {}'.format(len(chunk), self._bytes2hexstring(chunk), chunk))
                        if len(chunk) != 0:
                            # self.logger.info('Received chunk! response was: {}, Hand over to parse_response now.format(chunk))
                            response_packet.extend(chunk)
                            self._parse_response(response_packet, rcommandcode, read_response)
                        else:
                            self.logger.error('Received 0 bytes chunk - ignoring response_packet! chunk was: {}'.format(chunk))
                except socket.timeout:
                    raise Exception('Error receiving response: time-out')
                except IOError as io:
                    raise IOError('IO Error: {}'.format(io))
                except Exception as e:
                    raise Exception('Error receiving response: {}'.format(e))
            else:
                raise Exception('Interface not initialized!')
        except IOError as io:
            self.logger.error('send_command failed with IO error: {}.'.format(io))
            self.logger.error('Trying to reconnect (disconnecting, connecting')
            self._disconnect()
        except Exception as e:
            self.logger.error('send_command failed with error: {}.'.format(e))
        finally:
            self._lock.release()

    def _send_bytes(self, packet):
        '''
        Send data to device

        :param packet: Data to be sent
        :type packet: bytearray
        :return: Returns False, if no connection is established or write failed; True otherwise
        :rtype: bool
        '''
        if not self._connected:
            return False

        try:
            self._serial.write(packet)
        except serial.SerialTimeoutException:
            return False

        # self.logger.debug('send_bytes: Sent {}'.format(packet))
        return True

    def _read_bytes(self, length):
        '''
        Try to read bytes from device

        :param length: Number of bytes to read
        :type length: int
        :return: Number of bytes actually read
        :rtype: int
        '''

        if not self._connected:
            return 0

        totalreadbytes = bytes()
        # self.logger.debug('read_bytes: Start read')
        starttime = time.time()

        # don't wait for input indefinitely, stop after self._timeout seconds
        while time.time() <= starttime + self._timeout:
            readbyte = self._serial.read()
            self._lastbyte = readbyte
            # self.logger.debug('read_bytes: Read {}'.format(readbyte))
            if readbyte != b'':
                self._lastbytetime = time.time()
            else:
                return totalreadbytes
            totalreadbytes += readbyte
            if len(totalreadbytes) >= length:
                return totalreadbytes

        # timeout reached, did we read anything?
        if not totalreadbytes:

            # just in case, force plugin to reconnect
            self._connected = False
            self._initialized = False

        # return what we got so far, might be 0
        return totalreadbytes

    def _parse_response(self, response, rcommandcode='', read_response=True):
        '''
        Process device response data, try to parse type and value and assign value to associated item

        :param response: Data received from device
        :type response: bytearray
        :param rcommandcode: Commandcode used for request (only needed for KW protocol)
        :type rcommandcode: str
        :param read_response: True if command was read command and value is expected, False if only status byte is expected (only needed for KW protocol)
        :type read_response: bool
        '''

        if self._protocol == 'P300':

            # A read_response telegram looks like this: ACK (1 byte), startbyte (1 byte), data length in bytes (1 byte), request/response (1 byte), read/write (1 byte), addr (2 byte), amount of valuebytes (1 byte), value (bytes as per last byte), checksum (1 byte)
            # A write_response telegram looks like this: ACK (1 byte), startbyte (1 byte), data length in bytes (1 byte), request/response (1 byte), read/write (1 byte), addr (2 byte), amount of bytes written (1 byte), checksum (1 byte)

            # Validate checksum
            checksum = self._calc_checksum(response[1:len(response) - 1])  # first, cut first byte (ACK) and last byte (checksum) and then calculate checksum
            received_checksum = response[len(response) - 1]
            if received_checksum != checksum:
                self.logger.error('Calculated checksum {} does not match received checksum of {}! Ignoring reponse.'.format(checksum, received_checksum))
                return

            # Extract command/address, valuebytes and valuebytecount out of response
            commandcode = response[5:7].hex()
            responsetypecode = response[3]  # 0x00 = Anfrage, 0x01 = Antwort, 0x03 = Fehler
            responsedatacode = response[4]  # 0x01 = ReadData, 0x02 = WriteData, 0x07 = Function Call
            valuebytecount = response[7]

            # Extract databytes out of response
            rawdatabytes = bytearray()
            rawdatabytes.extend(response[8:8 + (valuebytecount)])
        elif self._protocol == 'KW':

            # imitate P300 response code data for easier combined handling afterwards
            # a read_response telegram consists only of the value bytes
            # a write_response telegram is 0x00 for OK, 0xXX for error
            if rcommandcode == '':
                self.logger.error('trying to parse KW protocol response, but rcommandcode not set in _parse_response. This should not happen...')
                return

            if read_response:
                # value response to read request, no error detection (except implausible value)
                responsedatacode = 1
            else:
                # status response to write request
                responsedatacode = 2
                if len(rawdatabytes) == 1 and rawdatabytes[0] != 0:
                    # error if status reply is not 0x00
                    responsetypecode = 3

            responsetypecode = 1
            commandcode = self._commandset[rcommandcode]['addr']
            valuebytecount = len(response)
            rawdatabytes = response

        self.logger.debug('Response decoded to: commandcode: {}, responsedatacode: {}, valuebytecount: {}'.format(commandcode, responsedatacode, valuebytecount))
        self.logger.debug('Rawdatabytes formatted: {} and unformatted: {}'.format(self._bytes2hexstring(rawdatabytes), rawdatabytes))

        # Process response for items if read response and not error
        if responsedatacode == 1 and responsetypecode != 3:

            # Process response for items in item-dict using the commandcode
            if commandcode in self._params.keys():

                # Find corresponding item and commandname
                item = self._params[commandcode]['item']
                commandname = self._params[commandcode]['commandname']
                self.logger.debug('Corresponding Item: {}; Corresponding commandname: {}'.format(item.id(), commandname))

                # Get command and respective unit config
                commandconf = self._commandset[commandname]
                commandvaluebytes = commandconf['len']
                commandunit = commandconf['unit']
                unitconf = self._unitset[commandunit]
                commandsigned = unitconf['signed']
                valuetransform = unitconf['read_value_transform']
                self.logger.debug('Unit defined to {} with config {}.'.format(commandunit, unitconf))

                # start value decode
                if commandunit == 'CT':
                    rawdatastring = rawdatabytes.hex()
                    timer = self._decode_timer(rawdatastring)
                    # fill list
                    timer = [{'An': on_time, 'Aus': off_time}
                             for on_time, off_time in zip(timer, timer)]
                    value = timer
                    self.logger.debug('Matched command {} and read transformed timer {} and byte length {}.'.format(commandname, value, commandvaluebytes))
                    # Split timer list and put it the child items, which were created by struct.timer in iso time format
                    try:
                        for child in item.return_children():
                            child_item = str(child.id())
                            if child_item.endswith('an1'):
                                child(timer[0]['An'], self.get_shortname())
                                # child(datetime.strptime(timer[0]['An'], '%H:%M').time().isoformat())
                            elif child_item.endswith('aus1'):
                                child(timer[0]['Aus'], self.get_shortname())
                            elif child_item.endswith('an2'):
                                child(timer[1]['An'], self.get_shortname())
                            elif child_item.endswith('aus2'):
                                child(timer[1]['Aus'], self.get_shortname())
                            elif child_item.endswith('an3'):
                                child(timer[2]['An'], self.get_shortname())
                            elif child_item.endswith('aus3'):
                                child(timer[2]['Aus'], self.get_shortname())
                            elif child_item.endswith('an4'):
                                child(timer[3]['An'], self.get_shortname())
                            elif child_item.endswith('aus4'):
                                child(timer[3]['Aus'], self.get_shortname())
                    except:
                        self.logger.debug('No child items for timer found (use timer.structs) or value no valid')

                elif commandunit == 'TI':
                    rawdatastring = rawdatabytes.hex()
                    rawdata = bytearray()
                    rawdata.extend(map(ord, rawdatastring))
                    # decode datetime
                    value = datetime.strptime(rawdata.decode(), '%Y%m%d%W%H%M%S').isoformat()
                    self.logger.debug('Matched command {} and read transformed datetime {} and byte length {}.'.format(commandname, value, commandvaluebytes))
                elif commandunit == 'DA':
                    rawdatastring = rawdatabytes.hex()
                    rawdata = bytearray()
                    rawdata.extend(map(ord, rawdatastring))
                    # decode date
                    value = datetime.strptime(rawdata.decode(), '%Y%m%d%W%H%M%S').date().isoformat()
                    self.logger.debug('Matched command {} and read transformed datetime {} and byte length {}.'.format(commandname, value, commandvaluebytes))
                elif commandunit == 'ES':
                    # erstes Byte = Fehlercode; folgenden 8 Byte = Systemzeit
                    errorcode = (rawdatabytes[:1]).hex()
                    # errorquerytime = (rawdatabytes[1:8]).hex()
                    value = self._error_decode(errorcode)
                    self.logger.debug('Matched command {} and read transformed errorcode {} (raw value was {}) and byte length {}.'.format(commandname, value, errorcode, commandvaluebytes))
                elif commandunit == 'SC':
                    # erstes Byte = Anlagenschema
                    systemschemescode = (rawdatabytes[:1]).hex()
                    value = self._systemscheme_decode(systemschemescode)
                    self.logger.debug('Matched command {} and read transformed system scheme {} (raw value was {}) and byte length {}.'.format(commandname, value, systemschemescode, commandvaluebytes))
                elif commandunit == 'BA':
                    operatingmodecode = (rawdatabytes[:1]).hex()
                    value = self._operatingmode_decode(operatingmodecode)
                    self.logger.debug('Matched command {} and read transformed operating mode {} (raw value was {}) and byte length {}.'.format(commandname, value, operatingmodecode, commandvaluebytes))
                elif commandunit == 'DT':
                    # device type has 8 bytes, but first 4 bytes are device type indicator
                    devicetypebytes = rawdatabytes[:2].hex()
                    value = self._devicetype_decode(devicetypebytes).upper()
                    self.logger.debug('Matched command {} and read transformed device type {} (raw value was {}) and byte length {}.'.format(commandname, value, devicetypebytes, commandvaluebytes))
                elif commandunit == 'SN':
                    # serial number has 7 bytes,
                    serialnummerbytes = rawdatabytes[:7]
                    value = self._serialnumber_decode(serialnummerbytes)
                    self.logger.debug('Matched command {} and read transformed serial number {} (raw value was {}) and byte length {}.'.format(commandname, value, serialnummerbytes, commandvaluebytes))
                else:
                    rawvalue = self._bytes2int(rawdatabytes, commandsigned)
                    value = self._value_transform_read(rawvalue, valuetransform)
                    self.logger.debug('Matched command {} and read transformed value {} (integer raw value was {}) and byte length {}.'.format(commandname, value, rawvalue, commandvaluebytes))

                # Update item
                item(value, self.get_shortname())

            # Process response for timers in timer-dict using the commandcode
            if commandcode in self._timer_cmds:
                self.logger.debug('Parse_Response_Timer: {}.'.format(commandcode))

                # Find corresponding commandname
                commandname = self._commandname_by_commandcode(commandcode)

                # Find timer application
                for timer in self._application_timer:
                    if commandcode in self._application_timer[timer]['commandcodes']:
                        timer_app = timer

                # Get commandconf and respective unit config
                commandconf = self._commandset[commandname]
                commandvaluebytes = commandconf['len']
                commandunit = commandconf['unit']

                # Value decode
                if commandunit == 'CT':
                    rawdatastring = rawdatabytes.hex()
                    timer = self._decode_timer(rawdatastring)
                    # fill single timer list
                    timer = [{'An': on_time, 'Aus': off_time}
                             for on_time, off_time in zip(timer, timer)]
                    self.logger.debug('Matched timer command {} for application timer {} and read transformed timer {} and byte length {}.'.format(commandname, timer_app, timer, commandvaluebytes))

                    # Fill timer dict
                    if timer_app not in self._viess_timer_dict:
                        self._viess_timer_dict[timer_app] = {}

                    self._viess_timer_dict[timer_app][commandname] = timer
                    self.logger.debug('Viessmann timer dict: {}.'.format(self._viess_timer_dict))
                    # self._viess_timer_dict: {'Timer_M2': {'Timer_M2_Di': [{'An': '04:10', 'Aus': '07:00'}, {'An': '13:30', 'Aus': '20:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_M2_Mo': [{'An': '04:10', 'Aus': '07:00'}, {'An': '13:30', 'Aus': '20:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_M2_Sa': [{'An': '04:40', 'Aus': '21:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_M2_So': [{'An': '04:40', 'Aus': '21:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_M2_Do': [{'An': '04:10', 'Aus': '07:00'}, {'An': '13:30', 'Aus': '20:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_M2_Mi': [{'An': '04:10', 'Aus': '07:00'}, {'An': '13:30', 'Aus': '20:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_M2_Fr': [{'An': '04:10', 'Aus': '07:00'}, {'An': '13:30', 'Aus': '20:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}]}, 'Timer_Warmwasser': {'Timer_Warmwasser_Fr': [{'An': '04:00', 'Aus': '04:40'}, {'An': '16:30', 'Aus': '17:10'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_Warmwasser_Mi': [{'An': '04:00', 'Aus': '04:40'}, {'An': '16:30', 'Aus': '17:10'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_Warmwasser_Mo': [{'An': '04:00', 'Aus': '04:40'}, {'An': '16:30', 'Aus': '17:10'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_Warmwasser_Do': [{'An': '04:00', 'Aus': '04:40'}, {'An': '16:30', 'Aus': '17:10'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_Warmwasser_Sa': [{'An': '04:00', 'Aus': '04:40'}, {'An': '16:30', 'Aus': '17:10'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_Warmwasser_Di': [{'An': '04:00', 'Aus': '04:40'}, {'An': '16:30', 'Aus': '17:10'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}], 'Timer_Warmwasser_So': [{'An': '04:00', 'Aus': '04:40'}, {'An': '16:30', 'Aus': '17:10'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}]}}

        # Handling of write command response if not error
        elif responsedatacode == 2 and responsetypecode != 3:
            self.logger.info('Write request of adress {} successfull writing {} bytes.'.format(commandcode, valuebytecount))
        else:
            self.logger.error('Write request of adress {} NOT successfull writing {} bytes.'.format(commandcode, valuebytecount))

    #
    # convert data types
    #

    def _viess_dict_to_uzsu_dict(self):
        '''
        Convert data read from device to UZSU compatible struct.
        Input is taken from self._viess_timer_dict, output is written to
        self._uzsu_dict
        '''

        # set variables
        dict_timer = {}
        empty_time = '00:00'

        shitems = Items.get_instance()
        try:
            sunset = shitems.return_item('env.location.sunset')().strftime("%H:%M")
            sunrise = shitems.return_item('env.location.sunrise')().strftime("%H:%M")
        except:
            sunset = '21:00'
            sunrise = '06:00'

        # convert all switching times with corresponding app and days to timer-dict
        for application in self._viess_timer_dict:
            if application not in dict_timer:
                dict_timer[application] = {}
            for application_day in self._viess_timer_dict[application]:
                timer = self._viess_timer_dict[application][application_day]
                day = application_day[(application_day.rfind('_') + 1):len(application_day)].lower()

                # normalize days
                for element in self._wochentage:
                    if day in self._wochentage[element]:
                        weekday = element

                for entry in timer:
                    for event, sw_time in entry.items():
                        if sw_time != empty_time:
                            value = 1 if event == "An" else 0
                            if sw_time not in dict_timer[application]:
                                dict_timer[application][sw_time] = {}
                            if value not in dict_timer[application][sw_time]:
                                dict_timer[application][sw_time][value] = []
                            dict_timer[application][sw_time][value].append(weekday)

        self.logger.debug('Viessmann timer dict for UZSU: {}.'.format(dict_timer))

        # find items, read UZSU-dict, convert to list of switching times, update item
        for application in dict_timer:
            item = self._application_timer[application]['item']

            # read UZSU-dict (or use preset if empty)
            uzsu_dict = item()
            if not item():
                uzsu_dict = {'lastvalue': '0', 'sunset': sunset, 'list': [], 'active': True, 'interpolation': {'initage': '', 'initialized': True, 'itemtype': 'bool', 'interval': '', 'type': 'none'}, 'sunrise': sunrise}

            # create empty list
            uzsu_dict['list'] = []

            # fill list with switching times
            for sw_time in sorted(dict_timer[application].keys()):
                for key in dict_timer[application][sw_time]:
                    rrule = 'FREQ=WEEKLY;BYDAY=' + ",".join(dict_timer[application][sw_time][key])
                    uzsu_dict['list'].append({'time': sw_time, 'rrule': rrule, 'value': str(key), 'active': True})

            # update item
            item(uzsu_dict, self.get_shortname())

    def _uzsu_dict_to_viess_timer(self, timer_app, uzsu_dict):
        '''
        Convert UZSU dict from item/visu for selected application into separate
        on/off time events and write all timers to the device

        :param timer_app: Application for which the timer should be written, as in "commands.py"
        :type timer_app: str
        :param uzsu_dict: UZSU-compatible dict with timer data
        :type uzsu_dict: dict
        '''
        if self._timerread:

            # set variables
            commandnames = set()
            timer_dict = {}
            an = {}
            aus = {}

            # quit if timer_app not defined
            if timer_app not in self._application_timer:
                return

            commandnames.update([self._commandname_by_commandcode(code) for code in self._application_timer[timer_app]['commandcodes']])
            self.logger.debug('Commandnames: {}.'.format(commandnames))

            # find switching times and create lists for on and off operations
            for sw_time in uzsu_dict['list']:
                myDays = sw_time['rrule'].split(';')[1].split("=")[1].split(",")
                for day in myDays:
                    if sw_time['value'] == '1' and sw_time['active']:
                        if day not in an:
                            an[day] = []
                        an[day].append(sw_time['time'])
                for day in myDays:
                    if sw_time['value'] == '0' and sw_time['active']:
                        if day not in aus:
                            aus[day] = []
                        aus[day].append(sw_time['time'])

            # sort daily lists
            for day in an:
                an[day].sort()
            self.logger.debug('An: {}.'.format(an))
            for day in aus:
                aus[day].sort()
            self.logger.debug('Aus: {}.'.format(aus))

            # create timer dict in Viessmann format for all weekdays
            for commandname in commandnames:
                self.logger.debug('Commandname in process: {}.'.format(commandname))
                # create empty dict
                timer_dict[commandname] = [{'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}, {'An': '00:00', 'Aus': '00:00'}]
                # get current day
                wday = commandname[(commandname.rfind('_') + 1):len(commandname)].lower()
                # normalize day
                for element in self._wochentage:
                    if wday in self._wochentage[element]:
                        wday = element
                # transfer switching times
                for idx, val in enumerate(an[wday]):
                    timer_dict[commandname][idx]['An'] = val
                for idx, val in enumerate(aus[wday]):
                    timer_dict[commandname][idx]['Aus'] = val
            self.logger.debug('Timer-dict for update of items: {}.'.format(timer_dict))

            # write all timer dicts to device
            for commandname in timer_dict:
                value = timer_dict[commandname]
                self.logger.debug('Got item value to be written: {} on command name {}.'.format(value, commandname))
                self._send_write_command(commandname, value)

    def _calc_checksum(self, packet):
        '''
        Calculate checksum for P300 protocol packets

        :parameter packet: Data packet for which to calculate checksum
        :type packet: bytearray
        :return: Calculated checksum
        :rtype: int
        '''
        checksum = 0
        if len(packet) > 0:
            if packet[:1] == b'\x41':
                packet = packet[1:]
                checksum = sum(packet)
                checksum = checksum - int(checksum / 256) * 256
            else:
                self.logger.error('bytes to calculate checksum from not starting with start byte')
        else:
            self.logger.error('No bytes received to calculate checksum')
        return checksum

    def _int2bytes(self, value, length, signed=False):
        '''
        Convert value to bytearray with respect to defined length and sign format.
        Value exceeding limit set by length and sign will be truncated

        :parameter value: Value to convert
        :type value: int
        :parameter length: number of bytes to create
        :type length: int
        :parameter signed: True if result should be a signed int, False for unsigned
        :type signed: bool
        :return: Converted value
        :rtype: bytearray
        '''
        value = value % (2 ** (length * 8))
        return value.to_bytes(length, byteorder='big', signed=signed)

    def _bytes2int(self, rawbytes, signed):
        '''
        Convert bytearray to value with respect to sign format

        :parameter rawbytes: Bytes to convert
        :type value: bytearray
        :parameter signed: True if result should be a signed int, False for unsigned
        :type signed: bool
        :return: Converted value
        :rtype: int
        '''
        return int.from_bytes(rawbytes, byteorder='little', signed=signed)

    def _bytes2hexstring(self, bytesvalue):
        '''
        Create hex-formatted string from bytearray
        :param bytesvalue: Bytes to convert
        :type bytesvalue: bytearray
        :return: Converted hex string
        :rtype: str
        '''
        return "".join("{:02x}".format(c) for c in bytesvalue)

    def _decode_rawvalue(self, rawdatabytes, commandsigned):
        '''
        Convert little-endian byte sequence to int value

        :param rawdatabytes: Bytes to convert
        :type rawdatabytes: bytearray
        :param commandsigned: 'signed' if value should be interpreted as signed
        :type commandsigned: str
        :return: Converted value
        :rtype: int
        '''
        rawvalue = 0
        for i in range(len(rawdatabytes)):
            leftbyte = rawdatabytes[0]
            value = int(leftbyte * pow(256, i))
            rawvalue += value
            rawdatabytes = rawdatabytes[1:]
        # Signed/Unsigned berücksichtigen
        if commandsigned == 'signed' and rawvalue > int(pow(256, i) / 2 - 1):
            rawvalue = (pow(256, i) - rawvalue) * (-1)
        return rawvalue

    def _decode_timer(self, rawdatabytes):
        '''
        Generator to convert byte sequence to a number of time strings hh:mm

        :param rawdatabytes: Bytes to convert
        :type rawdatabytes: bytearray
        '''
        while rawdatabytes:
            hours, minutes = divmod(int(rawdatabytes[:2], 16), 8)
            if minutes >= 6 or hours >= 24:
                yield "{}".format('00:00')  # f"00:00"  # keine gültiger Zeit-Wert
            else:
                yield "{:02d}:{:02d}".format(hours, minutes * 10)   # f"{hours:02d}:{minutes*10:02d}"
            rawdatabytes = rawdatabytes[2:]
        return None

    def _encode_timer(self, switching_time):
        '''
        Convert time string to encoded time value for timer application

        :param switching_time: time value in 'hh:mm' format
        :type switching_time: str
        :return: Encoded time value
        :rtype: int
        '''
        if switching_time == "00:00":
            return 0xff
        clocktime = re.compile(r'(\d\d):(\d\d)')
        mo = clocktime.search(switching_time)
        number = int(mo.group(1)) * 8 + int(mo.group(2)) // 10
        return number

    def _value_transform_read(self, value, transform):
        '''
        Transform value according to protocol specification for writing to device

        :param value: Value to transform
        :param transform: Specification for transforming
        :return: Transformed value
        '''
        if transform == 'bool':
            return bool(value)
        elif transform.isdigit():
            return round(value / int(transform), 2)
        else:
            return int(value)

    def _value_transform_write(self, value, transform):
        '''
        Transform value according to protocol requirement after reading from device

        :param value: Value to transform
        :type value: int
        :param transform: Specification for transforming
        :type transform: int
        :return: Transformed value
        :rtype: int
        '''
        return int(value * int(transform))

    def _error_decode(self, value):
        '''
        Decode error value from device if defined, else return error as string
        '''
        if value in self._errorset:
            errorstring = str(self._errorset[value])
        else:
            errorstring = str(value)
        return errorstring

    def _systemscheme_decode(self, value):
        '''
        Decode schema value from device if possible, else return schema as string
        '''
        if value in self._systemschemes:
            systemscheme = str(self._systemschemes[value])
        else:
            systemscheme = str(value)
        return systemscheme

    def _operatingmode_decode(self, value):
        '''
        Decode operating mode value from device if possible, else return mode as string
        '''
        if value in self._operatingmodes:
            operatingmode = str(self._operatingmodes[value])
        else:
            operatingmode = str(value)
        return operatingmode

    def _devicetype_decode(self, value):
        '''
        Decode device type value if possible, else return device type as string
        '''
        if value in self._devicetypes:
            devicetypes = str(self._devicetypes[value])
        else:
            devicetypes = str(value)
        return devicetypes

    def _serialnumber_decode(self, serialnummerbytes):
        '''
        Decode serial number from device response
        '''
        serialnumber = 0
        serialnummerbytes.reverse()
        for byte in range(0, len(serialnummerbytes)):
            serialnumber += (serialnummerbytes[byte] - 48) * 10 ** byte
        return hex(serialnumber).upper()

    def _commandname_by_commandcode(self, commandcode):
        '''
        Find matching command name from "commands.py" for given command address

        :param commandcode: address of command
        :type commandcode: str
        :return: name of matching command or None if not found
        '''
        for commandname in self._commandset.keys():
            if self._commandset[commandname]['addr'].lower() == commandcode:
                return commandname
        return None

    #
    # webinterface
    #

    def init_webinterface(self):
        """"
        Initialize the web interface for this plugin

        This method is only needed if the plugin is implementing a web interface
        """
        try:
            self.mod_http = Modules.get_instance().get_module(
                'http')  # try/except to handle running in a core version that does not support modules
        except:
            self.mod_http = None
        if self.mod_http is None:
            self.logger.error("Not initializing the web interface")
            return False

        import sys
        if "SmartPluginWebIf" not in list(sys.modules['lib.model.smartplugin'].__dict__):
            self.logger.warning("Web interface needs SmartHomeNG v1.5 and up. Not initializing the web interface")
            return False

        # set application configuration for cherrypy
        webif_dir = self.path_join(self.get_plugin_dir(), 'webif')
        config = {
            '/': {
                'tools.staticdir.root': webif_dir,
            },
            '/static': {
                'tools.staticdir.on': True,
                'tools.staticdir.dir': 'static'
            }
        }

        # Register the web interface as a cherrypy app
        self.mod_http.register_webif(WebInterface(webif_dir, self),
                                     self.get_shortname(),
                                     config,
                                     self.get_classname(), self.get_instance_name(),
                                     description='')

        return True


# ------------------------------------------
#    Webinterface of the plugin
# ------------------------------------------


class WebInterface(SmartPluginWebIf):

    def __init__(self, webif_dir, plugin):
        """
        Initialization of instance of class WebInterface

        :param webif_dir: directory where the webinterface of the plugin resides
        :param plugin: instance of the plugin
        :type webif_dir: str
        :type plugin: object
        """
        self.logger = logging.getLogger(__name__)
        self.webif_dir = webif_dir
        self.plugin = plugin
        self.tplenv = self.init_template_environment()

        self.items = Items.get_instance()

    @cherrypy.expose
    def index(self, reload=None):
        """
        Build index.html for cherrypy

        Render the template and return the html file to be delivered to the browser

        :return: contents of the template after beeing rendered
        """
        tmpl = self.tplenv.get_template('index.html')
        # add values to be passed to the Jinja2 template eg: tmpl.render(p=self.plugin, interface=interface, ...)
        return tmpl.render(p=self.plugin, items=sorted(self.items.return_items(), key=lambda k: str.lower(k['_path'])))

    @cherrypy.expose
    def get_data_html(self, dataSet=None):
        """
        Return data to update the webpage

        For the standard update mechanism of the web interface, the dataSet to return the data for is None

        :param dataSet: Dataset for which the data should be returned (standard: None)
        :return: dict with the data needed to update the web page.
        """
        if dataSet is not None:
            # get the new data
            # data = {}

            # data['item'] = {}
            # for i in self.plugin.items:
            #     data['item'][i]['value'] = self.plugin.getitemvalue(i)
            #
            # return it as json the the web page
            # try:
            #     return json.dumps(data)
            # except Exception as e:
            #     self.logger.error("get_data_html exception: {}".format(e))
            pass

        return {}
