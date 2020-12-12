# Viessmann

#### Version 1.1.0

The Viessmann plugin is designed to connect to a Viessmann heating systems via the Optolink USB adapter to read out and write its parameters.
Currently the P300 and KW protocol are supported. Other devices can easily be added, other protocols might need some code additions.
All details of devices and protocols can be read here: https://github.com/openv/openv/wiki/vcontrold

The Viessmann plugin uses a separate commands.py file which contains the definitions for protocols, devices and control sets (control characters like start sequence, acknowledge etc.). Adding devices can be accomplished by adding the device command data to the commands.py file.

You can configure the plugin to connect by direct serial connection on the host system.

## Change history

### 1.1.0 

* Added KW protocol support.

### 1.0.0 

* Initial Release

## Requirements

This plugin needs pyserial and an Optolink adapter (Viessmann original or DIY).

### Supported Hardware

Any Viessmann heating system with an Optolink interface is supported. 

Currently, the command configuration includes the following devices:

* V200KO1B
* V200HO1C
* V200KW2
* V200WO1C

Additional devices can be added if the command configuration is known.

## Configuration

### plugin.yaml

```yaml
viessmann:
    protocol: P300
    plugin_name: viessmann
    heating_type: V200KO1B
    serialport: /dev/ttyUSB_optolink
```


### items.yaml

The plugin is completely flexible concerning which commands you want to use and when they should be read from the device.
Everything is configured by adding new items in a SmartHomeNG item configuration file.

The following item attributes are supported:

#### viess_read

The item value should be read by using the configured command.

```yaml
viess_read: Raumtemperatur_Soll_Normalbetrieb_A1M1
```

#### viess_send

Changes to this item result in sending the configured value to the heating system.
The command is complemented by the item value in a pre-configured way (see commands.py).
In case items are also configured with viess_read, you can just use "True" instead of the command

The item only has a send command:
```yaml
viess_send: Raumtemperatur_Soll_Normalbetrieb_A1M1
```
The item has a read and send command:
```yaml
viess_send: True
```

#### viess_read_afterwrite

A timespan (seconds) can be configured. If a value for this attribute is set, the plugin will wait the configured delay after the write command and then issue the configured read command to update the item value.
This attribute has no default value. If the attribute is not set, no read will be issued after write.

```yaml
viess_read_afterwrite: 1  # seconds
```

#### viess_read_cycle

With this attribute a cyclic read operation for this item can be configured (timespan between cycles in seconds).

```yaml
viess_read_cycle: 3600  # every hour
```

#### viess_init

If this attribute is set to True, the plugin will issue a read command at startup to get an initial value from the device.

```yaml
viess_init: true
```

#### viess_trigger

This attribute can contain a list of read commands which will be issued if the item is updated.
Useful for instance: If the ventilation level is changed, get updated fan RPM values.

```yaml
viess_trigger:
   - Betriebsart_A1M1
   - Sparbetrieb_A1M1
```

#### viess_trigger_afterwrite

If a viess_trigger is configured for this item, this item sets the delay time before starting to issue the triggered read commands.
Default value: 5 seconds.

```yaml
viess_trigger_afterwrite: 10 # seconds
```

#### Example

Here you can find a configuration sample using the commands for V200KO1B:

```yaml
viessmann:
    viessmann_update:
        name: Update aller Items mit 'viess_read'
        type: bool
        visu_acl: rw
        viess_update: 1
        autotimer: 1 = 0

    allgemein:
        aussentemp:
            name: Aussentemperatur
            type: num
            viess_read: Aussentemperatur
            viess_read_cycle: 300
            viess_init: true
            database: true
        aussentemp_gedaempft:
            name: Aussentemperatur
            type: num
            viess_read: Aussentemperatur_TP
            viess_read_cycle: 300
            viess_init: true
            database: true
 
    kessel:
        kesseltemperatur_ist:
            name: Kesseltemperatur_Ist
            type: num
            viess_read: Kesseltemperatur
            viess_read_cycle: 180
            viess_init: true
            database: init
        kesseltemperatur_soll:
            name: Kesselsolltemperatur_Soll
            type: num
            viess_read: Kesselsolltemperatur
            viess_read_cycle: 180
            viess_init: true
        abgastemperatur:
            name: Abgastemperatur
            type: num
            viess_read: Abgastemperatur
            viess_read_cycle: 180
            viess_init: true
            database: init        
    heizkreis_a1m1:
       betriebsart:
            betriebsart_aktuell:
                name: Aktuelle_Betriebsart_A1M1
                type: str
                viess_read: Aktuelle_Betriebsart_A1M1
                viess_read_cycle: 3600
                viess_init: true
            betriebsart:
                name: Betriebsart_A1M1
                type: num
                viess_read: Betriebsart_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                cache: true
                enforce_updates: true
                viess_trigger:
                  - Aktuelle_Betriebsart_A1M1
                struct: viessmann.betriebsart
                visu_acl: rw
            sparbetrieb:
                name: Sparbetrieb_A1M1
                type: bool
                viess_read: Sparbetrieb_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_trigger: 
                  - Betriebsart_A1M1
                  - Aktuelle_Betriebsart_A1M1
                viess_init: true
                visu_acl: rw
       schaltzeiten:
            montag:
                name: Timer_A1M1_Mo
                type: list
                viess_read: Timer_A1M1_Mo
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
                visu_acl: rw
            dienstag:
                name: Timer_A1M1_Di
                type: list
                viess_read: Timer_A1M1_Di
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
                visu_acl: rw
       ferienprogramm:
            status:
                name: Ferienprogramm_A1M1
                type: num
                viess_read: Ferienprogramm_A1M1
                viess_read_cycle: 3600
                viess_init: true
            starttag:
                name: Ferien_Abreisetag_A1M1
                type: str
                viess_read: Ferien_Abreisetag_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                visu_acl: rw
                eval: value[:10]
            endtag:
                name: Ferien_Rückreisetag_A1M1
                type: str
                viess_read: Ferien_Rückreisetag_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                visu_acl: rw
```

### logic.yaml

Currently there is no logic configuration for this plugin.

## Methods

### update_all_read_items()

The function update_all_read_items() can be used to trigger read operations on all configured items.
