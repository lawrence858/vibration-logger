import gc
import time
import os
import _thread
import machine
from machine import Pin, I2C, WDT, Timer
from bmp280 import BMP280, BMP280_CASE_INDOOR
import ble_module
from mpu6050 import MPU6050
import json
from remote_sheet import RemoteSheet
import updater

__version__ = '0.9.1'

# configure pin numbers dynamically based on the device
(sysname, nodename, sys_release, sys_version, machine_info) = os.uname()

if 'esp32c3' in machine_info.lower():
    # assume xiao esp32c3 board
    ADC_PIN = 2
    SDA_PIN = 6
    SCL_PIN = 7
    LED_PIN = 20  # could attach an external LED
else:
    # assume xiao esp32c6 board
    ADC_PIN = 0
    SDA_PIN = 22
    SCL_PIN = 23
    LED_PIN = 15  # internal LED for XIAO ESP32-C6

MPU6050_ADDR = 0x69  # connect A0 to change the address from the default 0x68

SAMPLING_INTERVAL_MS = 200  # measuring the vibration takes up a big portion of this time
TEMPERATURE_INTERVAL_MS = 60_000  # wait this long between taking temperature/pressure samples
BLUETOOTH_INTERVAL_MS = 10_000  # wait this long between bluetooth updates
UPDATE_INTERVAL_MS = 15_000  # TODO: increase. check this often if there is new data to post
HEARTBEAT_INTERVAL_MS = 30 * 60_000  # TODO: increase
VIBRATIONS_TEMP_FILE = 'vibrations_log.txt'

# Global variables
last_log_line = '...'
last_data_line = '???'
temp_f = 0
mpu = None
last_recorded_timestamp = '2000-01-01T00:00:00'
timestamp_lock = _thread.allocate_lock()
settings_lock = _thread.allocate_lock()

led = None
remote = None
bmp = None
vibration_minimum_magnitude = 0
vibration_minimum_seconds = 0


def file_exists(filename):
    try:
        os.stat(filename)
        return True
    except OSError:
        return False


def iso8601_time():
    # Get the current time as a tuple (year, month, day, hour, minute, second, ...)
    t = time.localtime()
    # Format it as ISO 8601 (YYYY-MM-DDTHH:MM:SS)
    return '{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}'.format(
        t[0], t[1], t[2],  # Year, month, day
        t[3], t[4], t[5]  # Hour, minute, second
    )


def set_time_from_iso8601(iso_string):
    date_part, time_part = iso_string.split('T')
    year, month, day = date_part.split('-')
    hour, minute, second = time_part.split(':')
    year, month, day = int(year), int(month), int(day)
    hour, minute, second = int(hour), int(minute), int(second)
    datetime_tuple = (year, month, day, 0, hour, minute, second, 0)
    rtc = machine.RTC()
    rtc.datetime(datetime_tuple)
    return datetime_tuple


def log_vibration_stats(data, max_lines=25):
    log_line = json.dumps(data)
    filename = VIBRATIONS_TEMP_FILE

    # Create the file if it doesn't exist
    if filename not in os.listdir():
        with open(filename, 'w') as f:
            f.write(log_line + '\n')
        return log_line

    # Count lines in the file
    line_count = 0
    with open(filename, 'r') as f:
        for _ in f:
            line_count += 1

    # If under the limit, just append
    if line_count < max_lines:
        with open(filename, 'a') as f:
            f.write(log_line + '\n')
        return log_line

    # If over limit, create a new file with last (max_lines-1) lines
    temp_filename = filename + '.tmp'
    with open(filename, 'r') as old_file:
        with open(temp_filename, 'w') as new_file:
            # Skip initial lines we don't need
            for _ in range(line_count - (max_lines - 1)):
                next(old_file)
            # Copy the remaining lines
            for line in old_file:
                new_file.write(line)
            # Add the new line
            new_file.write(log_line + '\n')

    # Replace old file with new one
    os.remove(filename)
    os.rename(temp_filename, filename)

    return log_line


def read_vibration_stats(omit_until=None, max_lines=25):
    """
    Read a file containing JSON objects, one per line, and return an array of parsed objects.

    Args:
        omit_until (str): Optional ISO8601 timestamp. If provided, only include objects with
                          a timestamp greater than this value. Defaults to None.
        max_lines (int): Maximum number of lines to read from the file. Defaults to 100.

    Returns:
        list: Array of dictionary objects parsed from the file
    """
    filename = VIBRATIONS_TEMP_FILE
    results = []
    line_count = 0

    if file_exists(filename):
        try:
            with open(filename, 'r') as file:
                for line in file:
                    if not line.strip():
                        continue  # skip empty lines
                    try:
                        data = json.loads(line)
                        if omit_until and 'timestamp' in data:
                            if not data['timestamp'] > omit_until:
                                continue
                        results.append(data)
                        line_count += 1
                        if line_count >= max_lines:
                            break
                    except json.JSONDecodeError:
                        print_and_log(f'Could not parse: {line.strip()}')
        except Exception as e:
            print_and_log(f'Error reading file: {e}')

    return results, line_count


def log_with_timestamp(message, filename='log.txt'):
    if filename in os.listdir():
        file_size = os.stat(filename)[6]  # Get the file size in bytes
        if file_size > 100 * 1024:
            os.remove(filename)
    with open(filename, 'a') as f:
        timestamp = iso8601_time()
        log_line = f'{timestamp}: {message}'
        f.write(log_line + '\n')
    return log_line


def print_and_log(line, log_type='status'):
    # assume log_type is 'status', 'info', or 'data'
    # broadcast the last 'status' and last 'data' log over BLE
    # just print the 'info' line
    global last_log_line, last_data_line
    log_line = log_with_timestamp(line, 'log.txt')
    if log_type == 'status':
        last_log_line = log_line
    elif log_type != 'info':
        last_data_line = log_line
    print(f'>>>   {line}')


def read_temperature():
    global temp_f
    try:
        temp_c = bmp.temperature
        temp_f = temp_c * 9 / 5 + 32
    except Exception:
        temp_f = -459.67  # absolute zero
    return temp_f


def ble_advertise():
    try:
        ble_data = f'{last_log_line} :: {last_data_line}'
        print(f'BLE: {ble_data}')
        ble_module.write_and_notify(ble_data)
    except Exception as ble_e:
        print_and_log(f'Bluetooth notification error: {ble_e}')


def post_update_to_service(values):
    global last_recorded_timestamp, vibration_minimum_magnitude, vibration_minimum_seconds
    gc.collect()
    print(f'====== sending values over http: {len(values)}')
    result = remote.append_values(values)
    print(result)
    update_if_available(result.get('ota_version'), result.get('ota_url'))
    with timestamp_lock:
        if result.get('status') == 'success':
            if result.get('last_timestamp') > last_recorded_timestamp and result.get('last_timestamp').startswith('20'):  # Y2.1K bug ;-)
                last_recorded_timestamp = result.get('last_timestamp')
            else:
                last_recorded_timestamp = values[-1].get('timestamp', last_recorded_timestamp)
    with settings_lock:
        if 'vibration_minimum_magnitude' in result and 0 < result.get('vibration_minimum_magnitude') < 10:
            vibration_minimum_magnitude = result.get('vibration_minimum_magnitude')
        if 'vibration_minimum_seconds' in result and 0 < result.get('vibration_minimum_seconds') < 24 * 60 * 60:
            vibration_minimum_seconds = result.get('vibration_minimum_seconds')


def post_heartbeat_to_service(data):
    gc.collect()
    print(f'====== sending heartbeat over http: {json.dumps(data)}')
    result = remote.ping(data)
    print(result)
    update_if_available(result.get('ota_version'), result.get('ota_url'))
    if result.get('status') != 'success':
        print_and_log(f'ping not successful.')


def update_if_available(ota_version, ota_url):
    if ota_version and ota_url and ota_url.startswith('http'):
        try:
            if updater.install_update_if_available(__version__, ota_version, ota_url):
                print(f'Installed version {ota_version}. Rebooting.')
                time.sleep(3)
                machine.reset()
        except Exception as e:
            print_and_log(f'OTA update error: {e}')


def initialize():
    global led, remote, mpu, bmp, vibration_minimum_magnitude, vibration_minimum_seconds

    i2c = None
    print_and_log('Restarting.')

    # try the must-have initialization and reset if it fails
    try:
        led = Pin(LED_PIN, Pin.OUT)
        # TODO wdt = WDT(timeout=60 * 1000)  # 60 second timeout

        if not file_exists('config.json'):
            raise Exception('missing config.json')
        with open('config.json', 'r') as file:
            config = json.load(file)
        if 'wifi_ssid' not in config or 'wifi_password' not in config or 'service_url' not in config:
            raise ValueError('missing wifi_ssid or wifi_password in config.json')

        # get config values with defaults
        wifi_ssid = config.get('wifi_ssid')
        wifi_password = config.get('wifi_password')
        service_url = config.get('service_url')

        remote = RemoteSheet(wifi_ssid, wifi_password, service_url, print_and_log)
        i2c = I2C(0, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN))
        connected_i2c_devices = i2c.scan()
        if MPU6050_ADDR not in connected_i2c_devices:
            raise Exception('MPU6050 not found')
        mpu = MPU6050(i2c, MPU6050_ADDR)

        init_response = remote.initialize(config.get('timezone', 'America/Los_Angeles'), __version__)
        update_if_available(init_response.get('ota_version'), init_response.get('ota_url'))
        if init_response.get('status') == 'error' or 'current_time' not in init_response:
            raise Exception(init_response.get('message', 'time setting error'))
        set_time_from_iso8601(init_response.get('current_time'))
        vibration_minimum_magnitude = init_response.get('vibration_minimum_magnitude', 0.08)
        vibration_minimum_seconds = init_response.get('vibration_minimum_seconds', 9)
        print(time.localtime(), vibration_minimum_magnitude, vibration_minimum_seconds)

    except Exception as e:
        print_and_log(f'Critical init error: {e}')
        time.sleep(20)
        machine.reset()

    # try the nice-to-have initialization
    try:
        time.sleep_ms(200)
        ble_module.start_advertising()

        bmp = BMP280(i2c)
        bmp.use_case(BMP280_CASE_INDOOR)
    except Exception as e:
        print_and_log(f'Secondary init error: {e}')

    print_and_log('Initialized.')


def main_loop():
    global temp_f

    temperature_sample_time = -TEMPERATURE_INTERVAL_MS
    bluetooth_update_time = -BLUETOOTH_INTERVAL_MS
    last_update_check_time = 0
    last_post_time = 0
    is_vibrating, was_vibrating = False, False
    vibration_start_ticks = 0
    vibration_count = 0

    # the following two initial values only apply to the very first cycle - slight inaccuracy is okay.
    ave_vib_on = 0.1
    ave_vib_off = 0
    alpha = 0.01  # Weight for new readings
    # TODO: log max and min in on & off periods excluding first and last samples. use a queue.

    while True:
        try:
            with settings_lock:
                vib_min_magnitude = vibration_minimum_magnitude
                vib_min_seconds = vibration_minimum_seconds
            # TODO wdt.feed()
            sample_time = time.ticks_ms()
            _, _, _, vib = mpu.get_accel_and_vibration_magnitude(50, 2)
            is_vibrating = vib > vib_min_magnitude

            # Update the appropriate running average based on vibration state
            if is_vibrating:
                ave_vib_on = (1 - alpha) * ave_vib_on + alpha * vib
            else:
                ave_vib_off = (1 - alpha) * ave_vib_off + alpha * vib

            if is_vibrating != was_vibrating:
                if is_vibrating:
                    print(f'crossed {vib_min_magnitude} and waiting for {vib_min_seconds}')
                if is_vibrating:
                    vibration_start_ticks = sample_time
                    vibration_start_timestamp = iso8601_time()
                    ave_vib_on = vib  # Start with current reading for the new vibration period
                else:
                    vibration_duration_sec = time.ticks_diff(sample_time, vibration_start_ticks) / 1000
                    if vibration_duration_sec >= vib_min_seconds:
                        vibration_count += 1
                        print_and_log('count: {}, last vibration: {:.1f} seconds'.format(vibration_count, vibration_duration_sec), 'data')
                        log_vibration_stats({
                            'timestamp': vibration_start_timestamp,
                            'duration': '{:.1f}'.format(vibration_duration_sec),
                            'temperature': '{:.1f}'.format(temp_f),
                            'ave_vib_on': '{:.3f}'.format(ave_vib_on),
                            'ave_vib_off': '{:.3f}'.format(ave_vib_off),
                            'count': vibration_count,
                            'last_log_line': last_log_line,
                            'version': __version__
                        }, 25)
                    ave_vib_off = vib  # Start with current reading for the new non-vibration period

            led.value(not is_vibrating)  # use the LED to indicate we're getting vibrations. false is ON
            was_vibrating = is_vibrating

            if time.ticks_diff(sample_time, temperature_sample_time) > TEMPERATURE_INTERVAL_MS:
                temperature_sample_time = sample_time
                temp_f = read_temperature()

            if time.ticks_diff(sample_time, bluetooth_update_time) > BLUETOOTH_INTERVAL_MS:
                bluetooth_update_time = sample_time
                ble_advertise()

            if not is_vibrating and time.ticks_diff(sample_time, last_update_check_time) > UPDATE_INTERVAL_MS:
                last_update_check_time = sample_time
                with timestamp_lock:
                    omit_until = last_recorded_timestamp
                values, num_values = read_vibration_stats(omit_until, 15)
                if len(values) > 0:
                    print(f'sending {len(values)} values after {omit_until}')
                    last_post_time = sample_time
                    _thread.start_new_thread(post_update_to_service, (values,))
                else:
                    print('nothing new to log')

            if time.ticks_diff(sample_time, last_post_time) > HEARTBEAT_INTERVAL_MS:
                last_post_time = sample_time
                _thread.start_new_thread(
                    post_heartbeat_to_service, ({
                                                    'vib': '{:.3f}'.format(vib),
                                                    'is_vibrating': is_vibrating,
                                                    'temperature': '{:.1f}'.format(temp_f),
                                                    'ave_vib_on': '{:.3f}'.format(ave_vib_on),
                                                    'ave_vib_off': '{:.3f}'.format(ave_vib_off),
                                                    'count': vibration_count,
                                                    'version': __version__,
                                                    'last_log_line': last_log_line
                                                },))

            elapsed_time = time.ticks_diff(time.ticks_ms(), sample_time)
            sleep_duration = max(10, SAMPLING_INTERVAL_MS - elapsed_time)
            time.sleep_ms(sleep_duration)

        except Exception as e:
            print_and_log(f'Unexpected error: {e}')
            time.sleep(5)
            machine.reset()


if __name__ == '__main__':
    initialize()
    main_loop()
