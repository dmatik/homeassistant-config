#!/bin/bash
curl -LsI -o /dev/null -w %{url_effective} https://github.com/Koenkk/zigbee2mqtt/releases/latest | cut -d\" -f2 | rev | cut -d/ -f1 | rev 2>/config/zigbee2mqtt_version.err