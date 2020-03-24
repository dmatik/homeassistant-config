# Switcher integration using WebAPI

## What
This is alternative option for integration of Switcher water heater in Home Assistant.  
There are two existing components, both developed by [tomerfi](https://hub.docker.com/u/tomerfi) for that: 
* "switcher_aio" - Very old custom component and has issues with newer versions of HA.
* "switcher_kis" - Newer component, already part of official HA releases. However it has very limited functionality. Also some people report they are getting timeouts while trying to load it during HA startup.  

In this solution we will be using **Switcher water heater WebAPI**, running in docker, developed also by [tomerfi](https://hub.docker.com/u/tomerfi).

## Prerequisites
* Install and configure your Switcher device.
* Collect the following information from the device’s following NightRang3r instructions in the [Switcher-V2-Python repository](https://github.com/NightRang3r/Switcher-V2-Python):
  * ip_address
  * phone_id
  * device_id
  * device_pass
* Install docker

## How
### WebAPI container
Setup Switcher water heater WebAPI container in docker using its the [documentation](https://aioswitcher.readthedocs.io/projects/switcher_webapi/en/stable/).  
This is example of working Docker Compose (change to your values):

    version: '2'
    services:
        switcher_webapi:
            image: tomerfi/switcher_webapi:latest
            container_name: switcher_webapi
            hostname: switcher_webapi
            restart: always
            network_mode: bridge
            ports:
              - 8000:8000
            environment:
                CONF_DEVICE_IP_ADDR: <<your Switcher IP address>>
                CONF_PHONE_ID: <<your phone ID>>
                CONF_DEVICE_ID: <<your device ID>>
                CONF_DEVICE_PASSWORD: <<your device password>>
                CONF_THROTTLE: 1.0


### RESTful commands
Define RESTful commands in HA, to be used in scripts.  
**_Change to your IP and port below._**

    rest_command:

      switcher_turn_on:
        url: http://192.168.1.1:8000/switcher/turn_on
        method: "POST"
        payload: '{"minutes": "{{ minutes }}"}'

      switcher_turn_off:
        url: http://192.168.1.1:8000/switcher/turn_off
        method: "POST"

### Sensors
Define RESTful Sensor and other Template sensors depending on it in HA.  
**_Change to your IP and port below._**



### Input Select
Define Input Select in HA, to select the timings for the Turn On with timer script.

    input_select:
      switcher_timer_minutes_input_select:
          name: Timer minutes
          options:
              - 15
              - 30
              - 45
              - 60

### Scripts
Define scripts in HA for turning on the Switcher, with and without timers, and turning it off.

    script:

      switcher_turn_on_timer_script:
          alias: On with Timer
          sequence:
              - service: rest_command.switcher_turn_on
                data_template:
                  minutes: '{{ states("input_select.switcher_timer_minutes_input_select") }}'
              - service: homeassistant.update_entity
                entity_id: sensor.switcher_webapi

      switcher_turn_on:
          alias: Turn On
          sequence:
              - service: rest_command.switcher_turn_on
              - service: homeassistant.update_entity
                entity_id: sensor.switcher_webapi

      switcher_turn_off:
          alias: Turn Off
          sequence:
              - service: rest_command.switcher_turn_off
              - service: homeassistant.update_entity
                entity_id: sensor.switcher_webapi

### Switch
Define Switch in HA, which uses the sensor and scripts we defined before.

    switch:
      - platform: template
        switches:

          switcher_webapi:
              friendly_name: Boiler
              icon_template: mdi:shower
              entity_id: sensor.switcher_webapi
              value_template: "{{ is_state_attr('sensor.switcher_webapi', 'state', 'on') }}"
              turn_on:
                  service: script.turn_on
                  data:
                    entity_id: script.switcher_turn_on
              turn_off:
                  service: script.turn_on
                  data:
                    entity_id: script.switcher_turn_off

## UI
This is it. All that is left to define a nice UI and use all the above entities.
But this is for another guide.
