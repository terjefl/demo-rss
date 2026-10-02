#!/bin/bash

# Start logging in background
tail -f /var/log/demorss.log &

echo "Installing crontab..."
crontab -r
crontab /etc/cron.d/demorss-crontab
cat /etc/cron.d/demorss-crontab

echo "Starting cron service..."
cron

echo "Starting server..."
demorss serve "$@"
