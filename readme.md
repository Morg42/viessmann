# Viessmann

#### Version 1.0.0

The Viessmann plugin is designed to connect to a Viessmann heating systems via the Optolink USB adapter to read out and write its parameters.
Currently the P300 protocol and the V200KO1B,KO2B devices are supportet. Other protocols and devices can easily be added.
All details of devices and protocols can be read here: https://github.com/openv/openv/wiki/vcontrold

The Viessmann plugin uses a separate commands.py file which contains the different control- (control characters like start sequence, acknowledge etc.) and commandsets for the supported systems.

You can configure the plugin to connect by direct serial connection on the host system.

## Change history

Initial Release

## Requirements

This plugin has no requirements or dependencies.

### Needed software

None

### Supported Hardware

* Optolink adapter (Viessmann original or DIY)

## Configuration

### plugin.yaml

```
viessmann:
    protocol: P300
    plugin_name: viessmann
    heating_type: V200KO1B
    serialport: /dev/ttyUSB_optolink
```


### items.yaml

The plugin is completely flexible in which commands you use and when you want the read out which parameters.
Everything is configured by adding new items in a SmartHomeNG item configuration file.

The following item attributes are supported:

#### viess_send

Changes to this item result in sending the configured command to the heating system.
The command is complemented by the item value in a pre-configured way (see commands.py).
Typically read and write command are identical. In case a items and read and send command, 
you just can use "True" instead of the command

The item just has a send command:
```yaml
viess_send: Raumtemperatur_Soll_Normalbetrieb_A1M1
```
The item has a read and send command:
```yaml
viess_send: True
```

#### viess_read

The item value should be read by using the configured command.

```yaml
viess_read: Raumtemperatur_Soll_Normalbetrieb_A1M1
```

#### viess_read_afterwrite

A timespan (seconds) can be configured. If a value for this attribute is set, the plugin will wait the configured delay after the write command and then issue the configured read command to update the items value.
This attribute has no default value. If the attribute is not set, no read will be issued after write.

```yaml
viess_read_afterwrite: 1 # seconds
```

#### viess_read_cycle

With this attribute a read cycle for this item can be configured (timespan between cycles in seconds).

```yaml
viess_read_cycle: 3600 # every hour
```

#### viess_init

If this attribute is set to a bool value (e.g. 'true'), the plugin will use the read command at startup to get an initial value.

```yaml
viess_init: true
```

#### viess_trigger

This attribute can contain a list of commands, which will be issued if the item is updated.
Useful for instance: If the ventilation level is changed, get updated ventilator RPM values.

```yaml
viess_trigger:
   - Betriebsart_A1M1
   - Sparbetrieb_A1M1
```

#### viess_trigger_afterwrite

A timespan (seconds) can be configured. After an update to this item, the commands configured in comfoair_trigger will be issued. Before triggering the here configured delay will be waited for.
Default value: 5 seconds.

```yaml
viess_trigger_afterwrite: 10 # seconds
```

#### Example

Here you can find a sample configuration using the commands for KO1B:

```yaml
viessmann:
    type: foo
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
        stoerungen:
            sammelstoerung:
                name: Sammelstoerung
                type: num
                viess_read: Sammelstoerung
                viess_read_cycle: 3600
                viess_init: true
                database: true
            error_1:
                name: Fehlerhistory Eintrag 1
                type: foo
                viess_read: Error0
                viess_read_cycle: 3600
                viess_init: true
            error_2:
                name: Fehlerhistory Eintrag 2
                type: foo
                viess_read: Error1
                viess_read_cycle: 3600
                viess_init: true
            error_3:
                name: Fehlerhistory Eintrag 3
                type: foo
                viess_read: Error2
                viess_read_cycle: 3600
                viess_init: true
            error_4:
                name: Fehlerhistory Eintrag 4
                type: foo
                viess_read: Error3
                viess_read_cycle: 3600
                viess_init: true
            error_5:
                name: Fehlerhistory Eintrag 5
                type: foo
                viess_read: Error4
                viess_read_cycle: 3600
                viess_init: true
            error_6:
                name: Fehlerhistory Eintrag 6
                type: foo
                viess_read: Error5
                viess_read_cycle: 3600
                viess_init: true
            error_7:
                name: Fehlerhistory Eintrag 7
                type: foo
                viess_read: Error6
                viess_read_cycle: 3600
                viess_init: true
            error_8:
                name: Fehlerhistory Eintrag 8
                type: foo
                viess_read: Error7
                viess_read_cycle: 3600
                viess_init: true
            error_9:
                name: Fehlerhistory Eintrag 9
                type: foo
                viess_read: Error8
                viess_read_cycle: 3600
                viess_init: true
            error_0:
                name: Fehlerhistory Eintrag 10
                type: foo
                viess_read: Error9
                viess_read_cycle: 3600
                viess_init: true
    brenner:
        starts:
            name: Brennerstarts
            type: num
            viess_read: Brennerstarts
            viess_send: true
            viess_read_afterwrite: 5
            viess_read_cycle: 300
            viess_init: true
            database: true
        betriebsstunden:
            name: Brenner_Betriebsstunden
            type: num
            viess_read: Brenner_Betriebsstunden
            viess_send: true
            viess_read_afterwrite: 5
            viess_read_cycle: 300
            viess_init: true
            database: true
        betrieb_2_starts:
            name: Betriebsstunden / Brennertstarts
            type: num
            eval: round(sh...betriebsstunden() / sh...starts(), 2)
            eval_trigger:
              - ..betriebsstunden
              - ..starts
            database: true
        brennerstatus_1:
            name: Brennerstatus_1
            type: bool
            viess_read: Brennerstatus_1
            viess_read_cycle: 120
            viess_init: true
        brennerstatus_2:
            name: Brennerstatus_2
            type: bool
            viess_read: Brennerstatus_2
            viess_read_cycle: 120
            viess_init: true
        oeldurchsatz:
            name: Oeldurchsatz_dl/h
            type: num
            viess_read: Oeldurchsatz
            viess_send: true
            viess_read_afterwrite: 5
            viess_init: true
        oelverbrauch:
            name: Oelverbrauch
            type: num
            viess_read: Oelverbrauch
            viess_send: true
            viess_read_afterwrite: 5
            viess_read_cycle: 3600
            viess_init: true
            database: true
            struct: wertehistorie_total
 
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
        zirkulationspumpe:
            name: Status_Zirkulationspumpe
            type: bool
            viess_read: Zirkulationspumpe
            viess_read_cycle: 300
            viess_init: true
        relais_k12:
            name: Status Relais_K12
            type: bool
            viess_read: Relais_K12
            viess_read_cycle: 3600
            viess_init: true
        temp_offset_m2:
            name: Offset KesselTemp uber WW_Solltemp in Grad C
            type: num
            viess_read: TempKOffset
            viess_send: true
            viess_read_afterwrite: 5
            viess_init: true
        systemtime:
            name: Systemzeit
            type: str
            viess_read: Systemtime
            viess_send: true
            viess_read_afterwrite: 5
            viess_read_cycle: 3600
            viess_init: true
        anlagenschema:
            name: Anlagenschema
            type: str
            viess_read: Anlagenschema
            viess_init: true
        seriennummer:
            name: Seriennummer
            type: str
            viess_read: Inventory
            viess_init: true
        geraetetyp:
            name: Geraetetyp
            type: str
            viess_read: DevType
            viess_init: true
    heizkreis_a1m1:
        status:
            vorlauftemperatur:
                name: Vorlauftemperatur_A1M1
                type: num
                viess_read: Vorlauftemperatur_A1M1
                viess_read_cycle: 300
                viess_init: true
            hk_pumpe:
                name: Heizkreispumpe_A1M1
                type: bool
                viess_read: Heizkreispumpe_A1M1
                viess_read_cycle: 120
                viess_init: true
                database: init
            relais_status_pumpe:
                name: Relais_Status_Pumpe_A1M1
                type: bool
                viess_read: Relais_Status_Pumpe_A1M1
                viess_read_cycle: 3600
                viess_init: true
        raumtemperatur:
            raumtemperatur:
                name: null
                type: num
                viess_read: Raumtemperatur_A1M1
                viess_read_cycle: 1800
                viess_init: true
            raumtemperatur_soll_normal:
                name: null
                type: num
                viess_read: Raumtemperatur_Soll_Normalbetrieb_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                visu_acl: rw
            raumtemperatur_soll_red:
                name: null
                type: num
                viess_read: Raumtemperatur_Soll_Red_Betrieb_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                visu_acl: rw
            raumtemperatur_soll_party:
                name: null
                type: num
                viess_read: Raumtemperatur_Soll_Party_Betrieb_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                visu_acl: rw
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
            sparbetrieb_aktuell:
                name: Zustand_Sparbetrieb_A1M1 (read only)
                type: bool
                viess_read: Zustand_Sparbetrieb_A1M1
                viess_read_cycle: 3600
                viess_init: true
            partybetrieb:
                name: Partybetrieb_A1M1
                type: bool
                viess_read: Partybetrieb_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_trigger: 
                  - Betriebsart_A1M1
                  - Aktuelle_Betriebsart_A1M1
                viess_init: true
                visu_acl: rw
            partybetrieb_aktuell:
                name: Zustand_Partybetrieb_A1M1 (read only)
                type: bool
                viess_read: Zustand_Partybetrieb_A1M1
                viess_read_cycle: 3600
                viess_init: true
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
            mittwoch:
                name: Timer_A1M1_Mi
                type: list
                viess_read: Timer_A1M1_Mi
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
                visu_acl: rw
            donnerstag:
                name: Timer_A1M1_Do
                type: list
                viess_read: Timer_A1M1_Do
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
                visu_acl: rw
            freitag:
                name: Timer_A1M1_Fr
                type: list
                viess_read: Timer_A1M1_Fr
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
                visu_acl: rw
            samstag:
                name: Timer_A1M1_Sa
                type: list
                viess_read: Timer_A1M1_Sa
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
                visu_acl: rw
            sonntag:
                name: Timer_A1M1_So
                type: list
                viess_read: Timer_A1M1_So
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
        konfiguration:
            hkl_niveau:
                name: Niveau_Heizkennlinie_A1M1
                type: num
                viess_read: Niveau_Heizkennlinie_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                visu_acl: rw
            hkl_neigung:
                name: Neigung_Heizkennlinie_A1M1
                type: num
                viess_read: Neigung_Heizkennlinie_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                visu_acl: rw
            speichervorrang:
                name: Speichervorrang
                type: num
                viess_read: Speichervorrang_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            frostschutzgrenze:
                name: Frostschutzgrenze
                type: num
                viess_read: Frostschutzgrenze_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            frostschutz:
                name: Frostschutz
                type: num
                viess_read: Frostschutz_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            heizkreispumpenlogik:
                name: Systemzeit
                type: num
                viess_read: Heizkreispumpenlogik_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            sommersparschaltung:
                name: AbsolutSommersparschaltung
                type: num
                viess_read: Sparschaltung_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            sparfunktion_mischer:
                name: Sparfunktion_Mischer
                type: num
                viess_read: Mischersparfunktion_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            pumpenstillstandzeit:
                name: Pumpenstillstandzeit
                type: num
                viess_read: Pumpenstillstandzeit_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                pumpenstillstandzeit_in_min:
                    type: num
                    eval: round(((sh.....raumtemperatur.raumtemperatur_soll_normal() - sh.....raumtemperatur.raumtemperatur_soll_red()) / (sh.....raumtemperatur.raumtemperatur_soll_red() - sh......allgemein.aussentemp_gedaempft())) * sh...() * 30, 0)
                    eval_trigger:
                      - ..
                      - .....allgemein.aussentemp_gedaempft
                      - ....raumtemperatur.raumtemperatur_soll_normal
                      - ....raumtemperatur.raumtemperatur_soll_red
            vorlauftemperatur_min:
                name: Vorlauftemperatur_min
                type: num
                viess_read: Vorlauftemperatur_min_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            vorlauftemperatur_max:
                name: Vorlauftemperatur_max
                type: num
                viess_read: Vorlauftemperatur_max_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            partybetrieb_Zeitbegrenzung:
                name: Partybetrieb_Zeitbegrenzung
                type: num
                viess_read: Partybetrieb_Zeitbegrenzung_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            temperaturgrenze_aufhebung_red_Betrieb_A1M1:
                name: Temperaturgrenze_red_Betrieb
                type: num
                viess_read: Temperaturgrenze_red_Betrieb_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            temperaturgrenze_anhebung_red_raumtemp:
                name: Temperaturgrenze_red_Raumtemp_A1M1
                type: num
                viess_read: Temperaturgrenze_red_Raumtemp_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            vorlauftemperatur_erhoehung_soll:
                name: Vorlauftemperatur_Erhoehung_Soll
                type: num
                viess_read: Vorlauftemperatur_Erhoehung_Soll_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
            vorlauftemperatur_erhoehung_zeit:
                name: Vorlauftemperatur_Erhoehung_Zeit
                type: num
                viess_read: Vorlauftemperatur_Erhoehung_Zeit_A1M1
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
    warmwasser:
        status:
            name: Satus_Warmwasserbereitung
            type: num
            viess_read: Satus_Warmwasserbereitung
            viess_read_cycle: 3600
            viess_init: true
        speicherladepumpe:
            type: bool
            viess_read: Speicherladepumpe
            viess_read_cycle: 120
            viess_init: true
        temperatur_soll:
            name: Warmwasser_Solltemperatur
            type: num
            visu_acl: rw
            viess_read: Warmwasser_Solltemperatur
            viess_send: true
            viess_read_afterwrite: 5
            viess_init: true
        temperatur_ist:
            name: Warmwasser_Temperatur
            type: num
            viess_read: Temp_Speicher_Ladesensor
            viess_read_cycle: 180
            viess_init: true
            database: init
        schaltzeiten:
            montag:
                name: Timer_Warmwasser_Mo
                type: list
                viess_read: Timer_Warmwasser_Mo
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
            dienstag:
                name: Timer_Warmwasser_Di
                type: list
                viess_read: Timer_Warmwasser_Di
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
            mittwoch:
                name: Timer_Warmwasser_Mi
                type: list
                viess_read: Timer_Warmwasser_Mi
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
            donnerstag:
                name: Timer_Warmwasser_Do
                type: list
                viess_read: Timer_Warmwasser_Do
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
            freitag:
                name: Timer_Warmwasser_Fr
                type: list
                viess_read: Timer_Warmwasser_Fr
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
            samstag:
                name: Timer_Warmwasser_Sa
                type: list
                viess_read: Timer_Warmwasser_Sa
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
            sonntag:
                name: Timer_Warmwasser_D0
                type: list
                viess_read: Timer_Warmwasser_So
                viess_send: true
                viess_read_afterwrite: 5
                viess_init: true
                struct: viessmann.timer
```


### logic.yaml
Currently there is no logic configuration for this plugin.


## Methods
Currently there are no functions offered from this plugin.


## Web Interfaces

For building a web interface for a plugin, we deliver the following 3rd party components with the HTTP module:

   * JQuery 3.4.1: 
     * JS: &lt;script src="/gstatic/js/jquery-3.4.1.min.js"&gt;&lt;/script&gt;
   * Bootstrap : 
     * CSS: &lt;link rel="stylesheet" href="/gstatic/bootstrap/css/bootstrap.min.css" type="text/css"/&gt; 
     * JS: &lt;script src="/gstatic/bootstrap/js/bootstrap.min.js"&gt;&lt;/script&gt;     
   * Bootstrap Tree View: 
      * CSS: &lt;link rel="stylesheet" href="/gstatic/bootstrap-treeview/bootstrap-treeview.css" type="text/css"/&gt; 
      * JS: &lt;script src="/gstatic/bootstrap-treeview/bootstrap-treeview.min.js"&gt;&lt;/script&gt;
   * Bootstrap Datepicker v1.8.0:
      * CSS: &lt;link rel="stylesheet" href="/gstatic/bootstrap-datepicker/dist/css/bootstrap-datepicker.min.css" type="text/css"/&gt;
      * JS:
         * &lt;script src="/gstatic/bootstrap-datepicker/dist/js/bootstrap-datepicker.min.js"&gt;&lt;/script&gt;
         * &lt;script src="/gstatic/bootstrap-datepicker/dist/locales/bootstrap-datepicker.de.min.js"&gt;&lt;/script&gt;
   * popper.js: 
      * JS: &lt;script src="/gstatic/popper.js/popper.min.js"&gt;&lt;/script&gt;
   * CodeMirror 5.46.0: 
      * CSS: &lt;link rel="stylesheet" href="/gstatic/codemirror/lib/codemirror.css"/&gt;
      * JS: &lt;script src="/gstatic/codemirror/lib/codemirror.js"&gt;&lt;/script&gt;
   * Font Awesome 5.8.1:
      * CSS: &lt;link rel="stylesheet" href="/gstatic/fontawesome/css/all.css" type="text/css"/&gt;

 For addons, etc. that are delivered with the components, see /modules/http/webif/gstatic folder!
 
 If you are interested in new "global" components, contact us. Otherwise feel free to use them in your plugin, as long as
 the Open Source license is ok.
 
