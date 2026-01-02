import numpy as np
import matplotlib.pyplot as plt
from kalman_filter import KalmanFilter
import time

total_time_steps = 800
dt = 0.001

clean_data = np.linspace((1,4,10), (100,5,10), total_time_steps)
gaussian_noise = np.random.normal(loc = 0, scale = 0.5, size = (total_time_steps,3))

"""
Possible option for dealing with erratic noise could be to keep track of a running average of the last
N measurements and see if the current measurement is too far from it. If it is too far, don't forward that 
measurement to any process other than the running average.

Another option could simply be to ignore measurements that are too far away from the previous valid measurement.
The only way a quick change in position could plausibly happen would be if the user rapidly moves the needle around,
which would be a bad idea.

"""
erratic_noise = np.zeros((total_time_steps,3))
for i in range(total_time_steps):
    if np.random.random() < 0.1:
        erratic_noise[i] += np.random.normal(loc = 0, scale = 50, size = 3)

real_data = clean_data + gaussian_noise + erratic_noise

k = KalmanFilter(5, 25) # These coefficients are what should be tuned
kalman_data_x = np.zeros(total_time_steps)
real_data_x = np.zeros(total_time_steps)
x = np.zeros(total_time_steps)
curr_x = 0
for i in range(total_time_steps):
    time.sleep(dt)
    k.update(real_data[i,0], real_data[i,1], real_data[i,2])
    k_data = k.get()
    kalman_data_x[i] = k_data[0]
    real_data_x[i] = real_data[i,0]
    curr_x += dt
    x[i] = curr_x

plt.plot(x, real_data_x)
plt.plot(x, kalman_data_x, '-.')
plt.show()