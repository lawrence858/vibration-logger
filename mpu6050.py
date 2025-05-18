import math
import time
from uarray import array

# MPU6050 registers
ACCEL_XOUT_H = 0x3B
PWR_MGMT_1 = 0x6B


def stdev(values):
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    sum_squared_diff = sum((x - mean) ** 2 for x in values)
    std = (sum_squared_diff / (len(values) - 1)) ** 0.5
    return std


def magnitude(vx, vy, vz):
    return math.sqrt(vx * vx + vy * vy + vz * vz)


class MPU6050:
    def __init__(self, i2c, addr):
        self.i2c = i2c
        self.addr = addr
        self.index = 0

        # Wake up the MPU6050
        self.i2c.writeto_mem(self.addr, PWR_MGMT_1, bytes([0]))
        time.sleep_ms(50)

    def get_accel_data(self):
        """Get accelerometer data"""
        raw_data = self.i2c.readfrom_mem(self.addr, ACCEL_XOUT_H, 6)

        # Convert the data
        ax = (raw_data[0] << 8 | raw_data[1])
        if ax > 32767:
            ax -= 65536

        ay = (raw_data[2] << 8 | raw_data[3])
        if ay > 32767:
            ay -= 65536

        az = (raw_data[4] << 8 | raw_data[5])
        if az > 32767:
            az -= 65536

        # Convert to g (standard gravity)
        ax = ax / 16384.0
        ay = ay / 16384.0
        az = az / 16384.0

        return ax, ay, az

    def get_accel_and_vibration_magnitude(self, reps=10, dt=2):
        ax, ay, az = 0, 0, 0

        axs = array('f', [0.0] * reps)
        ays = array('f', [0.0] * reps)
        azs = array('f', [0.0] * reps)
        for i in range(reps):
            ax, ay, az = self.get_accel_data()
            axs[i] = ax
            ays[i] = ay
            azs[i] = az
            if i < reps - 1:
                time.sleep_ms(dt)

        ax_std = stdev(axs)
        ay_std = stdev(ays)
        az_std = stdev(azs)

        std_mag = magnitude(ax_std, ay_std, az_std)
        return ax, ay, az, std_mag
