# vibration-logger

Use an accelerometer connected to an ESP32 to track how often motors activate

## setup

In addition to the files included here you'll need to place a `config.json` file on your MicroPython device with this
format:

```json
{
  "wifi_ssid": "your-wifi-ssid",
  "wifi_password": "your-wifi-password",
  "timezone": "America/Los_Angeles",
  "service_url": "https://google-sheet-or-proxy-url/"
}
```

Non-essential dependencies that you can find elsewhere or remove from the code:

* bmp280 - for logging the temperature
* ble_module - for broadcasting staus over bluetooth