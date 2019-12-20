"""////////////////////////////////////////////////////////////////////////////////////////////////
Home Assistant ALL IN ONE Custom Component for managing the Switcher version 2 device.
Build by TomerFi
Please visit https://github.com/TomerFi/home-assistant-custom-components for more custom components

Installation notes:
place this file and the services.xml file in the following folder and restart home assistant:
/config/custom_components/switcher_aio/

If an error occures, raise the log level to debug mode and analyze the logs, for example:
logger:
  default: error
  logs:
    custom_components.switcher_aio: debug

yaml configuration examples (configuration.yaml):

Mandatory Only Fields:
switcher_aio:
  phone_id: xxxx
  device_id: xxxxxx
  device_password: xxxxxxxx

Mandatory with Optional Fields:
switcher_aio:
  phone_id: xxxx
  device_id: xxxxxx
  device_password: xxxxxxxx
  create_view: true/false (default is true)
  create_groups: true/false (default is true)
  schedules_scan_interval:
    minutes: 5 (default is 5)

////////////////////////////////////////////////////////////////////////////////////////////////"""
import asyncio
import logging

import binascii as ba
import time
from struct import pack
import re
import socket
import datetime
import traceback
import threading

import voluptuous as vol

from homeassistant.core import callback
from homeassistant.const import (EVENT_HOMEASSISTANT_STOP, EVENT_CALL_SERVICE, EVENT_SERVICE_REGISTERED, STATE_ON, STATE_OFF, ATTR_SERVICE, 
    CONF_IP_ADDRESS, CONF_DEVICE, CONF_NAME, CONF_TYPE, SERVICE_TURN_ON, SERVICE_TURN_OFF, SERVICE_TOGGLE, CONF_ENTITY_ID, ATTR_HIDDEN , CONF_ICON)
from homeassistant.loader import bind_hass

from homeassistant.helpers.script import Script
import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.template as template_helper
from homeassistant.helpers.entity import Entity, async_generate_entity_id, ToggleEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.event import async_track_time_interval

from homeassistant.components.input_number import (MODE_SLIDER, ATTR_VALUE, ATTR_MIN, ATTR_MAX, ATTR_STEP, ATTR_MODE, SERVICE_SET_VALUE, DOMAIN as INPUT_NUMBER_DOMAIN)
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN, ATTR_CAN_CANCEL, ATTR_LAST_ACTION, ATTR_LAST_TRIGGERED
from homeassistant.components.input_select import DOMAIN as INPUT_SELECT_DOMAIN, ATTR_OPTIONS, SERVICE_SELECT_OPTION, SERVICE_SELECT_NEXT, SERVICE_SELECT_PREVIOUS
from homeassistant.components.input_text import DOMAIN as INPUT_TEXT_DOMAIN, MODE_TEXT, ATTR_VALUE, ATTR_MIN, ATTR_MAX, ATTR_PATTERN, ATTR_MODE
from homeassistant.components.group import DOMAIN as GROUP_DOMAIN, ENTITY_ID_FORMAT as GROUP_ENTITY_ID_FORMAT
from homeassistant.components.notify import DOMAIN as NOTIFY_DOMAIN


REQUIREMENTS = []
DEPENDENCIES = [GROUP_DOMAIN]
_LOGGER = logging.getLogger(__name__)

"""###############################
##### Home Assistant Naming ######
###############################"""
DOMAIN = "switcher_aio"
ENTITY_ID_FORMAT = DOMAIN + ".{}"

"""###############################
#### Configuration Constants #####
###############################"""
CONF_PHONE_ID = 'phone_id'
CONF_DEVICE_PASSWORD = 'device_password'
CONF_DEVICE_ID = 'device_id'
CONF_TIME_LEFT = "time_left"
CONF_AUTO_OFF = "auto_off"
CONF_CURRENT_POWER_CONSUMPTIOMN = "current_power_consumption"
CONF_ELECTRIC_CURRENT = "electric_current"
CONF_LAST_UPDATE = "last_update"
CONF_LAST_STATE_CHANGE = "last_state_change"
CONF_CREATE_VIEW = "create_view"
CONF_CREATE_GROUPS = "create_groups"
CONF_SCHEDULE_SCAN_INTERVAL = "schedules_scan_interval"
CONF_DEVICE_NAME = "device_name"
CONF_ENTITY = "entity"
CONF_STATE_CARD = "custom_ui_state_card"
CONF_CARD = "card"
CONF_DATA_TEMPLATE = "data_template"
CONF_SERVICE_TEMPLATE = "service_template"
CONF_ENABLED = "enabled"
ATTR_NOT_ENABLED = "Not enabled"
CONF_RECURRING = "recurring"
CONF_START_TIME = "start_time"
CONF_END_TIME = "end_time"
CONF_DURATION = "duration"
CONF_DAYS = "days"
CONF_CONFIGURED = "configured"
ATTR_NOT_CONFIGURED = "Not configured"
CONF_SCHEDULE_ID = "schedule_id"

"""###############################
######### Default Values #########
###############################"""
DEFAULT_CREATE_VIEW = True
DEFAULT_CREATE_GROUPS = True
DEFAULT_CONF_DAYS = []
DEFAULT_SCHEDULES_SCAN_INTERVAL = datetime.timedelta(minutes=5)

"""###############################
####### Weekdays Constants #######
###############################"""
SUNDAY = "Sunday"
MONDAY = "Monday"
TUESDAY = "Tuesday"
WEDNESDAY = "Wednesday"
THURSDAY = "Thursday"
FRIDAY = "Friday"
SATURDAY = "Saturday"
ALL_DAYS = "Every day"

WEEKDAY_TUP = (MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY)

"""###############################
##### Configuration Schemas ######
###############################"""
CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_PHONE_ID): cv.string,
        vol.Required(CONF_DEVICE_PASSWORD): cv.string,
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Optional(CONF_CREATE_VIEW, default=DEFAULT_CREATE_VIEW): cv.boolean,
        vol.Optional(CONF_CREATE_GROUPS, default=DEFAULT_CREATE_GROUPS): cv.boolean,
        vol.Optional(CONF_SCHEDULE_SCAN_INTERVAL, default=DEFAULT_SCHEDULES_SCAN_INTERVAL): vol.All(cv.time_period, cv.positive_timedelta)
        })
}, extra=vol.ALLOW_EXTRA)

TURN_ONOFF_SERVICE_SCHEMA = vol.Schema({
    vol.Required(CONF_ENTITY_ID): cv.entity_ids,
})

SET_AUTO_OFF_SERVICE_SCHEMA = vol.Schema({
    vol.Required(CONF_AUTO_OFF): cv.time_period_str
})

UPDATE_DEVICE_NAME_SERVICE_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string
})

MANAGE_SCHEDULE_SERVICE_SCHEMA = vol.Schema({
    vol.Required(CONF_SCHEDULE_ID): vol.All(cv.positive_int, vol.Range(min=0, max=7))
})

CREATE_RECURRING_SCHEDULE_SERVICE_SCHEMA = vol.All(vol.Schema({
    vol.Required(CONF_START_TIME): cv.time_period_str,
    vol.Required(CONF_END_TIME): cv.time_period_str,
    vol.Required(CONF_RECURRING): vol.All(cv.boolean, True),
    vol.Optional(CONF_DAYS, default=DEFAULT_CONF_DAYS): vol.All(
        cv.ensure_list_csv, [vol.In([MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY])]
        )
    })
)

CREATE_NON_RECURRING_SCHEDULE_SERVICE_SCHEMA = vol.All(vol.Schema({
    vol.Required(CONF_START_TIME): cv.time_period_str,
    vol.Required(CONF_END_TIME): cv.time_period_str,
    vol.Required(CONF_RECURRING): vol.All(cv.boolean, False),
    vol.Optional(CONF_DAYS, default=DEFAULT_CONF_DAYS): vol.Any(cv.match_all, None)
    })
)

CREATE_SCHEDULE_SERVICE_SCHEMA = vol.Any(
    CREATE_RECURRING_SCHEDULE_SERVICE_SCHEMA,
    CREATE_NON_RECURRING_SCHEDULE_SERVICE_SCHEMA
)

"""###############################
######### Custom Events ##########
###############################"""
EVENT_SWITCHER_DISCOVERY_DATA = "switcher_discovery_data"

"""###############################
######### Service Names ##########
###############################"""
SERVICE_TURN_ON_15 = "turn_on_15_minutes"
SERVICE_TURN_ON_30 = "turn_on_30_minutes"
SERVICE_TURN_ON_45 = "turn_on_45_minutes"
SERVICE_TURN_ON_60 = "turn_on_60_minutes"
SERVICE_SET_AUTO_OFF = "set_auto_off"
SERVICE_UPDATE_DEVICE_NAME = "update_device_name"
SERVICE_DELETE_SCHEDULE = "delete_schedule"
SERVICE_ENABLE_SCHEDULE = "enable_schedule"
SERVICE_DISABLE_SCHEDULE = "disable_schedule"
SERVICE_CREATE_SCHEDULE = "create_schedule"

"""###############################
######## Entities Config #########
###############################"""
ENTITY_CONTROL_TYPE = "type_control"
ENTITY_CONTROL_CONFIG = {
    CONF_TYPE: ENTITY_CONTROL_TYPE,
    CONF_CARD: "state-card-toggle",
    CONF_ICON: "mdi:thermostat-box"
}

ENTITY_TIME_LEFT_TYPE = "type_time_left"
ENTITY_TIME_LEFT_CONFIG = {
    CONF_TYPE: ENTITY_TIME_LEFT_TYPE,
    CONF_CARD: "state-card-display",
    CONF_ICON: "mdi:timelapse"
}

ENTITY_AUTO_OFF_TYPE = "type_auto_off"
ENTITY_AUTO_OFF_CONFIG = {
    CONF_TYPE: ENTITY_AUTO_OFF_TYPE,
    CONF_CARD: "state-card-display",
    CONF_ICON: "mdi:timer"
}

ENTITY_ELECTRIC_CURRENT_TYPE = "type_electric_current"
ENTITY_ELECTRIC_CURRENT_CONFIG = {
    CONF_TYPE: ENTITY_ELECTRIC_CURRENT_TYPE,
    CONF_CARD: "state-card-display",
    CONF_ICON: "mdi:flash-circle"
}

ENTITY_DEVICE_NAME_TYPE = "type_device_name"
ENTITY_DEVICE_NAME_CONFIG = {
    CONF_TYPE: ENTITY_DEVICE_NAME_TYPE,
    CONF_CARD: "state-card-display",
    CONF_ICON: "mdi:settings-box"
}

HOURS_SLIDER_UNIT = "Hours"
ENTITY_HOURS_SLIDER_TYPE = "type_hours_slider"
ENTITY_HOURS_SLIDER_CONFIG = {
    CONF_TYPE: ENTITY_HOURS_SLIDER_TYPE,
    CONF_CARD: "state-card-input_number",
    CONF_ICON: "mdi:ray-vertex"
}

MINUTES_SLIDER_UNIT = "Minutes"
ENTITY_MINUTES_SLIDER_TYPE = "type_minutes_slider"
ENTITY_MINUTES_SLIDER_CONFIG = {
    CONF_TYPE: ENTITY_MINUTES_SLIDER_TYPE,
    CONF_CARD: "state-card-input_number",
    CONF_ICON: "mdi:ray-vertex"
}

ENTITY_AUTO_OFF_SCRIPT_TYPE = "type_send_auto_off_config"
ENTITY_AUTO_OFF_SCRIPT_CONFIG = {
    CONF_TYPE: ENTITY_AUTO_OFF_SCRIPT_TYPE,
    CONF_CARD: "state-card-script",
    CONF_ICON: "mdi:launch"
}

TURN_ON_TIMER_SELECT_OPTIONS = ["15", "30", "45", "60"]
ENTITY_TURN_ON_TIMER_SELECT_TYPE = "type_turn_on_timer_select"
ENTITY_TURN_ON_TIMER_SELECT_CONFIG = {
    CONF_TYPE: ENTITY_TURN_ON_TIMER_SELECT_TYPE,
    CONF_CARD: "state-card-input_select",
    CONF_ICON: "mdi:format-list-bulleted"
}

ENTITY_TURN_ON_TIMER_SCRIPT_TYPE = "type_turn_on_with_timer"
ENTITY_TURN_ON_TIMER_SCRIPT_CONFIG = {
    CONF_TYPE: ENTITY_TURN_ON_TIMER_SCRIPT_TYPE,
    CONF_CARD: "state-card-script",
    CONF_ICON: "mdi:launch"
}

ENTITY_SET_NAME_OF_DEVICE_TEXT_TYPE = "type_update_device_name_text"
ENTITY_SET_NAME_OF_DEVICE_TEXT_CONFIG = {
    CONF_TYPE: ENTITY_SET_NAME_OF_DEVICE_TEXT_TYPE,
    CONF_CARD: "state-card-input_text",
    CONF_ICON: "mdi:textbox"
}

ENTITY_UPDATE_DEVICE_NAME_SCRIPT_TYPE = "type_update_device_name_config"
ENTITY_UPDATE_DEVICE_NAME_SCRIPT_CONFIG = {
    CONF_TYPE: ENTITY_UPDATE_DEVICE_NAME_SCRIPT_TYPE,
    CONF_CARD: "state-card-script",
    CONF_ICON: "mdi:launch"
}

NOTIFICATION_SELECT_NONE = "None"
NOTIFICATION_SELECT_OPTIONS = [NOTIFICATION_SELECT_NONE]
ENTITY_NOTIFICATION_SELECT_TYPE = "type_notification_select"
ENTITY_NOTIFICATION_SELECT_CONFIG = {
    CONF_TYPE: ENTITY_NOTIFICATION_SELECT_TYPE,
    CONF_CARD: "state-card-input_select",
    CONF_ICON: "mdi:format-list-bulleted"
}

ENTITY_SCHEDULE_SENSOR_TYPE = "type_schedule"
ENTITY_SCHEDULE_SENSOR_CONFIG = {
    CONF_TYPE: ENTITY_SCHEDULE_SENSOR_TYPE,
    CONF_CARD: "state-card-display",
    CONF_ICON: "mdi:clock"
}

SCHEDULE_SELECT_OPTIONS = ["0", "1", "2", "3", "4", "5", "6", "7"]
ENTITY_SCHEDULE_SELECT_TYPE = "type_schedule_select"
ENTITY_SCHEDULE_SELECT_CONFIG = {
    CONF_TYPE: ENTITY_SCHEDULE_SELECT_TYPE,
    CONF_CARD: "state-card-input_select",
    CONF_ICON: "mdi:format-list-bulleted"
}

SCHEDULE_SELECT_ACTION_NONE = "please select an action"
SCHEDULE_SELECT_ACTION_ENABLE = "Enable"
SCHEDULE_SELECT_ACTION_DISABLE = "Disable"
SCHEDULE_SELECT_ACTION_DELETE = "Delete"
SCHEDULE_SELECT_ACTION_OPTIONS = [SCHEDULE_SELECT_ACTION_NONE, SCHEDULE_SELECT_ACTION_ENABLE, SCHEDULE_SELECT_ACTION_DISABLE, SCHEDULE_SELECT_ACTION_DELETE]
ENTITY_SCHEDULE_ACTION_SELECT_TYPE = "type_schedule_action_select"
ENTITY_SCHEDULE_ACTION_SELECT_CONFIG = {
    CONF_TYPE: ENTITY_SCHEDULE_ACTION_SELECT_TYPE,
    CONF_CARD: "state-card-input_select",
    CONF_ICON: "mdi:format-list-bulleted"
}

ENTITY_PERFORM_SCHEDULE_ACTION_SCRIPT_TYPE = "type_perform_schedule_action"
ENTITY_PERFORM_SCHEDULE_ACTION_SCRIPT_CONFIG = {
    CONF_TYPE: ENTITY_PERFORM_SCHEDULE_ACTION_SCRIPT_TYPE,
    CONF_CARD: "state-card-script",
    CONF_ICON: "mdi:launch"
}

ENTITY_SCHEDULE_DAYS_CONTROL_TYPE = "type_select_schedule_day"
ENTITY_SCHEDULE_DAYS_CONTROL_CONFIG = {
    CONF_TYPE: ENTITY_SCHEDULE_DAYS_CONTROL_TYPE,
    CONF_CARD: "state-card-toggle",
    CONF_ICON: "mdi:calendar-check"
}

ENTITY_SCHEDULE_START_TIME_TEXT_TYPE = "type_schedule_start_time_text"
ENTITY_SCHEDULE_START_TIME_TEXT_CONFIG = {
    CONF_TYPE: ENTITY_SCHEDULE_START_TIME_TEXT_TYPE,
    CONF_CARD: "state-card-input_text",
    CONF_ICON: "mdi:textbox"
}

ENTITY_SCHEDULE_END_TIME_TEXT_TYPE = "type_schedule_end_time_text"
ENTITY_SCHEDULE_END_TIME_TEXT_CONFIG = {
    CONF_TYPE: ENTITY_SCHEDULE_END_TIME_TEXT_TYPE,
    CONF_CARD: "state-card-input_text",
    CONF_ICON: "mdi:textbox"
}

ENTITY_CREATE_SCHEDULE_SCRIPT_TYPE = "type_perform_schedule_action"
ENTITY_CREATE_SCHEDULE_SCRIPT_CONFIG = {
    CONF_TYPE: ENTITY_CREATE_SCHEDULE_SCRIPT_TYPE,
    CONF_CARD: "state-card-script",
    CONF_ICON: "mdi:launch"
}

"""###############################
######### Entities Names ########
###############################"""
VIEW_NAME = "Switcher-V2"
VIEW_ENTITY = "switcher_aio_V2_view"

GROUP_CONTROL_NAME = "Switcher-V2 Control"
GROUP_CONTROL_ENTITY = "switcher_aio_V2_control"

GROUP_CONFIG_NAME = "Switcher-V2 Configuration"
GROUP_CONFIG_ENTITY = "switcher_aio_V2_configuration"

GROUP_SCHEDULES_NAME = "Switcher-V2 Schedules"
GROUP_SCHEDULES_ENTITY = "switcher_aio_V2_schedules"

GROUP_CREATE_SCHEDULE_NAME = "Switcher-V2 Create Schedule"
GROUP_CREATE_SCHEDULE_ENTITY = "switcher_aio_V2_create_schedule"

AUTO_OFF_HOURS_SLIDER_NAME = "Set Auto-Off Hours"
AUTO_OFF_HOURS_SLIDER_SLUG_ID = "set_auto_off_hours_slider"

AUTO_OFF_MINUTES_SLIDER_NAME = "Set Auto-Off Minutes"
AUTO_OFF_MINUTES_SLIDER_SLUG_ID = "set_auto_off_minutes_slider"

DEVICE_NAME_SENSOR_NAME = "Device Name"
DEVICE_NAME_SENSOR_SLUG_ID = "device_name_sensor"

TIME_LEFT_SENSOR_NAME = "Time Left"
TIME_LEFT_SENSOR_SLUG_ID = "time_left_sensor"

ELECTRIC_CURRENT_SENSOR_NAME = "Electric Current"
ELECTRIC_CURRENT_SENSOR_SLUG_ID = "electric_current_sensor"

AUTO_OFF_SENSOR_NAME = "Auto Off"
AUTO_OFF_SENSOR_SLUG_ID = "auto_off_sensor"

CONTROL_SWITCH_NAME = "Control Device"
CONTROL_SWITCH_SLUG_ID = "control_device_switch"

AUTO_OFF_SCRIPT_NAME = "Send Auto-Off to device"
AUTO_OFF_SCRIPT_SLUG_ID = "send_auto_off_script"

TURN_ON_TIMER_SELECT_NAME = "Timer minutes"
TURN_ON_TIMER_SELECT_SLUG_ID = "timer_minutes_input_select"

TURN_ON_TIMER_SCRIPT_NAME = "Send Turn On with timer"
TURN_ON_TIMER_SCRIPT_SLUG_ID = "turn_on_timer_script"

SET_NAME_OF_DEVICE_TEXT_NAME = "Update name of device"
SET_NAME_OF_DEVICE_TEXT_SLUG_ID = "name_of_device_input_text"

UPDATE_DEVICE_NAME_SCRIPT_NAME = "Send device name update"
UPDATE_DEVICE_NAME_SCRIPT_SLUG_ID = "update_device_name_script"

NOTIFICATION_SELECT_NAME = "Notification Service"
NOTIFICATION_SELECT_SLUG_ID = "notification_service_input_select"

SCHEDULE_SENSOR_NAME = "Schedule ID {}"
SCHEDULE_SENSOR_SLUG_ID = "schedule_id{}_sensor"

SCHEDULE_SELECT_NAME = "Schedule for action"
SCHEDULE_SELECT_SLUG_ID = "schedule_for_action_input_select"

SCHEDULE_ACTION_SELECT_NAME = "Action to perform"
SCHEDULE_ACTION_SELECT_SLUG_ID = "action_to_perform_input_select"

PERFORM_SCHEDULE_ACTION_SCRIPT_NAME = "Perform schedule action"
PERFORM_SCHEDULE_ACTION_SCRIPT_SLUG_ID = "perform_schedule_action_script"

SUNDAY_CONTROL_INPUT_BOOLEAN_NAME = "Select Sunday"
SUNDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID = "select_sunday_input_boolean"

MONDAY_CONTROL_INPUT_BOOLEAN_NAME = "Select Monday"
MONDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID = "select_monday_input_boolean"

TUESDAY_CONTROL_INPUT_BOOLEAN_NAME = "Select Tuesday"
TUESDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID = "select_tuesday_input_boolean"

WEDNESDAY_CONTROL_INPUT_BOOLEAN_NAME = "Select wednesday"
WEDNESDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID = "select_wednesday_input_boolean"

THURSDAY_CONTROL_INPUT_BOOLEAN_NAME = "Select Thursday"
THURSDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID = "select_thursday_input_boolean"

FRIDAY_CONTROL_INPUT_BOOLEAN_NAME = "Select Friday"
FRIDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID = "select_friday_input_boolean"

SATURDAY_CONTROL_INPUT_BOOLEAN_NAME = "Select Saturday"
SATURDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID = "select_saturday_input_boolean"

SET_SCHEDULE_START_TIME_TEXT_NAME = "Set start time in HH:mm"
SET_SCHEDULE_START_TIME_TEXT_SLUG_ID = "set_schedule_start_time_input_text"

SET_SCHEDULE_END_TIME_TEXT_NAME = "Set end time in HH:mm"
SET_SCHEDULE_END_TIME_TEXT_SLUG_ID = "set_end_start_time_input_text"

CREATE_SCHEDULE_SCRIPT_NAME = "Send create schedule"
CREATE_SCHEDULE_SCRIPT_SLUG_ID = "create_schedule_script"

"""###############################
###### Notification Dicts ########
###############################"""
TIMER_TURN_ON_NOTIFICATION_DATA = {
    "title": "SwitcherV2 Turned On",
    "message": "{} has been turned on, auto off is due in {}."
}

TIMER_TURN_OFF_NOTIFICATION_DATA = {
    "title": "SwitcherV2 Turned Off",
    "message": "{} has been turned off."
}

"""###############################
###### SwitcherV2 Constants ######
###############################"""
ENCODING_CODEC = "utf-8"
REMOTE_SESSION_ID = "00000000"
REMOTE_KEY = b"00000000000000000000000000000000"
SOCKET_PORT = 9957
SOCKET_BIND_TUP = ("0.0.0.0", 20002)
STATE_RESPONSE_ON = "0100"
STATE_RESPONSE_OFF = "0000"
COMMAND_ON = "1"
COMMAND_OFF = "0"
NO_TIMER_REQUESTED = "00000000"
ENABLE_SCHEDULE = "01"
DISABLE_SCHEDULE = "00"
DAYS_HEX_DICT = {0x02:MONDAY, 0x04:TUESDAY, 0x08:WEDNESDAY, 0x10:THURSDAY, 0x20:FRIDAY, 0x40:SATURDAY, 0x80:SUNDAY}
DAYS_INT_DICT = {MONDAY: 2, TUESDAY: 4, WEDNESDAY: 8, THURSDAY: 16, FRIDAY:32, SATURDAY:64, SUNDAY: 128}

"""###############################
######### Packet Formats #########
###############################"""
# remote session id, timestamp, phone id, device password
LOGIN_PACKET = "fef052000232a100{}340001000000000000000000{}00000000000000000000f0fe1c00{}0000{}00000000000000000000000000000000000000000000000000000000"
# local session id, timestamp, device id
GET_STATE_PACKET = "fef0300002320103{}340001000000000000000000{}00000000000000000000f0fe{}00"
# local session id, timestamp, device id, phone id, device password, command (1/0), timer
SEND_CONTROL_PACKET = "fef05d0002320102{}340001000000000000000000{}00000000000000000000f0fe{}00{}0000{}000000000000000000000000000000000000000000000000000000000106000{}00{}"
# local session id, timestamp, device id, phone id, device password, auto-off seconds
SET_AUTO_OFF_PACKET = "fef05b0002320102{}340001000000000000000000{}00000000000000000000f0fe{}00{}0000{}00000000000000000000000000000000000000000000000000000000040400{}"
# local session id, timestamp, device id, phone id, device password, name
UPDATE_DEVICE_NAME_PACKET = "fef0740002320202{}340001000000000000000000{}00000000000000000000f0fe{}00{}0000{}00000000000000000000000000000000000000000000000000000000{}"
# local session id, timestamp, device id, phone id, device password
GET_SCHEDULES_PACKET = "fef0570002320102{}340001000000000000000000{}00000000000000000000f0fe{}00{}0000{}00000000000000000000000000000000000000000000000000000000060000"
# local session id, timestamp, device id, phone id, device password, schedule id
DELETE_SCHEDULE_PACKET = "fef0580002320102{}340001000000000000000000{}00000000000000000000f0fe{}00{}0000{}000000000000000000000000000000000000000000000000000000000801000{}"
# local session id, timestamp, device id, phone id, device password, schedule data (time_id + on_off + week + timstate + start_time + end_time)
DISABLE_ENABLE_SCHEDULE_PACKET = "fef0630002320102{}340001000000000000000000{}00000000000000000000f0fe{}00{}0000{}00000000000000000000000000000000000000000000000000000000070c00{}"
# local session id, timestamp, device id, phone id, device password, schedule data (on_off + week + timstate + start_time + end_time)
CREATE_SCHEDULE_PACKET = "fef0630002320102{}340001000000000000000000{}00000000000000000000f0fe{}00{}0000{}00000000000000000000000000000000000000000000000000000000030c00ff{}"

"""###############################
#### Tools Parsers Converters ####
###############################"""


@callback
def convert_seconds_to_iso_time(all_seconds):
    """convert seconds to iso time (%H:%M:%S)"""
    try:
        minutes, seconds = divmod(int(all_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        return datetime.time(hour=hours, minute=minutes, second=seconds).isoformat()
    except Exception:
        _LOGGER.exception('failed to create iso time from ' + str(all_seconds) + ' seconds')
        raise


@callback
def crc_sign_full_packet_com_key(data):
    """CRC calculation"""
    try:
        crc = ba.hexlify(pack('>I', ba.crc_hqx(ba.unhexlify(data), 0x1021))).decode(ENCODING_CODEC)
        data = data + crc[6:8] + crc[4:6]
        crc = crc[6:8] + crc[4:6] + (ba.hexlify(REMOTE_KEY)).decode(ENCODING_CODEC)
        crc = ba.hexlify(pack('>I', ba.crc_hqx(ba.unhexlify(crc), 0x1021))).decode(ENCODING_CODEC)
        data = data + crc[6:8] + crc[4:6]
        return data
    except:
        _LOGGER.exception('failed to sign crc ' + traceback.format_exc())
        raise


@callback
def get_timestamp():
    """Generate timestamp"""
    try:
        return ba.hexlify(pack('<I', int(round(time.time())))).decode(ENCODING_CODEC)
    except Exception:
        _LOGGER.exception('failed to generate timestamp')
        raise


@callback
def get_socket(ip_addr):
    """Connect to socket"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((ip_addr, SOCKET_PORT))
        _LOGGER.debug('connected socket to ' + ip_addr)
        return sock
    except Exception:
        _LOGGER.exception('failed to connect socket to ' + ip_addr + traceback.format_exc())
        raise


@callback
def close_socket_connection(sock, ip_addr):
    """Close socket"""
    try:
        sock.close()
        _LOGGER.debug('closed socket connection to ' + ip_addr)
    except Exception:
        _LOGGER.exception('socket to '+ ip_addr + ' is not closable')
        pass


@callback
def convert_minutes_to_timer(minutes):
    """convert minutes to hex for timer"""
    try:
        return ba.hexlify(pack('<I', int(minutes) * 60)).decode(ENCODING_CODEC)
    except Exception:
        _LOGGER.exception('failed to create timer from ' + str(minutes) + ' minutes')
        raise


@callback
def convert_timedelta_to_auto_off(full_time):
    """convert timedelta seconds to hex for auto-off"""
    try:
        minutes = full_time.total_seconds() / 60
        hours, minutes = divmod(minutes, 60)
        seconds = int(hours) * 3600 + int(minutes) * 60
        if seconds > 3599 and seconds < 86341:
            return ba.hexlify(pack('<I', int(seconds))).decode(ENCODING_CODEC)
    except Exception:
        _LOGGER.exception('failed to create auto-off from' + str(full_time) + 'timedelta')
        raise


@callback
def convert_string_to_device_name(name):
    """convert string to device name"""
    try:
        return (ba.hexlify(name.encode(ENCODING_CODEC)) + ((32-len(name))*"00").encode(ENCODING_CODEC)).decode(ENCODING_CODEC)
    except Exception:
        _LOGGER.exception('failed to convert ' + name + ' to device name')
        raise


@callback
def get_days_list_from_bytes(data):
    """extract week days from shcedule bytes"""
    days_list = []
    try:
        for day in DAYS_HEX_DICT:
            if (day & data  != 0x00):
                days_list.append(DAYS_HEX_DICT[day])
        
        return days_list
    except Exception:
        _LOGGER.exception("failed to extract week days from schedule")
        raise


@callback
def get_time_from_bytes(data):
    """extract start/end time from shcedule bytes"""
    try:
        timeStamp = int(data[6:8] + data[4:6] + data[2:4] + data[0:2] , 16)
        return time.strftime("%H:%M", time.localtime(timeStamp))
    except Exception:
        _LOGGER.exception("failed to extract time from schedule")
        raise


@callback
def convert_timedelta_to_schedule_time(time_value):
    """convert timedelta to schedule start/end time"""
    try:
        return_time = time.mktime(time.strptime(time.strftime("%d/%m/%Y") + " " + str(time_value).split(":")[0] + ":" + str(time_value).split(":")[1], "%d/%m/%Y %H:%M"))  
        return ba.hexlify(pack('<I', int(return_time))).decode(ENCODING_CODEC)
    except Exception:
        _LOGGER.exception("failed to convert time value to schedule time")
        raise


"""############################
####### Packet Handlers #######
############################"""


@asyncio.coroutine
def async_send_login_packet(phone_id, device_password, sock, ts, retry=3):
    """Send login packet"""
    try:
        packet = crc_sign_full_packet_com_key(LOGIN_PACKET.format(REMOTE_SESSION_ID, ts, phone_id, device_password))
        sock.send(ba.unhexlify(packet))
        return SwitcherV2LoginResponseMSG(sock.recv(1024))
    except Exception:
        if retry > 0:
            _LOGGER.warning('failed to send login packet, retrying')
            return async_send_login_packet(phone_id, device_password, sock, ts, retry - 1)
        else:
            _LOGGER.error('failed to send login packet ' + traceback.format_exc())
            raise


@asyncio.coroutine
def async_send_get_state_packet(device_id, sock, ts, session_id):
    """Send get state packet"""
    try:
        packet = crc_sign_full_packet_com_key(GET_STATE_PACKET.format(session_id, ts, device_id))
        sock.send(ba.unhexlify(packet))
        return SwitcherV2StateResponseMSG(sock.recv(1024))
    except Exception:
        _LOGGER.error('failed to send state packet ' + traceback.format_exc())
        raise


@asyncio.coroutine
def async_send_control_packet(device_id, phone_id, device_password, sock, ts, session_id, cmd, timer=None):
    """Send control packet"""
    try:
        if timer is None:
            """No timer requested"""
            packet = crc_sign_full_packet_com_key(SEND_CONTROL_PACKET.format(session_id, ts, device_id, phone_id, device_password, cmd, NO_TIMER_REQUESTED))
        else:
            """Incorporate timer in packet"""
            _LOGGER.debug('incorporating timer for ' + timer + ' minutes')
            packet = crc_sign_full_packet_com_key(SEND_CONTROL_PACKET.format(session_id, ts, device_id, phone_id, device_password, cmd, convert_minutes_to_timer(timer)))

        sock.send(ba.unhexlify(packet))
        return SwitcherV2ControlResponseMSG(sock.recv(1024))
    except Exception:
        _LOGGER.error('failed to send control packet ' + traceback.format_exc())
        raise


@asyncio.coroutine
def async_send_set_auto_off_packet(device_id, phone_id, device_password, full_time, sock, ts, session_id):
    """Send set auto-off packet"""
    try:
        packet = crc_sign_full_packet_com_key(SET_AUTO_OFF_PACKET.format(session_id, ts, device_id, phone_id, device_password, convert_timedelta_to_auto_off(full_time)))
        sock.send(ba.unhexlify(packet))
        return SwitcherV2SetAutoOffResponseMSG(sock.recv(1024))
    except Exception:
        _LOGGER.error('failed to send set auto-off packet ' + traceback.format_exc())
        raise


@asyncio.coroutine
def async_send_update_name_packet(device_id, phone_id, device_password, name, sock, ts, session_id):
    """Send set auto-off packet"""
    try:
        packet = crc_sign_full_packet_com_key(UPDATE_DEVICE_NAME_PACKET.format(session_id, ts, device_id, phone_id, device_password, convert_string_to_device_name(name)))
        sock.send(ba.unhexlify(packet))
        return SwitcherV2UpdateNameResponseMSG(sock.recv(1024))
    except Exception:
        _LOGGER.error('failed to send update name packet ' + traceback.format_exc())
        raise


@asyncio.coroutine
def async_send_get_schedules_packet(device_id, phone_id, device_password, sock, ts, session_id):
    """Send get schedule packet"""
    try:
        packet = crc_sign_full_packet_com_key(GET_SCHEDULES_PACKET.format(session_id, ts, device_id, phone_id, device_password))
        sock.send(ba.unhexlify(packet))
        return SwitcherV2GetScheduleResponseMSG(sock.recv(1024))
    except Exception:
        _LOGGER.error('failed to send get schedules packet ' + traceback.format_exc())
        raise


@asyncio.coroutine
def async_send_disable_enable_schedule_packet(device_id, phone_id, device_password, sock, ts, session_id, schedule_data):
    """Send get schedule packet"""
    try:
        packet = crc_sign_full_packet_com_key(DISABLE_ENABLE_SCHEDULE_PACKET.format(session_id, ts, device_id, phone_id, device_password, schedule_data))
        sock.send(ba.unhexlify(packet))
        return SwitcherV2DisableEnableScheduleResponseMSG(sock.recv(1024))
    except Exception:
        _LOGGER.error('failed to send disable enable schedule packet ' + traceback.format_exc())
        raise


@asyncio.coroutine
def async_send_delete_schedule_packet(device_id, phone_id, device_password, sock, ts, session_id, schedule_id):
    """Send delete schedule packet"""
    try:
        packet = crc_sign_full_packet_com_key(DELETE_SCHEDULE_PACKET.format(session_id, ts, device_id, phone_id, device_password, schedule_id))
        sock.send(ba.unhexlify(packet))
        return SwitcherV2DeleteScheduleResponseMSG(sock.recv(1024))
    except Exception:
        _LOGGER.error('failed to send delete schedule packet ' + traceback.format_exc())
        raise


@asyncio.coroutine
def async_send_create_schedule_packet(device_id, phone_id, device_password, sock, ts, session_id, schedule_data):
    """Send create schedule packet"""
    try:
        packet = crc_sign_full_packet_com_key(CREATE_SCHEDULE_PACKET.format(session_id, ts, device_id, phone_id, device_password, schedule_data))
        sock.send(ba.unhexlify(packet))
        return SwitcherV2CreateScheduleResponseMSG(sock.recv(1024))
    except Exception:
        _LOGGER.error('failed to send create schedule packet ' + traceback.format_exc())
        raise


"""############################
###### Request Handlers #######
############################"""


@asyncio.coroutine
def async_send_command_to_device(ip_address, phone_id, device_id, device_password, cmd, timer=None):
    """Handles control requests"""
    sock = None
    try:
        sock = get_socket(ip_address)
        if not sock is None:
            ts = get_timestamp()
            _LOGGER.debug("sending login packet")
            response = yield from async_send_login_packet(phone_id, device_password, sock, ts)
            if response.successful:
                session_id = response.session_id
                _LOGGER.debug("login packet successful retreived session id " + session_id + ", sending state packet")
                response = yield from async_send_get_state_packet(device_id, sock, ts, session_id)
                if response.successful:
                    _LOGGER.debug("state packet successful, sending control packet")
                    response = yield from async_send_control_packet(device_id, phone_id, device_password, sock, ts, session_id, cmd, timer)
                    if response.successful:
                        _LOGGER.debug("control packet successful")

            return response.successful  
    except:
        _LOGGER.error('failed to control the device ' + traceback.format_exc())
    finally:
        if sock is not None:
            close_socket_connection(sock, ip_address)
    return False


@asyncio.coroutine
def async_set_auto_off_to_device(ip_address, phone_id, device_id, device_password, full_time):
    """Handles set auto-off requests"""
    sock = None
    try:
        sock = get_socket(ip_address)
        if not sock is None:
            ts = get_timestamp()
            _LOGGER.debug("sending login packet")
            response = yield from async_send_login_packet(phone_id, device_password, sock, ts)
            if response.successful:
                session_id = response.session_id
                _LOGGER.debug("login packet successful retreived session id: " + session_id + ", sending state packet")
                response = yield from async_send_get_state_packet(device_id, sock, ts, session_id)
                if response.successful:
                    _LOGGER.debug("state packet successful, sending auto-off config packet")
                    response = yield from async_send_set_auto_off_packet(device_id, phone_id, device_password, full_time, sock, ts, session_id)
                    if response.successful:
                        _LOGGER.debug("auto-off config packet successful")

            return response.successful
    except:
        _LOGGER.error('failed to set auto-off for the device ' + traceback.format_exc())
    finally:
        if sock is not None:
            close_socket_connection(sock, ip_address)
    return False


@asyncio.coroutine
def async_update_name_of_device(ip_address, phone_id, device_id, device_password, name):
    """Handles update device name requests"""
    sock = None
    try:
        sock = get_socket(ip_address)
        if not sock is None:
            ts = get_timestamp()
            _LOGGER.debug("sending login packet")
            response = yield from async_send_login_packet(phone_id, device_password, sock, ts)
            if response.successful:
                session_id = response.session_id
                _LOGGER.debug("login packet successful retreived session id: " + session_id + ", sending state packet")
                response = yield from async_send_get_state_packet(device_id, sock, ts, session_id)
                if response.successful:
                    _LOGGER.debug("state packet successful, sending name update packet")
                    response = yield from async_send_update_name_packet(device_id, phone_id, device_password, name, sock, ts, session_id)
                    if response.successful:
                        _LOGGER.debug("name update packet successful")

            return response.successful
    except:
        _LOGGER.error('failed to update the name of the device ' + traceback.format_exc())
    finally:
        if sock is not None:
            close_socket_connection(sock, ip_address)
    return False


@asyncio.coroutine
def async_get_schedules(ip_address, phone_id, device_id, device_password):
    """Handles get schedules requests"""
    sock = None
    try:
        sock = get_socket(ip_address)
        if not sock is None:
            ts = get_timestamp()
            _LOGGER.debug("sending login packet")
            response = yield from async_send_login_packet(phone_id, device_password, sock, ts)
            if response.successful:
                session_id = response.session_id
                _LOGGER.debug("login packet successful retreived session id: " + session_id + ", sending state packet")
                response = yield from async_send_get_state_packet(device_id, sock, ts, session_id)
                if response.successful:
                    _LOGGER.debug("state packet successful, sending get schedule packet")
                    response = yield from async_send_get_schedules_packet(device_id, phone_id, device_password, sock, ts, session_id)
                    if response.successful:
                        _LOGGER.debug("get schedule packet successful")

            return response.successful, response
    except:
        _LOGGER.error('failed to get schedules from the device ' + traceback.format_exc())
    finally:
        if sock is not None:
            close_socket_connection(sock, ip_address)
    return False, None


@asyncio.coroutine
def async_disable_enable_schedule(ip_address, phone_id, device_id, device_password, schedule_data):
    """Handles disable enable schedule requests"""
    sock = None
    try:
        sock = get_socket(ip_address)
        if not sock is None:
            ts = get_timestamp()
            _LOGGER.debug("sending login packet")
            response = yield from async_send_login_packet(phone_id, device_password, sock, ts)
            if response.successful:
                session_id = response.session_id
                _LOGGER.debug("login packet successful retreived session id: " + session_id + ", sending state packet")
                response = yield from async_send_get_state_packet(device_id, sock, ts, session_id)
                if response.successful:
                    _LOGGER.debug("state packet successful, sending disable enable schedule packet")
                    response = yield from async_send_disable_enable_schedule_packet(device_id, phone_id, device_password, sock, ts, session_id, schedule_data)
                    if response.successful:
                        _LOGGER.debug("disable enable schedule packet successful")

            return response.successful
    except:
        _LOGGER.error('failed to disable enable the schedule ' + traceback.format_exc())
    finally:
        if sock is not None:
            close_socket_connection(sock, ip_address)
    return False


@asyncio.coroutine
def async_delete_schedule(ip_address, phone_id, device_id, device_password, schedule_id):
    """Handles delete schedule requests"""
    sock = None
    try:
        sock = get_socket(ip_address)
        if not sock is None:
            ts = get_timestamp()
            _LOGGER.debug("sending login packet")
            response = yield from async_send_login_packet(phone_id, device_password, sock, ts)
            if response.successful:
                session_id = response.session_id
                _LOGGER.debug("login packet successful retreived session id: " + session_id + ", sending state packet")
                response = yield from async_send_get_state_packet(device_id, sock, ts, session_id)
                if response.successful:
                    _LOGGER.debug("state packet successful, sending delete schedule packet")
                    response = yield from async_send_delete_schedule_packet(device_id, phone_id, device_password, sock, ts, session_id, schedule_id)
                    if response.successful:
                        _LOGGER.debug("delete schedule packet successful")

            return response.successful
    except:
        _LOGGER.error('failed to delete the schedule ' + traceback.format_exc())
    finally:
        if sock is not None:
            close_socket_connection(sock, ip_address)
    return False


@asyncio.coroutine
def async_create_schedule(ip_address, phone_id, device_id, device_password, schedule_data):
    """Handles create schedule requests"""
    sock = None
    try:
        sock = get_socket(ip_address)
        if not sock is None:
            ts = get_timestamp()
            _LOGGER.debug("sending login packet")
            response = yield from async_send_login_packet(phone_id, device_password, sock, ts)
            if response.successful:
                session_id = response.session_id
                _LOGGER.debug("login packet successful retreived session id: " + session_id + ", sending state packet")
                response = yield from async_send_get_state_packet(device_id, sock, ts, session_id)
                if response.successful:
                    _LOGGER.debug("state packet successful, sending create schedule packet")
                    response = yield from async_send_create_schedule_packet(device_id, phone_id, device_password, sock, ts, session_id, schedule_data)
                    if response.successful:
                        _LOGGER.debug("create schedule packet successful, sending get schedule packet")
                        response = yield from async_send_get_schedules_packet(device_id, phone_id, device_password, sock, ts, session_id)
                        if response.successful:
                            _LOGGER.debug("get schedule packet successful")

            return response.successful, response
    except:
        _LOGGER.error('failed to create the schedule ' + traceback.format_exc())
    finally:
        if sock is not None:
            close_socket_connection(sock, ip_address)
    return False, None

"""###########################
###### Component Setup #######
###########################"""


@asyncio.coroutine
def async_setup(hass, config):
    """setup the component"""
    @asyncio.coroutine
    def discover_devices(event):
        """handle discovery response"""
        discoverd_device = event.data[CONF_DEVICE]
        _LOGGER.debug("discoverd switcher version 2 device at " + discoverd_device.ip)

        """Create calls and services functions"""
        @asyncio.coroutine
        def async_switcher_control(service):
            """Function to handle turn on, off and on with timer service calls"""
            _LOGGER.debug("received: " + service.service)
            if service.service in [SERVICE_TURN_ON, SERVICE_TURN_OFF]:
                if service.service == SERVICE_TURN_ON:
                    func_name = "async_turn_on"
                else:
                    func_name = "async_turn_off"
                for entity_id in service.data["entity_id"]:
                    for entity in [control_switch, select_schedule_sunday, select_schedule_monday, select_schedule_tuesday, select_schedule_wednesday, select_schedule_thursday, select_schedule_friday, select_schedule_saturday]:
                        if entity.entity_id == entity_id:
                            yield from hass.async_add_job(getattr(entity, func_name)())
            else:
                yield from hass.async_add_job(control_switch.async_turn_on_with_timer(''.join(list(filter(str.isdigit, service.service)))))
            
        @asyncio.coroutine
        def async_set_auto_off_service(service):
            """Function to handle set auto off service calls"""
            _LOGGER.debug("received: " + service.service + " value passed is: " + str(service.data[CONF_AUTO_OFF]))
            device = switcher_conn.get_device()
            yield from async_set_auto_off_to_device(device.ip, device.phone_id, device.device_id, device.device_password, service.data[CONF_AUTO_OFF])

        @asyncio.coroutine
        def async_update_device_name_service(service):
            """Function to handle update device name service calls"""
            _LOGGER.debug("received: " + service.service + " value passed is: " + service.data[CONF_NAME])
            device = switcher_conn.get_device()
            yield from async_update_name_of_device(device.ip, device.phone_id, device.device_id, device.device_password, service.data[CONF_NAME])

        @asyncio.coroutine
        def async_parse_retrieved_schedules(response):
            """Function to parse schedules response from get or create schedule requests"""
            if response.found_schedules:
                updated_schedules = []
                _LOGGER.debug("got schedules from device, updating entities")
                for schedule in response.get_schedules:
                    _LOGGER.debug("updating schedule id " + schedule.schedule_id)
                    if schedule.schedule_id == "0":
                        updated_schedules.append(schedule_id0_sensor)
                        yield from hass.async_add_job(schedule_id0_sensor.async_update_received(schedule))
                    elif schedule.schedule_id == "1":
                        updated_schedules.append(schedule_id1_sensor)
                        yield from hass.async_add_job(schedule_id1_sensor.async_update_received(schedule))
                    elif schedule.schedule_id == "2":
                        updated_schedules.append(schedule_id2_sensor)
                        yield from hass.async_add_job(schedule_id2_sensor.async_update_received(schedule))
                    elif schedule.schedule_id == "3":
                        updated_schedules.append(schedule_id3_sensor)
                        yield from hass.async_add_job(schedule_id3_sensor.async_update_received(schedule))
                    elif schedule.schedule_id == "4":
                        updated_schedules.append(schedule_id4_sensor)
                        yield from hass.async_add_job(schedule_id4_sensor.async_update_received(schedule))
                    elif schedule.schedule_id == "5":
                        updated_schedules.append(schedule_id5_sensor)
                        yield from hass.async_add_job(schedule_id5_sensor.async_update_received(schedule))
                    elif schedule.schedule_id == "6":
                        updated_schedules.append(schedule_id6_sensor)
                        yield from hass.async_add_job(schedule_id6_sensor.async_update_received(schedule))
                    elif schedule.schedule_id == "7":
                        updated_schedules.append(schedule_id7_sensor)
                        yield from hass.async_add_job(schedule_id7_sensor.async_update_received(schedule))

                for schedule_sens in schedule_sensor_list:
                    if schedule_sens not in updated_schedules:
                        yield from schedule_sens.async_deconfigure()
            else:
                _LOGGER.debug("no schedules set on device")

        @asyncio.coroutine
        def async_update_schedules_call(call=None):
            """Function to handle recursive schedules updates"""
            if call:
                _LOGGER.debug("received schedule update call: " + str(call))
            else:
                _LOGGER.debug("initiated intervaled updates of schedule")
            device = switcher_conn.get_device()
            successful, response = yield from async_get_schedules(device.ip, device.phone_id, device.device_id, device.device_password)
            if successful:
                yield from async_parse_retrieved_schedules(response)

        @asyncio.coroutine
        def async_manage_schedules_service(service):
            """Function to handle schedule managment (enable, disable, delete)"""
            schedule_id = service.data[CONF_SCHEDULE_ID]
            _LOGGER.debug("received: " + service.service + " value passed is: " + str(schedule_id))
            if service.service == SERVICE_ENABLE_SCHEDULE:
                func_name = "async_enable"
            elif service.service == SERVICE_DISABLE_SCHEDULE:
                func_name = "async_disable"
            else:
                func_name = "async_delete"

            device = switcher_conn.get_device()

            if schedule_id == 0:
                yield from getattr(schedule_id0_sensor, func_name)(device)
            elif schedule_id == 1:
                yield from getattr(schedule_id1_sensor, func_name)(device)
            elif schedule_id == 2:
                yield from getattr(schedule_id2_sensor, func_name)(device)
            elif schedule_id == 3:
                yield from getattr(schedule_id3_sensor, func_name)(device)
            elif schedule_id == 4:
                yield from getattr(schedule_id4_sensor, func_name)(device)
            elif schedule_id == 5:
                yield from getattr(schedule_id5_sensor, func_name)(device)
            elif schedule_id == 6:
                yield from getattr(schedule_id6_sensor, func_name)(device)
            elif schedule_id == 7:
                yield from getattr(schedule_id7_sensor, func_name)(device)

        @asyncio.coroutine
        def async_create_schedule_service(service):
            """Function to handle create schedule"""
            _LOGGER.debug("received: " + service.service + " values passed are: " + str(service.data))
            if service.data[CONF_RECURRING] and not service.data[CONF_DAYS]:
                _LOGGER.error("wrong parameters passed, if schedule is recursive it must contain a list of days to run at")
            else:
                requested_days = [0]
                if service.data[CONF_RECURRING]:
                    for day in service.data[CONF_DAYS]:
                        requested_days.append(DAYS_INT_DICT[day])

                weekdays = "%02x" % (int(sum(requested_days)))

                start_time = convert_timedelta_to_schedule_time(service.data[CONF_START_TIME])
                end_time = convert_timedelta_to_schedule_time(service.data[CONF_END_TIME])

                schedule_data = ENABLE_SCHEDULE + weekdays + "01" + str(start_time) + str(end_time)

                device = switcher_conn.get_device()

                successful, response = yield from async_create_schedule(device.ip, device.phone_id, device.device_id, device.device_password, schedule_data)
                if successful:
                    yield from async_parse_retrieved_schedules(response)


        """Create the sensor entities"""
        device_name_sensor = SwitcherSensor(hass, DEVICE_NAME_SENSOR_SLUG_ID, DEVICE_NAME_SENSOR_NAME, discoverd_device, ENTITY_DEVICE_NAME_CONFIG)
        time_left_sensor = SwitcherSensor(hass, TIME_LEFT_SENSOR_SLUG_ID, TIME_LEFT_SENSOR_NAME, discoverd_device, ENTITY_TIME_LEFT_CONFIG)
        electric_current_sensor = SwitcherSensor(hass, ELECTRIC_CURRENT_SENSOR_SLUG_ID, ELECTRIC_CURRENT_SENSOR_NAME, discoverd_device, ENTITY_ELECTRIC_CURRENT_CONFIG)
        auto_off_sensor = SwitcherSensor(hass, AUTO_OFF_SENSOR_SLUG_ID, AUTO_OFF_SENSOR_NAME, discoverd_device, ENTITY_AUTO_OFF_CONFIG)

        sensor_tasks = [sensor.async_update_ha_state() for sensor in [device_name_sensor, time_left_sensor, electric_current_sensor, auto_off_sensor]]
 
        yield from asyncio.wait(sensor_tasks, loop=hass.loop)

        """Create the schedule sensor entities"""
        schedule_id0_sensor = SwitcherScheduleSensor(hass, SCHEDULE_SENSOR_SLUG_ID.format("0"), SCHEDULE_SENSOR_NAME.format("0"), "0", ENTITY_SCHEDULE_SENSOR_CONFIG)
        schedule_id1_sensor = SwitcherScheduleSensor(hass, SCHEDULE_SENSOR_SLUG_ID.format("1"), SCHEDULE_SENSOR_NAME.format("1"), "1", ENTITY_SCHEDULE_SENSOR_CONFIG)
        schedule_id2_sensor = SwitcherScheduleSensor(hass, SCHEDULE_SENSOR_SLUG_ID.format("2"), SCHEDULE_SENSOR_NAME.format("2"), "2", ENTITY_SCHEDULE_SENSOR_CONFIG)
        schedule_id3_sensor = SwitcherScheduleSensor(hass, SCHEDULE_SENSOR_SLUG_ID.format("3"), SCHEDULE_SENSOR_NAME.format("3"), "3", ENTITY_SCHEDULE_SENSOR_CONFIG)
        schedule_id4_sensor = SwitcherScheduleSensor(hass, SCHEDULE_SENSOR_SLUG_ID.format("4"), SCHEDULE_SENSOR_NAME.format("4"), "4", ENTITY_SCHEDULE_SENSOR_CONFIG)
        schedule_id5_sensor = SwitcherScheduleSensor(hass, SCHEDULE_SENSOR_SLUG_ID.format("5"), SCHEDULE_SENSOR_NAME.format("5"), "5", ENTITY_SCHEDULE_SENSOR_CONFIG)
        schedule_id6_sensor = SwitcherScheduleSensor(hass, SCHEDULE_SENSOR_SLUG_ID.format("6"), SCHEDULE_SENSOR_NAME.format("6"), "6", ENTITY_SCHEDULE_SENSOR_CONFIG)
        schedule_id7_sensor = SwitcherScheduleSensor(hass, SCHEDULE_SENSOR_SLUG_ID.format("7"), SCHEDULE_SENSOR_NAME.format("7"), "7", ENTITY_SCHEDULE_SENSOR_CONFIG)

        schedule_sensor_list = [schedule_id0_sensor, schedule_id1_sensor, schedule_id2_sensor, schedule_id3_sensor, schedule_id4_sensor, schedule_id5_sensor, schedule_id6_sensor, schedule_id7_sensor]
        schedule_sensor_tasks = [schedule_sensor.async_update_ha_state() for schedule_sensor in schedule_sensor_list]

        yield from asyncio.wait(schedule_sensor_tasks, loop=hass.loop)

        """Create the input number entities"""
        current_hours = int(auto_off_sensor.state.split(':')[0])
        auto_off_hours_slider = SwitcherSlider(hass, AUTO_OFF_HOURS_SLIDER_SLUG_ID, AUTO_OFF_HOURS_SLIDER_NAME, current_hours, 1, 23, 1, None, HOURS_SLIDER_UNIT, MODE_SLIDER, ENTITY_HOURS_SLIDER_CONFIG)
        current_minutes = int(auto_off_sensor.state.split(':')[1])
        auto_off_minutes_slider = SwitcherSlider(hass, AUTO_OFF_MINUTES_SLIDER_SLUG_ID, AUTO_OFF_MINUTES_SLIDER_NAME, current_minutes, 0, 59, 1, None, MINUTES_SLIDER_UNIT, MODE_SLIDER, ENTITY_MINUTES_SLIDER_CONFIG)

        input_number_tasks = [input_number.async_update_ha_state() for input_number in [auto_off_hours_slider, auto_off_minutes_slider]]
 
        yield from asyncio.wait(input_number_tasks, loop=hass.loop)

        """Create the input select entities"""
        services_dict = hass.services.async_services()
        if NOTIFY_DOMAIN in services_dict:
            for service_name in services_dict[NOTIFY_DOMAIN]:
                if not service_name == NOTIFY_DOMAIN:
                    NOTIFICATION_SELECT_OPTIONS.append(service_name)

        select_timer_input = SwitcherSelect(hass, TURN_ON_TIMER_SELECT_SLUG_ID, TURN_ON_TIMER_SELECT_NAME, TURN_ON_TIMER_SELECT_OPTIONS, ENTITY_TURN_ON_TIMER_SELECT_CONFIG)
        select_notification_input = SwitcherSelect(hass, NOTIFICATION_SELECT_SLUG_ID, NOTIFICATION_SELECT_NAME, NOTIFICATION_SELECT_OPTIONS, ENTITY_NOTIFICATION_SELECT_CONFIG)
        select_schedule_input = SwitcherSelect(hass, SCHEDULE_SELECT_SLUG_ID, SCHEDULE_SELECT_NAME, SCHEDULE_SELECT_OPTIONS, ENTITY_SCHEDULE_SELECT_CONFIG, "0")
        select_schedule_action_input = SwitcherSelect(hass, SCHEDULE_ACTION_SELECT_SLUG_ID, SCHEDULE_ACTION_SELECT_NAME, SCHEDULE_SELECT_ACTION_OPTIONS, ENTITY_SCHEDULE_ACTION_SELECT_CONFIG, SCHEDULE_SELECT_ACTION_NONE)

        input_select_tasks = [input_select.async_update_ha_state() for input_select in [select_timer_input, select_notification_input, select_schedule_input, select_schedule_action_input]]

        yield from asyncio.wait(input_select_tasks, loop=hass.loop)

        """Create input text entities"""
        set_name_of_device_input = SwitcherText(hass, SET_NAME_OF_DEVICE_TEXT_SLUG_ID, SET_NAME_OF_DEVICE_TEXT_NAME, device_name_sensor.state, 2, 32, None, MODE_TEXT, ENTITY_SET_NAME_OF_DEVICE_TEXT_CONFIG)
        set_schedule_start_time_input = SwitcherText(hass, SET_SCHEDULE_START_TIME_TEXT_SLUG_ID, SET_SCHEDULE_START_TIME_TEXT_NAME, "17:30", 4, 5, None, MODE_TEXT, ENTITY_SCHEDULE_START_TIME_TEXT_CONFIG)
        set_schedule_end_time_input = SwitcherText(hass, SET_SCHEDULE_END_TIME_TEXT_SLUG_ID, SET_SCHEDULE_END_TIME_TEXT_NAME, "18:00", 4, 5, None, MODE_TEXT, ENTITY_SCHEDULE_END_TIME_TEXT_CONFIG)

        input_text_tasks = [input_text.async_update_ha_state() for input_text in [set_name_of_device_input, set_schedule_start_time_input, set_schedule_end_time_input]]

        yield from asyncio.wait(input_text_tasks, loop=hass.loop)

        """Create the input boolean entities"""
        select_schedule_sunday = SwitcherBoolean(hass, SUNDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID, SUNDAY_CONTROL_INPUT_BOOLEAN_NAME, False, ENTITY_SCHEDULE_DAYS_CONTROL_CONFIG)
        select_schedule_monday = SwitcherBoolean(hass, MONDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID, MONDAY_CONTROL_INPUT_BOOLEAN_NAME, False, ENTITY_SCHEDULE_DAYS_CONTROL_CONFIG)
        select_schedule_tuesday = SwitcherBoolean(hass, TUESDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID, TUESDAY_CONTROL_INPUT_BOOLEAN_NAME, False, ENTITY_SCHEDULE_DAYS_CONTROL_CONFIG)
        select_schedule_wednesday = SwitcherBoolean(hass, WEDNESDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID, WEDNESDAY_CONTROL_INPUT_BOOLEAN_NAME, False, ENTITY_SCHEDULE_DAYS_CONTROL_CONFIG)
        select_schedule_thursday = SwitcherBoolean(hass, THURSDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID, THURSDAY_CONTROL_INPUT_BOOLEAN_NAME, False, ENTITY_SCHEDULE_DAYS_CONTROL_CONFIG)
        select_schedule_friday = SwitcherBoolean(hass, FRIDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID, FRIDAY_CONTROL_INPUT_BOOLEAN_NAME, False, ENTITY_SCHEDULE_DAYS_CONTROL_CONFIG)
        select_schedule_saturday = SwitcherBoolean(hass, SATURDAY_CONTROL_INPUT_BOOLEAN_SLUG_ID, SATURDAY_CONTROL_INPUT_BOOLEAN_NAME, False, ENTITY_SCHEDULE_DAYS_CONTROL_CONFIG)

        input_boolean_tasks = [input_boolean.async_update_ha_state() for input_boolean in [select_schedule_sunday, select_schedule_monday, select_schedule_tuesday, select_schedule_wednesday, select_schedule_thursday, select_schedule_friday, select_schedule_saturday]]

        yield from asyncio.wait(input_boolean_tasks, loop=hass.loop)

        """Create the script templates"""
        auto_off_template = template_helper.Template("{{ ('0' + states." + auto_off_hours_slider.entity_id + ".state | int | string )[-2:] + ':' + ('0' + states." + auto_off_minutes_slider.entity_id + ".state | int | string )[-2:]}}", hass)

        turn_on_timer_template = template_helper.Template("{% if states." + select_timer_input.entity_id + ".state | int == 15 %}" + ENTITY_ID_FORMAT.format(SERVICE_TURN_ON_15) +
            "{% elif states." + select_timer_input.entity_id + ".state | int == 30 %}" + ENTITY_ID_FORMAT.format(SERVICE_TURN_ON_30) +
            "{% elif states." + select_timer_input.entity_id + ".state | int == 45 %}" + ENTITY_ID_FORMAT.format(SERVICE_TURN_ON_45) +
            "{% elif states." + select_timer_input.entity_id + ".state | int == 60 %}" + ENTITY_ID_FORMAT.format(SERVICE_TURN_ON_60) +
            "{% endif %}", hass)

        update_device_name_template = template_helper.Template("{{ states." + set_name_of_device_input.entity_id + ".state }}", hass)

        perform_schedule_action_service_template = template_helper.Template("{% set selected_action = states('" + select_schedule_action_input.entity_id + "') %}" + 
            "{% if selected_action == '" + SCHEDULE_SELECT_ACTION_ENABLE + "' %}" + ENTITY_ID_FORMAT.format(SERVICE_ENABLE_SCHEDULE) +
            "{% elif selected_action == '" + SCHEDULE_SELECT_ACTION_DISABLE + "' %}" + ENTITY_ID_FORMAT.format(SERVICE_DISABLE_SCHEDULE) + 
            "{% elif selected_action == '" + SCHEDULE_SELECT_ACTION_DELETE + "' %}" + ENTITY_ID_FORMAT.format(SERVICE_DELETE_SCHEDULE)  +
            "{% else %}{{ selected_action }}{% endif %}", hass)

        perform_schedule_action_data_template = template_helper.Template("{{ states('" + select_schedule_input.entity_id + "') | int }}" , hass)

        create_schedule_start_time_template = template_helper.Template("{{ states('" + set_schedule_start_time_input.entity_id + "') }}", hass)

        create_schedule_end_time_template = template_helper.Template("{{ states('" + set_schedule_end_time_input.entity_id + "') }}", hass)

        create_schedule_recurring_template = template_helper.Template("{% if is_state('" + select_schedule_sunday.entity_id + "', '" + STATE_ON + "') %}true" +
            "{% elif is_state('" + select_schedule_monday.entity_id + "', '" + STATE_ON + "') %}true" +
            "{% elif is_state('" + select_schedule_tuesday.entity_id + "', '" + STATE_ON + "') %}true" +
            "{% elif is_state('" + select_schedule_wednesday.entity_id + "', '" + STATE_ON + "') %}true" +
            "{% elif is_state('" + select_schedule_thursday.entity_id + "', '" + STATE_ON + "') %}true" +
            "{% elif is_state('" + select_schedule_friday.entity_id + "', '" + STATE_ON + "') %}true" +
            "{% elif is_state('" + select_schedule_saturday.entity_id + "', '" + STATE_ON + "') %}true" +
            "{% else %}false{% endif%}", hass)

        create_schedule_days_template = template_helper.Template("{% set days_string = '' %}" +
            "{% if is_state('" + select_schedule_sunday.entity_id + "', '" + STATE_ON + "') %}{% set days_string = days_string + '" + SUNDAY + ",' %}{% endif %}" +
            "{% if is_state('" + select_schedule_monday.entity_id + "', '" + STATE_ON + "') %}{% set days_string = days_string + '" + MONDAY + ",' %}{% endif %}" +
            "{% if is_state('" + select_schedule_tuesday.entity_id + "', '" + STATE_ON + "') %}{% set days_string = days_string + '" + TUESDAY + ",' %}{% endif %}" +
            "{% if is_state('" + select_schedule_wednesday.entity_id + "', '" + STATE_ON + "') %}{% set days_string = days_string + '" + WEDNESDAY + ",' %}{% endif %}" +
            "{% if is_state('" + select_schedule_thursday.entity_id + "', '" + STATE_ON + "') %}{% set days_string = days_string + '" + THURSDAY + ",' %}{% endif %}" +
            "{% if is_state('" + select_schedule_friday.entity_id + "', '" + STATE_ON + "') %}{% set days_string = days_string + '" + FRIDAY + ",' %}{% endif %}" +
            "{% if is_state('" + select_schedule_saturday.entity_id + "', '" + STATE_ON + "') %}{% set days_string = days_string + '" + SATURDAY + ",' %}{% endif %}" +
            "{% if days_string | length > 1 %}{{ days_string[:-1] }}{% endif %}", hass)

        """Create the script config schemas"""
        auto_off_config_data = {
            ATTR_SERVICE: ENTITY_ID_FORMAT.format(SERVICE_SET_AUTO_OFF),
            CONF_DATA_TEMPLATE: {
                CONF_AUTO_OFF: auto_off_template
            }
        }

        turn_on_timer_config_data = {
            CONF_SERVICE_TEMPLATE: turn_on_timer_template
        }

        update_device_name_config_data = {
            ATTR_SERVICE: ENTITY_ID_FORMAT.format(SERVICE_UPDATE_DEVICE_NAME),
            CONF_DATA_TEMPLATE: {
                CONF_NAME: update_device_name_template
            }
        }

        perform_schedule_action_config = {
            CONF_SERVICE_TEMPLATE: perform_schedule_action_service_template,
            CONF_DATA_TEMPLATE: {
                CONF_SCHEDULE_ID: perform_schedule_action_data_template
            }
        }

        create_schedule_config = {
            ATTR_SERVICE: ENTITY_ID_FORMAT.format(SERVICE_CREATE_SCHEDULE),
            CONF_DATA_TEMPLATE: {
                CONF_START_TIME: create_schedule_start_time_template,
                CONF_END_TIME: create_schedule_end_time_template,
                CONF_RECURRING: create_schedule_recurring_template,
                CONF_DAYS: create_schedule_days_template
            }
        }

        """Create the script entities"""
        set_auto_off_script = SwitcherScript(hass, AUTO_OFF_SCRIPT_SLUG_ID, AUTO_OFF_SCRIPT_NAME, [auto_off_config_data], ENTITY_AUTO_OFF_SCRIPT_CONFIG)
        turn_on_timer_script = SwitcherScript(hass, TURN_ON_TIMER_SCRIPT_SLUG_ID, TURN_ON_TIMER_SCRIPT_NAME, [turn_on_timer_config_data], ENTITY_TURN_ON_TIMER_SCRIPT_CONFIG)
        update_device_name_script = SwitcherScript(hass, UPDATE_DEVICE_NAME_SCRIPT_SLUG_ID, UPDATE_DEVICE_NAME_SCRIPT_NAME, [update_device_name_config_data], ENTITY_UPDATE_DEVICE_NAME_SCRIPT_CONFIG)
        perform_schedule_action_script = SwitcherScript(hass, PERFORM_SCHEDULE_ACTION_SCRIPT_SLUG_ID, PERFORM_SCHEDULE_ACTION_SCRIPT_NAME, [perform_schedule_action_config], ENTITY_PERFORM_SCHEDULE_ACTION_SCRIPT_CONFIG)
        create_schedule_script = SwitcherScript(hass, CREATE_SCHEDULE_SCRIPT_SLUG_ID, CREATE_SCHEDULE_SCRIPT_NAME, [create_schedule_config], ENTITY_CREATE_SCHEDULE_SCRIPT_CONFIG)

        script_tasks = [script.async_update_ha_state() for script in [set_auto_off_script, turn_on_timer_script, update_device_name_script, perform_schedule_action_script, create_schedule_script]]

        yield from asyncio.wait(script_tasks, loop=hass.loop)

        """Create the switch entities"""
        control_switch = SwitcherControl(hass, CONTROL_SWITCH_SLUG_ID, CONTROL_SWITCH_NAME, discoverd_device, ENTITY_CONTROL_CONFIG)
        switch_tasks = [switch.async_update_ha_state() for switch in [control_switch]]

        yield from asyncio.wait(switch_tasks, loop=hass.loop)

        """Register entities for actions by device"""
        switcher_conn.register_state_entities([device_name_sensor, time_left_sensor, electric_current_sensor, auto_off_sensor, control_switch])
        switcher_conn.register_notify_select_entity(select_notification_input)

        """Set the entities order for the groups"""
        if create_groups:
            control_group_entities = [
                control_switch.entity_id,
                time_left_sensor.entity_id,
                electric_current_sensor.entity_id,
                device_name_sensor.entity_id,
                auto_off_sensor.entity_id,
                select_timer_input.entity_id,
                turn_on_timer_script.entity_id
            ]

            config_group_entities = [
                select_notification_input.entity_id,
                auto_off_hours_slider.entity_id,
                auto_off_minutes_slider.entity_id,
                set_auto_off_script.entity_id,
                set_name_of_device_input.entity_id,
                update_device_name_script.entity_id
            ]

            schedule_group_entities = [
                select_schedule_input.entity_id,
                select_schedule_action_input.entity_id,
                perform_schedule_action_script.entity_id,
                schedule_id0_sensor.entity_id,
                schedule_id1_sensor.entity_id,
                schedule_id2_sensor.entity_id,
                schedule_id3_sensor.entity_id,
                schedule_id4_sensor.entity_id,
                schedule_id5_sensor.entity_id,
                schedule_id6_sensor.entity_id,
                schedule_id7_sensor.entity_id
            ]

            create_schedule_entities = [
                set_schedule_start_time_input.entity_id,
                set_schedule_end_time_input.entity_id,
                select_schedule_sunday.entity_id,
                select_schedule_monday.entity_id,
                select_schedule_tuesday.entity_id,
                select_schedule_wednesday.entity_id,
                select_schedule_thursday.entity_id,
                select_schedule_friday.entity_id,
                select_schedule_saturday.entity_id,
                create_schedule_script.entity_id
            ]

            """Create the groups"""
            create_groups_tasks = []
            create_groups_tasks.append(hass.components.group.Group.async_create_group(hass, GROUP_CONTROL_NAME, control_group_entities, object_id=GROUP_CONTROL_ENTITY, control=ATTR_HIDDEN))
            create_groups_tasks.append(hass.components.group.Group.async_create_group(hass, GROUP_CONFIG_NAME, config_group_entities, object_id=GROUP_CONFIG_ENTITY, control=ATTR_HIDDEN))
            create_groups_tasks.append(hass.components.group.Group.async_create_group(hass, GROUP_SCHEDULES_NAME, schedule_group_entities, object_id=GROUP_SCHEDULES_ENTITY, control=ATTR_HIDDEN))
            create_groups_tasks.append(hass.components.group.Group.async_create_group(hass, GROUP_CREATE_SCHEDULE_NAME, create_schedule_entities, object_id=GROUP_CREATE_SCHEDULE_ENTITY, control=ATTR_HIDDEN))

            if create_view:
                view_group_entities = [
                    GROUP_ENTITY_ID_FORMAT.format(GROUP_CONTROL_ENTITY),
                    GROUP_ENTITY_ID_FORMAT.format(GROUP_CONFIG_ENTITY),
                    GROUP_ENTITY_ID_FORMAT.format(GROUP_SCHEDULES_ENTITY),
                    GROUP_ENTITY_ID_FORMAT.format(GROUP_CREATE_SCHEDULE_ENTITY)
                ]

                create_groups_tasks.append(hass.components.group.Group.async_create_group(hass, VIEW_NAME, view_group_entities, view=True, object_id=VIEW_ENTITY))

            yield from asyncio.gather(*create_groups_tasks, loop=hass.loop)

        """Register the services"""
        for service in [SERVICE_TURN_ON_15, SERVICE_TURN_ON_30, SERVICE_TURN_ON_45, SERVICE_TURN_ON_60]:
            hass.services.async_register(DOMAIN, service, async_switcher_control, schema={})
        
        hass.services.async_register(DOMAIN, SERVICE_TURN_ON, async_switcher_control, schema=TURN_ONOFF_SERVICE_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_TURN_OFF, async_switcher_control, schema=TURN_ONOFF_SERVICE_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_SET_AUTO_OFF, async_set_auto_off_service, schema=SET_AUTO_OFF_SERVICE_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_UPDATE_DEVICE_NAME, async_update_device_name_service, schema=UPDATE_DEVICE_NAME_SERVICE_SCHEMA)
        
        for service in [SERVICE_ENABLE_SCHEDULE, SERVICE_DISABLE_SCHEDULE, SERVICE_DELETE_SCHEDULE]:
            hass.services.async_register(DOMAIN, service, async_manage_schedules_service, schema=MANAGE_SCHEDULE_SERVICE_SCHEMA)

        hass.services.async_register(DOMAIN, SERVICE_CREATE_SCHEDULE, async_create_schedule_service, schema=CREATE_SCHEDULE_SERVICE_SCHEMA)
        
        """Resgister intervaled calls for schedule update"""
        yield from async_update_schedules_call()
        async_track_time_interval(hass, async_update_schedules_call, schedules_scan_interval)

    """Get group parameters"""
    create_groups = config[DOMAIN][CONF_CREATE_GROUPS]
    create_view = config[DOMAIN][CONF_CREATE_VIEW]
    schedules_scan_interval = config[DOMAIN][CONF_SCHEDULE_SCAN_INTERVAL]

    """Listen for discoverd device"""
    hass.bus.async_listen_once(EVENT_SWITCHER_DISCOVERY_DATA, discover_devices)

    """Start the connection thread"""
    switcher_conn = SwitcherV2(hass, config[DOMAIN])
    switcher_conn.start()

    return True


"""#############################
#### Represntation Classes #####
#############################"""


class SwitcherV2(threading.Thread):
    """represntation of the switcher version 2 connection"""
    def __init__(self, hass, config):
        threading.Thread.__init__(self)
        """initialize the manager"""
        self._hass = hass
        self._device = None
        self._ok_to_run = False
        self._last_exception_dt = None
        self._exception_count = 0
        self._config = config
        self._state_entities = None
        self._notify_select_entity = None

    def run(self):
        """register functions for event listening"""
        self._hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, self.stop)

        """start discovery loop"""
        _LOGGER.debug("starting broadcast watch loop")
        try:
            tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            #tcp_socket.bind(("0.0.0.0", 20002))
            tcp_socket.bind(SOCKET_BIND_TUP)
            self._ok_to_run = True
        except:
            _LOGGER.error("exception while binding socket" + traceback.format_exc())

        conf_dev_id = self._config[CONF_DEVICE_ID].lower()
        while self._ok_to_run:
            try:
                message, address = tcp_socket.recvfrom(1024)
                msg = SwitcherV2BroadcastMSG(message)
                if msg.verified:
                    if conf_dev_id == msg.device_id:
                        state_changed = datetime.datetime.now()
                        if self._device is None:
                            """New device disvoverd"""
                            self._device = SwitcherV2Device(self.ident, msg.device_id, msg.ip, msg.mac, msg.name, msg.state, msg.time_left, msg.auto_off, msg.power, msg.current, self._config[CONF_PHONE_ID].lower(), self._config[CONF_DEVICE_PASSWORD].lower(), state_changed)
                            self._hass.bus.fire(EVENT_SWITCHER_DISCOVERY_DATA, {CONF_DEVICE: self._device})
                        else:
                            """Update known device"""
                            change_occur = True
                            prev_state = self._device.state
                            if prev_state == msg.state:
                                state_changed = self._device.last_state_change
                                change_occur = False

                            self._device.update_device_data(self.ident, msg.ip, msg.name, msg.state, msg.time_left, msg.auto_off, msg.power, msg.current, state_changed)
                            self.update_states_to_entities()

                            if change_occur:
                                self.send_state_change_notification()
                    else:
                        _LOGGER.warning("found switcher device with different device id")
                else:
                    _LOGGER.debug("message not verified as a switcher v2 broadcast message")
            except:
                _LOGGER.exception("exception while discovering device data: " + traceback.format_exc())
                self.check_loop_run()
                continue

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    def check_loop_run(self):
        """Stop thread of too many excption (x exception in y minutes) occured"""

        """max exceptions allowed in loop before exiting"""
        max_exceptions_before_stop = 50
        """max minutes to remmember the last excption"""
        max_minutes_from_last_exception = 1

        current_dt = datetime.datetime.now()
        if not (self._last_exception_dt is None):
            if (self._last_exception_dt.year == current_dt.year and self._last_exception_dt.month == current_dt.month and self._last_exception_dt.day == current_dt.day):
                calc_dt = current_dt - self._last_exception_dt
                diff = divmod(calc_dt.days * 86400 + calc_dt.seconds, 60)
                if (diff[0] > max_minutes_from_last_exception):
                    self._exception_count = 0
                else:
                    self._exception_count += 1
            else:
                self._exception_count = 0
        else:
            self._exception_count = 0

        if not (max_exceptions_before_stop > self._exception_count):
            _LOGGER.error("max exceptions allowed in watch loop exceeded, stoping thread")
            self.stop()

        self._last_exception_dt = current_dt

    def stop(self, event=None):
        """Stop the thread"""
        if not event is None:
            _LOGGER.debug("received :" + event.event_type + " shutting down connection manager")
        self._ok_to_run = False

    def get_device(self):
        """return devices data"""
        return self._device

    def register_state_entities(self, state_entities):
        """Register state entities for constant updates"""
        self._state_entities = state_entities

    def register_notify_select_entity(self, entity):
        """Register the notify select entity for notifications"""
        self._notify_select_entity = entity

    def update_states_to_entities(self):
        """Update new device state to entities"""
        if self._state_entities is not None:
            update_tasks = [entity.async_update_received(self._device) for entity in self._state_entities]
            self._hass.add_job(asyncio.wait(update_tasks, loop=self._hass.loop))

    def send_state_change_notification(self):
        """Send notification for state changes"""
        if self._notify_select_entity and not self._notify_select_entity.state == NOTIFICATION_SELECT_NONE:
            if self._device.state == STATE_ON:
                data = TIMER_TURN_ON_NOTIFICATION_DATA
                data["message"] = data["message"].format(self._device.name, self._device.time_left)
            else:
                data = TIMER_TURN_OFF_NOTIFICATION_DATA
                data["message"] = data["message"].format(self._device.name)
            
            self._hass.add_job(self._hass.services.async_call(NOTIFY_DOMAIN, self._notify_select_entity.state, data))


class SwitcherV2Device(object):
    """represntation of the switcher version data store"""
    def __init__(self, thread_id, device_id, ip_address, mac_address, name, state, time_left, auto_off, power_consumption, electric_current, phone_id, device_password, last_state_change):
        self._device_id = device_id
        self._mac_address = mac_address
        self._phone_id = phone_id
        self._device_password = device_password
        self.update_device_data(thread_id, ip_address, name, state, time_left, auto_off, power_consumption, electric_current, last_state_change)

    def update_device_data(self, thread_id, ip_address, name, state, time_left, auto_off, power_consumption, electric_current, last_state_change):
        self._thread_id = thread_id
        self._ip_address = ip_address
        self._name = name
        self._state = state
        self._time_left = time_left
        self._auto_off = auto_off
        self._power_consumption = power_consumption
        self._electric_current = electric_current
        self._last_update = datetime.datetime.now()
        self._last_state_change = last_state_change

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def thread_id(self):
        """Return the thread id"""
        return self._thread_id

    @property
    def device_id(self):
        """Return the device id"""
        return self._device_id

    @property
    def ip(self):
        """Return the ip address"""
        return self._ip_address

    @property
    def mac(self):
        """Return the mac address"""
        return self._mac_address

    @property
    def name(self):
        """Return the device name"""
        return self._name

    @property
    def state(self):
        """Return the device state"""
        return self._state

    @property
    def time_left(self):
        """Return the time left to auto-off"""
        return self._time_left

    @property
    def auto_off(self):
        """Return the auto-off configuration value"""
        return self._auto_off

    @property
    def power_consumption(self):
        """Return the power consumption in watts"""
        return self._power_consumption

    @property
    def electric_current(self):
        """Return the power consumption in amps"""
        return self._electric_current

    @property
    def phone_id(self):
        """Return the phone id"""
        return self._phone_id

    @property
    def device_password(self):
        """Return the device password"""
        return self._device_password

    @property
    def last_update(self):
        """Return the timestamp of the last update"""
        return self._last_update

    @property
    def last_state_change(self):
        """Return the timestamp of the state change"""
        return self._last_state_change


class SwitcherV2Schedule(object):
    """represnation of the switcher version 2 schedule"""
    def __init__(self, idx, schedule_details):
        self._schedule_id = None
        self._enabled = False
        self._recurring = False
        self._days = []
        self._start_time = None
        self._end_time = None
        self._duration = None
        self._schedule_data = None
        try:
            self._schedule_id = str(int(schedule_details[idx][0:2], 16))
            if int(schedule_details[idx][2:4], 16) == 1:
                self._enabled = True
            if not schedule_details[idx][4:6] == "00":
                self._recurring = True
                if schedule_details[idx][4:6] == "fe":
                    self._days = ALL_DAYS
                else:
                    self._days = get_days_list_from_bytes(bytearray(ba.unhexlify((schedule_details[idx][4:6])))[0])

            self._start_time = get_time_from_bytes(schedule_details[idx][8:16])
            self._end_time = get_time_from_bytes(schedule_details[idx][16:24])
            self._duration = str(datetime.datetime.strptime(self._end_time,'%H:%M') - datetime.datetime.strptime(self._start_time,'%H:%M'))

            time_id = schedule_details[idx][0:2]
            on_off = schedule_details[idx][2:4]
            week = schedule_details[idx][4:6]
            timestate = schedule_details[idx][6:8]
            start_time = schedule_details[idx][8:16]
            end_time = schedule_details[idx][16:24]
            self._schedule_data = (time_id + on_off + week + timestate + start_time + end_time)
        except:
            _LOGGER.error("failed to parse schedule data " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def schedule_id(self):
        """Return the schedule id"""
        return self._schedule_id
        
    @property
    def enabled(self):
        """Return true if enabled"""
        return self._enabled
        
    @property
    def recurring(self):
        """Return true if recurring"""
        return self._recurring
        
    @property
    def days(self):
        """Return the weekdays of the schedule"""
        return self._days
        
    @property
    def start_time(self):
        """Return the start time of the schedule"""
        return self._start_time
        
    @property
    def end_time(self):
        """Return the end time of the schedule"""
        return self._end_time
        
    @property
    def duration(self):
        """Return the duration of the schedule"""
        return self._duration
        
    @property
    def schedule_data(self):
        """Return the schedule data for managing the schedule"""
        return self._schedule_data

    def set_enabled(self, value):
        """Function to set the device as enabled or disabled"""
        self._enabled = value

    def set_schedule_data(self, data):
        """Function to set the schedule data for managing the schedule"""
        self._schedule_data = data


"""#############################
###### Response Messages #######
#############################"""


class SwitcherV2BroadcastMSG(object):
    """represntation of the switcher version 2 broadcast message"""
    def __init__(self, message):
        self._verified = self._validated = False
        self._ip_address = self._mac = self._name = self._device_id = self._state = self._time_to_auto_off = self._auto_off_config_time = None
        self._power_consumption = self._electric_current = 0

        try:
            self._verified = ba.hexlify(message)[0:4].decode(ENCODING_CODEC) == 'fef0' and len(message) == 165
            if self._verified:
                temp_ip = ba.hexlify(message)[152:160]
                ip_addr = int(temp_ip[6:8] + temp_ip[4:6] + temp_ip[2:4] + temp_ip[0:2], 16)
                self._ip_address = socket.inet_ntoa(pack("<L", ip_addr))

                mac = ba.hexlify(message)[160:172].decode(ENCODING_CODEC).upper()
                self._mac = mac[0:2] + ':' + mac[2:4] + ':' + mac[4:6] + ':' + mac[6:8] + ':' + mac[8:10] + ':' + mac[10:12]

                self._name = message[42:74].decode(ENCODING_CODEC).rstrip('\x00')

                self._device_id = ba.hexlify(message)[36:42].decode(ENCODING_CODEC)

                self._state = self._time_to_auto_off = STATE_ON if ba.hexlify(message)[266:270].decode(ENCODING_CODEC) == STATE_RESPONSE_ON else STATE_OFF

                temp_auto_off_config = ba.hexlify(message)[310:318]
                temp_auto_off_seconds = int(temp_auto_off_config[6:8] + temp_auto_off_config[4:6] + temp_auto_off_config[2:4] + temp_auto_off_config[0:2], 16)
                self._auto_off_config_time = convert_seconds_to_iso_time(temp_auto_off_seconds)

                if self._state == STATE_ON:
                    temp_power = ba.hexlify(message)[270:278]
                    self._power_consumption = int(temp_power[2:4] + temp_power[0:2], 16)
                    self._electric_current = round((self._power_consumption / float(220)), 1)

                    temp_time_left = ba.hexlify(message)[294:302]
                    temp_time_left_seconds = int(temp_time_left[6:8] + temp_time_left[4:6] + temp_time_left[2:4] + temp_time_left[0:2], 16)
                    self._time_to_auto_off = convert_seconds_to_iso_time(temp_time_left_seconds)

            self._validated = True
        except:
            _LOGGER.exception("failed to parse broadcast message " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def verified(self):
        """return rather or not the message was verified as a switcher v2 message"""
        return self._verified if self._validated == True else self._validated

    @property
    def ip(self):
        """return the ip address"""
        return self._ip_address

    @property
    def mac(self):
        """return the mac address"""
        return self._mac

    @property
    def name(self):
        """return the device name"""
        return self._name

    @property
    def device_id(self):
        """return the device id"""
        return self._device_id

    @property
    def state(self):
        """return the state of the device"""
        return self._state

    @property
    def time_left(self):
        """return the time left to auto-offf"""
        return self._time_to_auto_off

    @property
    def auto_off(self):
        """return the auto-off configuration value"""
        return self._auto_off_config_time

    @property
    def power(self):
        """return the power consumptionin watts"""
        return self._power_consumption

    @property
    def current(self):
        """return the power consumptionin amps"""
        return self._electric_current


class SwitcherV2LoginResponseMSG(object):
    """represntation of the switcher version 2 login response message"""
    def __init__(self, response):
        self._unparsed_response = response
        self._session_id = None
        try:
            self._session_id = ba.hexlify(response)[16:24].decode(ENCODING_CODEC)
        except:
            _LOGGER.exception("failed to parse login response message " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def unparsed_response(self):
        """Return the uparsed response message"""
        return self._unparsed_response

    @property
    def session_id(self):
        """Return the retrieved session id"""
        return self._session_id

    @property
    def successful(self):
        """Return the status of the message"""
        return self._session_id is not None


class SwitcherV2StateResponseMSG(object):
    """represntation of the switcher version 2 state response message"""
    def __init__(self, response):
        self._unparsed_response = response
        self._state = self._time_to_auto_off = self._auto_off_config_time = None
        self._power_consumption = self._electric_current = 0

        try:
            temp_power = ba.hexlify(response)[154:162]
            self._power_consumption = int(temp_power[2:4] + temp_power[0:2], 16)
            self._electric_current = round((self._power_consumption / float(220)), 1)

            temp_time_left = ba.hexlify(response)[178:186]
            temp_time_left_seconds = int(temp_time_left[6:8] + temp_time_left[4:6] + temp_time_left[2:4] + temp_time_left[0:2], 16)
            self._time_to_auto_off = convert_seconds_to_iso_time(temp_time_left_seconds)

            temp_auto_off = ba.hexlify(response)[194:202]
            temp_auto_off_seconds = int(temp_auto_off[6:8] + temp_auto_off[4:6] + temp_auto_off[2:4] + temp_auto_off[0:2], 16)
            self._auto_off_config_time = convert_seconds_to_iso_time(temp_auto_off_seconds)

            temp_state = ba.hexlify(response)[150:154].decode(ENCODING_CODEC)
            self._state = STATE_ON if temp_state == STATE_RESPONSE_ON else STATE_OFF if temp_state == STATE_RESPONSE_OFF else None

        except:
            _LOGGER.exception("failed to parse state response message " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def unparsed_response(self):
        """Return the uparsed response message"""
        return self._unparsed_response

    @property
    def state(self):
        """Return the state"""
        return self._state

    @property
    def time_left(self):
        """Return the time left to auto-off"""
        return self._time_to_auto_off

    @property
    def auto_off(self):
        """Return the auto-off configuration value"""
        return self._auto_off_config_time

    @property
    def power(self):
        """Return the current power consumption in watts"""
        return self._power_consumption

    @property
    def current(self):
        """Return the power consumption in amps"""
        return self._electric_current

    @property
    def successful(self):
        """Return the status of the message"""
        return self._state is not None


class SwitcherV2ControlResponseMSG(object):
    """represntation of the switcher version 2 control response message"""
    def __init__(self, response):
        self._unparsed_response = None
        try:
            self._unparsed_response = ba.hexlify(response)[16:24].decode(ENCODING_CODEC)
        except:
            _LOGGER.exception("failed to parse control response message " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def unparsed_response(self):
        """Return the uparsed response message"""
        return self._unparsed_response

    @property
    def successful(self):
        """Return the status of the message"""
        return self._unparsed_response is not None


class SwitcherV2SetAutoOffResponseMSG(object):
    """represntation of the switcher version 2 set auto-off response message"""
    def __init__(self, response):
        self._unparsed_response = None
        try:
            self._unparsed_response = ba.hexlify(response)[16:24].decode(ENCODING_CODEC)
        except:
            _LOGGER.exception("failed to parse set auto-off response message " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def unparsed_response(self):
        """Return the uparsed response message"""
        return self._unparsed_response

    @property
    def successful(self):
        """Return the status of the message"""
        return self._unparsed_response is not None


class SwitcherV2UpdateNameResponseMSG(object):
    """represntation of the switcher version 2 update name response message"""
    def __init__(self, response):
        self._unparsed_response = None
        try:
            self._unparsed_response = ba.hexlify(response)[16:24].decode(ENCODING_CODEC)
        except:
            _LOGGER.exception("failed to parse update name response message " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def unparsed_response(self):
        """Return the uparsed response message"""
        return self._unparsed_response

    @property
    def successful(self):
        """Return the status of the message"""
        return self._unparsed_response is not None


class SwitcherV2GetScheduleResponseMSG(object):
    """represnation of the switcher version 2 get schedule message"""
    def __init__(self, response):
        self._unparsed_response = None
        self._schedule_list = []
        try:
            self._unparsed_response = ba.hexlify(response).decode(ENCODING_CODEC)

            split_string_lambda = lambda x, n: [x[i:i+n] for i in range(0, len(x), n)]

            res = ba.hexlify(response)
            idx = res[90:-8].decode(ENCODING_CODEC)
            schedules_details = split_string_lambda(idx,32)
            if not len(schedules_details) == 0:
                for i in range(len(schedules_details)):
                    schedule = SwitcherV2Schedule(i, schedules_details)
                    self._schedule_list.append(schedule)
        except:
            _LOGGER.exception("failed to parse get schedules response message " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def unparsed_response(self):
        """Return the uparsed response message"""
        return self._unparsed_response

    @property
    def successful(self):
        """Return the status of the message"""
        return self._unparsed_response is not None

    @property
    def found_schedules(self):
        """Return true if found shedules in the response"""
        return not self._schedule_list == []

    @property
    def get_schedules(self):
        """Return the schedules list"""
        return self._schedule_list


class SwitcherV2DisableEnableScheduleResponseMSG(object):
    """represntation of the switcher version 2 disable enable schedule response message"""
    def __init__(self, response):
        self._unparsed_response = None
        try:
            self._unparsed_response = ba.hexlify(response)[16:24].decode(ENCODING_CODEC)
        except:
            _LOGGER.exception("failed to parse disable enable schedule response message " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def unparsed_response(self):
        """Return the uparsed response message"""
        return self._unparsed_response

    @property
    def successful(self):
        """Return the status of the message"""
        return self._unparsed_response is not None


class SwitcherV2DeleteScheduleResponseMSG(object):
    """represntation of the switcher version 2 delete schedule response message"""
    def __init__(self, response):
        self._unparsed_response = None
        try:
            self._unparsed_response = ba.hexlify(response)[16:24].decode(ENCODING_CODEC)
        except:
            _LOGGER.exception("failed to parse delete schedule response message " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def unparsed_response(self):
        """Return the uparsed response message"""
        return self._unparsed_response

    @property
    def successful(self):
        """Return the status of the message"""
        return self._unparsed_response is not None


class SwitcherV2CreateScheduleResponseMSG(object):
    """represntation of the switcher version 2 create schedule response message"""
    def __init__(self, response):
        self._unparsed_response = None
        try:
            self._unparsed_response = ba.hexlify(response)[16:24].decode(ENCODING_CODEC)
        except:
            _LOGGER.exception("failed to parse create schedule response message " + traceback.format_exc())

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def unparsed_response(self):
        """Return the uparsed response message"""
        return self._unparsed_response

    @property
    def successful(self):
        """Return the status of the message"""
        return self._unparsed_response is not None


"""#############################
### Home Assistant Entities ####
#############################"""


class SwitcherSensor(Entity):
    """Representation of the sensor entity"""
    def __init__(self, hass, slug_id, name, device, entity_config):
        """Initialize the sensor."""
        self.hass = hass
        self._entity_config = entity_config
        self._device = device
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, slug_id, hass=hass)
        self._name = name

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        if self._entity_config[CONF_TYPE] == ENTITY_TIME_LEFT_TYPE:
            return self._device.time_left
        if self._entity_config[CONF_TYPE] == ENTITY_AUTO_OFF_TYPE:
            return self._device.auto_off
        if self._entity_config[CONF_TYPE] == ENTITY_ELECTRIC_CURRENT_TYPE:
            return self._device.electric_current
        if self._entity_config[CONF_TYPE] == ENTITY_DEVICE_NAME_TYPE:
            return self._device.name
        return None

    @property
    def should_poll(self):
        """No polling needed"""
        return False

    @property
    def icon(self):
        """Return mdi icon"""
        return self._entity_config[CONF_ICON]

    @property
    def state_attributes(self):
        """Return the state attributes"""
        return {
            CONF_LAST_UPDATE: self._device.last_update,
            CONF_STATE_CARD: self._entity_config[CONF_CARD]
        }

    @asyncio.coroutine
    def async_update_received(self, device):
        """Update the device's state and attributes upon device update"""
        _LOGGER.debug('received update for ' + self.entity_id)
        self._device = device
        yield from self.async_update_ha_state()


class SwitcherControl(ToggleEntity):
    """Representation of a the switch entity"""
    def __init__(self, hass, slug_id, name, device, entity_config):
        """Initialize the switch"""
        self.hass = hass
        self._entity_config = entity_config
        self._device = device
        self._state = device.state
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, slug_id, hass=hass)
        self._name = name
        self._self_initiated = False

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def name(self):
        """Return the name of the entity"""
        return self._name

    @property
    def icon(self):
        """Return the mdi icon"""
        return self._entity_config[CONF_ICON]

    @property
    def assumed_state(self):
        """State not assumed"""
        return False

    @property
    def should_poll(self):
        """No polling needed"""
        return False

    @property
    def available(self):
        """Return true if the device is available for use"""
        return self._state is not None

    @property
    def is_on(self):
        """Return true if switch is on"""
        return self._state == STATE_ON

    @property
    def current_power_w(self):
        """Return the current power usage in watts"""
        return self._device.power_consumption

    @property
    def state_attributes(self):
        """Return the state attributes"""
        attributes = {}
        attributes[CONF_IP_ADDRESS] = self._device.ip
        attributes[CONF_DEVICE_ID] = self._device.device_id
        attributes[CONF_CURRENT_POWER_CONSUMPTIOMN] = self._device.power_consumption
        attributes[CONF_ELECTRIC_CURRENT] = self._device.electric_current
        attributes[CONF_TIME_LEFT] = self._device.time_left
        attributes[CONF_AUTO_OFF] = self._device.auto_off
        attributes[CONF_LAST_UPDATE] = self._device.last_update
        attributes[CONF_LAST_STATE_CHANGE] = self._device.last_state_change
        attributes[CONF_DEVICE_NAME] = self._device.name
        attributes[CONF_STATE_CARD] = self._entity_config[CONF_CARD]

        return attributes

    @asyncio.coroutine
    def async_turn_on_with_timer(self, minutes):
        """turn on the device and set timer for off"""
        _LOGGER.debug("received turn on request with timer for " + minutes + " minutes for " + self.entity_id)
        result = yield from async_send_command_to_device(self._device.ip, self._device.phone_id, self._device.device_id, self._device.device_password, COMMAND_ON, minutes)
        if result:
            self._state = STATE_ON
            self._self_initiated = True
            yield from self.async_update_ha_state()
            _LOGGER.debug("successfully turned on with timer for " + self.entity_id)
        else:
            _LOGGER.error("failed to turn on with timer for " + self.entity_id)

    @asyncio.coroutine
    def async_turn_on(self, **kwargs):
        """turn on the device"""
        _LOGGER.debug("received turn on request for " + self.entity_id)
        result = yield from async_send_command_to_device(self._device.ip, self._device.phone_id, self._device.device_id, self._device.device_password, COMMAND_ON)
        if result:
            self._state = STATE_ON
            self._self_initiated = True
            yield from self.async_update_ha_state()
            _LOGGER.debug("successfully turned on for " + self.entity_id)
        else:
            _LOGGER.error("failed to turn on for " + self.entity_id)

    @asyncio.coroutine
    def async_turn_off(self, **kwargs):
        """turn off the device"""
        _LOGGER.debug("received turn off request for " + self.entity_id)
        result = yield from async_send_command_to_device(self._device.ip, self._device.phone_id, self._device.device_id, self._device.device_password, COMMAND_OFF)
        if result:
            self._state = STATE_OFF
            self._self_initiated = True
            yield from self.async_update_ha_state()
            _LOGGER.debug("successfully turned off")
        else:
            _LOGGER.error("failed to turn off the device")

    @asyncio.coroutine
    def async_update_received(self, device):
        """Update the device's state and attributes upon device update"""
        _LOGGER.debug("received update for " + self.entity_id)
        self._device = device
        if self._self_initiated:
            self._self_initiated = False
        else:
            self._state = self._device.state

        yield from self.async_update_ha_state()


class SwitcherBoolean(ToggleEntity):
    """Representation of the input_boolean"""
    def __init__(self, hass, slug_id, name, initial, entity_config):
        """Initialize a boolean input."""
        self.hass = hass
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, slug_id, hass=hass)
        self._name = name
        self._state = initial
        self._entity_config = entity_config

    @property
    def should_poll(self):
        """No polling needed"""
        return True

    @property
    def name(self):
        """Return the name of the entity"""
        return self._name

    @property
    def icon(self):
        """Return the mdi icon"""
        return self._entity_config[CONF_ICON]

    @property
    def is_on(self):
        """Return true if entity is on."""
        return self._state

    @property
    def state_attributes(self):
        """Return the state attributes"""
        return {
            CONF_STATE_CARD: self._entity_config[CONF_CARD]
        }

    @asyncio.coroutine
    def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        _LOGGER.debug("received turn on request for " + self.entity_id)
        self._state = True
        yield from self.async_update_ha_state()

    @asyncio.coroutine
    def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        _LOGGER.debug("received turn on request for " + self.entity_id)
        self._state = False
        yield from self.async_update_ha_state()


class SwitcherSlider(Entity):
    """Representation of the input_number entity"""
    def __init__(self, hass, slug_id, name, initial, minimum, maximum, step, icon, unit, mode, entity_config):
        """Initialize an input number."""
        self.hass = hass
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, slug_id, hass=hass)
        self._entity_config = entity_config
        self._name = name
        self._current_value = initial
        self._minimum = minimum
        self._maximum = maximum
        self._step = step
        self._icon = icon
        self._unit = unit
        self._mode = mode

        self.hass.bus.async_listen(EVENT_CALL_SERVICE, self.async_service_call_event)

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def should_poll(self):
        """No polling needed"""
        return True

    @property
    def name(self):
        """Return the name of the entity"""
        return self._name

    @property
    def icon(self):
        """Return the mdi icon"""
        return self._entity_config[CONF_ICON]

    @property
    def state(self):
        """Return the state of the entity"""
        return self._current_value

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in"""
        return self._unit

    @property
    def state_attributes(self):
        """Return the state attributes"""
        return {
            ATTR_MIN: self._minimum,
            ATTR_MAX: self._maximum,
            ATTR_STEP: self._step,
            ATTR_MODE: self._mode,
            CONF_STATE_CARD: self._entity_config[CONF_CARD]
        }

    @asyncio.coroutine
    def async_service_call_event(self, event):
        """Handle all service calls"""
        if (event.data["service_data"] is not None and event.data["domain"] == INPUT_NUMBER_DOMAIN and event.data["service"] == SERVICE_SET_VALUE and event.data["service_data"]["entity_id"] == self.entity_id):
            yield from self.async_set_value(event.data["service_data"]["value"])

    @asyncio.coroutine
    def async_set_value(self, value):
        """Set new value"""
        num_value = float(value)
        if num_value < self._minimum or num_value > self._maximum:
            _LOGGER.warning("Invalid value: %s (range %s - %s)",
                            num_value, self._minimum, self._maximum)
            return
        self._current_value = num_value
        yield from self.async_update_ha_state()


class SwitcherScript(ToggleEntity):
    """Representation of the script entity."""
    def __init__(self, hass, slug_id, name, sequence, entity_config):
        """Initialize the script."""
        self.hass = hass
        self.entity_id = ENTITY_ID_FORMAT.format(slug_id)
        self.script = Script(hass, sequence, name, self.async_update_ha_state)
        self._entity_config = entity_config

        self.hass.bus.async_listen(EVENT_CALL_SERVICE, self.async_service_call_event)

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def name(self):
        """Return the name of the entity."""
        return self.script.name

    @property
    def icon(self):
        """Return the mdi icon"""
        return self._entity_config[CONF_ICON]

    @property
    def state_attributes(self):
        """Return the state attributes"""
        attrs = {}
        attrs[ATTR_LAST_TRIGGERED] = self.script.last_triggered
        if self.script.can_cancel:
            attrs[ATTR_CAN_CANCEL] = self.script.can_cancel
        if self.script.last_action:
            attrs[ATTR_LAST_ACTION] = self.script.last_action
        attrs[CONF_STATE_CARD] = self._entity_config[CONF_CARD]
        return attrs

    @property
    def is_on(self):
        """Return true if script is on."""
        return self.script.is_running

    @asyncio.coroutine
    def async_service_call_event(self, event):
        """Handle all service calls"""
        if (event.data["service_data"] is not None and event.data["domain"] == SCRIPT_DOMAIN and "entity_id" in event.data["service_data"] and event.data["service_data"]["entity_id"] == self.entity_id):
            if event.data["service"] == SERVICE_TURN_ON:
                yield from self.async_turn_on()
            elif event.data["service"] == SERVICE_TURN_OFF:
                yield from self.async_turn_off()

    @asyncio.coroutine
    def async_turn_on(self, **kwargs):
        """Turn the script on."""
        yield from self.script.async_run()

    @asyncio.coroutine
    def async_turn_off(self, **kwargs):
        """Turn the script off."""
        self.script.async_stop()


class SwitcherSelect(RestoreEntity):
    """Representation of the input_select entity"""
    def __init__(self, hass, slug_id, name, options, entity_config, initial=None):
        """Initialize a select input."""
        self.entity_id = ENTITY_ID_FORMAT.format(slug_id)
        self._entity_config = entity_config
        self.hass = hass
        self._name = name
        self._options = options
        self._current_option = None

        self.hass.bus.async_listen(EVENT_CALL_SERVICE, self.async_service_call_event)
        if self._entity_config[CONF_TYPE] == ENTITY_NOTIFICATION_SELECT_TYPE:
            self.hass.bus.async_listen(EVENT_SERVICE_REGISTERED, self.async_check_notify_service)

        if initial is None:
            self.hass.async_add_job(self.async_get_last_state_from_hass)
        else:
            self._current_option = initial

    async def async_get_last_state_from_hass(self):
        """get_last_state_from_hass"""
        state = await self.async_get_last_state()
        if not state:
            self._current_option = self._options[0]
        else:
            self._current_option = state.state

    @property
    def hidden(self):
        """return hidden if no options available"""
        if len(self._options) > 1:
            return False

        return True

    @property
    def should_poll(self):
        """No polling needed"""
        return False

    @property
    def name(self):
        """Return the name of the entity"""
        return self._name

    @property
    def icon(self):
        """Return the mdi icon"""
        return self._entity_config[CONF_ICON]

    @property
    def state(self):
        """Return the state of the entity"""
        return self._current_option

    @property
    def state_attributes(self):
        """Return the state attributes"""
        return {
            ATTR_OPTIONS: self._options,
            CONF_STATE_CARD: self._entity_config[CONF_CARD]
        }

    @asyncio.coroutine
    def async_service_call_event(self, event):
        """Handle all service calls"""
        if (event.data["service_data"] is not None and event.data["domain"] == INPUT_SELECT_DOMAIN and event.data["service_data"]["entity_id"] == self.entity_id):
            if event.data["service"] == SERVICE_SELECT_OPTION:
                yield from self.async_select_option(event.data["service_data"]["option"])
            elif event.data["service"] == SERVICE_SELECT_NEXT:
                yield from self.async_offset_index(1)
            elif event.data["service"] == SERVICE_SELECT_PREVIOUS:
                yield from self.async_offset_index(-1)

    @asyncio.coroutine
    def async_check_notify_service(self, event):
        """Add new notify services to options list"""
        if event.data["domain"] == NOTIFY_DOMAIN and not event.data["service"] == NOTIFY_DOMAIN:
            self._options.append(event.data["service"])
            yield from self.async_update_ha_state()

    @asyncio.coroutine
    def async_select_option(self, option):
        """Select new option"""
        if option not in self._options:
            _LOGGER.warning('Invalid option: %s (possible options: %s)',
                            option, ', '.join(self._options))
            return
        self._current_option = option
        yield from self.async_update_ha_state()

    @asyncio.coroutine
    def async_offset_index(self, offset):
        """Offset current index"""
        current_index = self._options.index(self._current_option)
        new_index = (current_index + offset) % len(self._options)
        self._current_option = self._options[new_index]
        yield from self.async_update_ha_state()


class SwitcherText(Entity):
    """Representation of the input_text entity"""
    def __init__(self, hass, slug_id, name, initial, minimum, maximum, unit, mode, entity_config):
        """Initialize a text input."""
        self.hass = hass
        self.entity_id = ENTITY_ID_FORMAT.format(slug_id)
        self._name = name
        self._entity_config = entity_config
        self._current_value = initial
        self._minimum = minimum
        self._maximum = maximum
        self._unit = unit
        self._pattern = None
        self._mode = mode

        self.hass.bus.async_listen(EVENT_CALL_SERVICE, self.async_service_call_event)

    @property
    def should_poll(self):
        """No polling needed"""
        return False

    @property
    def name(self):
        """Return the name of the entity"""
        return self._name

    @property
    def icon(self):
        """Return the mdi icon"""
        return self._entity_config[CONF_ICON]

    @property
    def state(self):
        """Return the state of the entity"""
        return self._current_value

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in"""
        return self._unit

    @property
    def state_attributes(self):
        """Return the state attributes"""
        return {
            ATTR_MIN: self._minimum,
            ATTR_MAX: self._maximum,
            ATTR_PATTERN: self._pattern,
            ATTR_MODE: self._mode,
            CONF_STATE_CARD: self._entity_config[CONF_CARD]
        }

    @asyncio.coroutine
    def async_service_call_event(self, event):
        """Handle all service calls"""
        if (event.data["service_data"] is not None and event.data["domain"] == INPUT_TEXT_DOMAIN and event.data["service"] == SERVICE_SET_VALUE and event.data["service_data"]["entity_id"] == self.entity_id):
            yield from self.async_set_value(event.data["service_data"]["value"])

    @asyncio.coroutine
    def async_set_value(self, value):
        """Select new value."""
        if len(value) < self._minimum or len(value) > self._maximum:
            _LOGGER.warning("Invalid value: %s (length range %s - %s)",
                            value, self._minimum, self._maximum)
            return
        self._current_value = value
        yield from self.async_update_ha_state()


class SwitcherScheduleSensor(Entity):
    """Representation of the sensor switch"""
    def __init__(self, hass, slug_id, name, schedule_id, entity_config):
        """Initialize the sensor."""
        self.hass = hass
        self._entity_config = entity_config
        self._schedule_id = schedule_id
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, slug_id, hass=hass)
        self._name = name
        self._configured = False
        self._schedule_details = None
        self._next_run = None

    def as_dict(self):
        """Callback for __dict__."""
        return self.__dict__

    @property
    def name(self):
        """Return the name of the sensor"""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor"""
        if not self._configured:
            return ATTR_NOT_CONFIGURED
        elif not self._schedule_details.enabled:
            return ATTR_NOT_ENABLED
        else:
            return self._next_run

    @property
    def should_poll(self):
        """no polling needed."""
        return False

    @property
    def icon(self):
        """Return mdi icon"""
        return self._entity_config[CONF_ICON]

    @property
    def schedule_id(self):
        """Return the schedule id"""
        return self._schedule_id

    @property
    def state_attributes(self):
        """Return the state attributes"""
        attributes = {}
        attributes[CONF_STATE_CARD] = self._entity_config[CONF_CARD]
        if self._configured:
            attributes[CONF_ENABLED] = self._schedule_details.enabled
            attributes[CONF_RECURRING] = self._schedule_details.recurring
            attributes[CONF_START_TIME] = self._schedule_details.start_time
            attributes[CONF_END_TIME] = self._schedule_details.end_time
            attributes[CONF_DURATION] = self._schedule_details.duration
            if self._schedule_details.recurring:
                attributes[CONF_DAYS] = self._schedule_details.days

        return attributes

    @asyncio.coroutine
    def async_deconfigure(self):
        """Deconfigure deleted schedules"""
        if self._configured:
            _LOGGER.debug("received deconfiguring request for " + self.entity_id)
            self._configured = False
            self._next_run = None
            self._schedule_details = None
            yield from self.async_update_ha_state()

    @asyncio.coroutine
    def async_enable(self, device):
        """Enable the schedule"""
        _LOGGER.debug("received enable request for " + self.entity_id)
        if self._schedule_details.enabled:
            _LOGGER.warning("schedule " + self._schedule_id + " is already enabled")
        else:
            schedule_data = self._schedule_details.schedule_data[0:2] + ENABLE_SCHEDULE + self._schedule_details.schedule_data[4:]
            successful = yield from  async_disable_enable_schedule(device.ip, device.phone_id, device.device_id, device.device_password, schedule_data)
            if successful:
                self._schedule_details.set_enabled(True)
                self._schedule_details.set_schedule_data(schedule_data)
                self._next_run = self.get_next_run()
                yield from self.async_update_ha_state()
                _LOGGER.debug("successfully enabled schedule " + self._schedule_id)
            else:
                _LOGGER.error("failed to enable schedule " + self._schedule_id)

    @asyncio.coroutine
    def async_disable(self, device):
        """disable the schedule"""
        _LOGGER.debug("received disable request for " + self.entity_id)
        if not self._schedule_details.enabled:
            _LOGGER.warning("schedule " + self._schedule_id + " is already disabled")
        else:
            schedule_data = self._schedule_details.schedule_data[0:2] + DISABLE_SCHEDULE + self._schedule_details.schedule_data[4:]
            successful = yield from  async_disable_enable_schedule(device.ip, device.phone_id, device.device_id, device.device_password, schedule_data)
            if successful:
                self._schedule_details.set_enabled(False)
                self._schedule_details.set_schedule_data(schedule_data)
                yield from self.async_update_ha_state()
                _LOGGER.debug("successfully enabled schedule " + self._schedule_id)
            else:
                _LOGGER.error("failed to disable schedule " + self._schedule_id)

    @asyncio.coroutine
    def async_delete(self, device):
        """Delete the schedule"""
        _LOGGER.debug("received delete request for " + self.entity_id)
        if not self._configured:
            _LOGGER.warning("schedule " + self._schedule_id + " is not configured")
        else:
            successful = yield from  async_delete_schedule(device.ip, device.phone_id, device.device_id, device.device_password, self._schedule_id)
            if successful:
                yield from self.async_deconfigure()
                _LOGGER.debug("successfully deleted schedule " + self._schedule_id)
            else:
                _LOGGER.error("failed to delete schedule " + self._schedule_id)

    @asyncio.coroutine
    def async_update_received(self, schedule_details):
        """Update the device's state and attributes upon device update"""
        _LOGGER.debug('received update for ' + self.entity_id)
        self._configured = True
        self._schedule_details = schedule_details
        if self._schedule_details.enabled:
            self._next_run = self.get_next_run()
        else:
            self._next_run = None
        yield from self.async_update_ha_state()

    @callback
    def get_next_run(self):
        """Calculate the next runtime of the schedule"""
        if self._schedule_details.recurring:
            today_datetime = datetime.datetime.now()
            
            start_time = datetime.datetime.strptime(self._schedule_details.start_time, "%H:%M")
            current_time = datetime.datetime.strptime(("0" + str(today_datetime.hour))[-2:] + ":" + ("0" + str(today_datetime.minute))[-2:], "%H:%M")

            current_weekday = today_datetime.weekday()
            found_day = None
            if self._schedule_details.days == ALL_DAYS:
                if current_time < start_time:
                    return "Due today at " + self._schedule_details.start_time
                else:
                    return "Due tommorow at " + self._schedule_details.start_time

            for day in self._schedule_details.days:
                set_weekday = WEEKDAY_TUP.index(day)
                
                if set_weekday == current_weekday and current_time < start_time:
                    return "Due today at " + self._schedule_details.start_time
                
                if found_day is None or found_day > set_weekday:
                    found_day = set_weekday

            if found_day - 1 == current_weekday or (found_day == WEEKDAY_TUP.index(MONDAY) and current_weekday == WEEKDAY_TUP.index(SUNDAY)):
                return "Due tommorow at " + self._schedule_details.start_time

            return "Due next " + WEEKDAY_TUP[found_day] + " at " + self._schedule_details.start_time

        return "Due today at " + self._schedule_details.start_time