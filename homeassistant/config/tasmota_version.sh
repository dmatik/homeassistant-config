#!/bin/bash
curl -LsI -o /dev/null -w %{url_effective} https://github.com/arendst/Tasmota/releases/latest | cut -d\" -f2 | rev | cut -d/ -f1 | rev 2>/config/tasmota_version.err