import time
import network
import gc
import ujson
import urequests
import binascii

class RemoteSheet:
    def __init__(self, ssid, password, url, logger=None):
        self.ssid = ssid
        self.password = password
        self.url = url
        self.logger = logger if logger else print
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        # due to an apparent bug machine.unique_id() is not unique on the esp32c6.
        # use the MAC address instead.
        mac = self.wlan.config('mac')  # get the MAC address as bytes
        self.device_id = binascii.hexlify(mac).decode()

    def connect(self):
        if not self.wlan.isconnected():
            print(f"Attempting to connect to {self.ssid}...")
            connection_t0 = time.ticks_ms()
            self.wlan.connect(self.ssid, self.password)

            connection_wait = 0
            while connection_wait < 30_000:
                if self.wlan.isconnected():
                    break
                time.sleep(0.5)
                connection_wait = time.ticks_ms() - connection_t0

            if self.wlan.isconnected():
                self.logger(f"WiFi connected to channel {self.wlan.config('channel')} successfully after {connection_wait} ms, rssi = {self.wlan.status('rssi')}")
                print("Network config: " + str(self.wlan.ifconfig()))
                return True, connection_wait
            else:
                self.logger("WiFi connection failed")
                return False, connection_wait
        else:
            return True, 0

    def post(self, data):
        print('RemoteSheet post')
        response = None

        try:
            gc.collect()
            connected, connection_wait = self.connect()
            if connected:
                data['rssi'] = self.wlan.status('rssi')
                data['connection_wait'] = connection_wait
                post_data = ujson.dumps(data)
                response = urequests.post(
                    self.url,
                    headers={'content-type': 'application/json', 'user-agent': 'MicroPython/ESP32'},
                    data=post_data,
                    timeout=15  # 15 second timeout
                )
                if response is None:
                    return {}
                return response.json()
            else:
                return {
                    'status': 'error',
                    'message': f'could not connect to {self.ssid}'
                }
        except Exception as e:
            self.logger(f"post failed: {e}")
            if self.wlan.isconnected():
                # we might have better luck after reconnecting next time
                self.logger("disconnecting WiFi")
                self.wlan.disconnect()
            return {
                'status': 'error',
                'message': f'post failed: {e}'
            }
        finally:
            if response:
                response.close()

    def initialize(self, timezone, version):
        print('RemoteSheet initialize', self.device_id)
        return self.post({
            'op': 'init',
            'device_id': self.device_id,
            'version': version,
            'timezone': timezone
        })

    def append_values(self, values):
        return self.post({
            'op': 'append',
            'device_id': self.device_id,
            'values': values
        })

    def ping(self, data):
        return self.post({
            'op': 'ping',
            'device_id': self.device_id,
            'data': data
        })
