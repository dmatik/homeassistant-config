#!/bin/bash

cd /volume1/docker/

sudo /usr/local/bin/docker-compose pull -q homeassistant

sudo /usr/local/bin/docker-compose up -d --quiet-pull homeassistant