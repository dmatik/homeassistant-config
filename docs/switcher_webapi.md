# What
This is alternative option for integration of Switcher water heater in Home Assistant.  
There are two existing components, both developed by [tomerfi](https://hub.docker.com/u/tomerfi) for that: 
* "switcher_aio" - Very old custom component and has issues with newer versions of HA.
* "switcher_kis" - Newer component, already part of official HA releases. However it has very limited functionality. Also some people report they are getting timeouts while trying to load it during HA startup.  

In this solution we will be using **Switcher water heater WebAPI**, running in docker, developed also by [tomerfi](https://hub.docker.com/u/tomerfi).

# Prerequisites
* Install and configure your Switcher device.
* Collect the following information from the device’s following NightRang3r instructions in the [Switcher-V2-Python repository](https://github.com/NightRang3r/Switcher-V2-Python):
  * ip_address
  * phone_id
  * device_id
  * device_pass
* Install docker

# How
## WebAPI container
Setup Switcher water heater WebAPI container in docker using its the [documentation](https://aioswitcher.readthedocs.io/projects/switcher_webapi/en/stable/).

## RESTful commands
Define RESTful commands in HA, to be used in scripts.

    rest_command:

      switcher_turn_on:
        url: http://192.168.1.1:8000/switcher/turn_on
        method: "POST"
        payload: '{"minutes": "{{ minutes }}"}'

      switcher_turn_off:
        url: http://192.168.1.1:8000/switcher/turn_off
        method: "POST"

