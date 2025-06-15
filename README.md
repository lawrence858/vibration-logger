# vibration-logger

Use an accelerometer connected to an ESP32 to track how often motors activate.

## Why is this useful?

There are many possible applications. 
In our case, we wanted to keep track of how much water is being used on a ranch that gets its water from a well.
There is a pressurized tank stores water that comes out of the well. 
As water is depleted from that tank, its pressure drops to 40 PSI, at which point the pump activates and adds water to the tank until its pressure reaches 60 PSI.
Based on measurements and the specs of the pressure tank, we know the (net) number gallons added while the pump was active.

## Setup for well water usage tracking

A small circuit board with an ESP32 running this code and an attached MP6050 accelerometer are paced on the water pump. 
In our use case the pump activates for 30 to 50 seconds a few dozen times per day. 
The program logs these activations and their durations to a Google sheet.
That information enables us to derive what we believe is a very good approximation for the amount of water that is being consumed.

There are more obvious ways to track water usage, but this technique has some advantages.
The obvious way would be to use a flow meter. 
The mechanical variety of flow meters is invasive and would require plumbing work and interruption of water on the ranch.
It's also susceptible to clogs and malfunctions from debris in the water.
The ultrasonic variety of flow meters is much more complicated and expensive, easily costing 50 times as much as the parts requred for this vibration-based solution.

## Configuration

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