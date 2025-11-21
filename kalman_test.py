import numpy as np
import matplotlib.pyplot as plt
from kalman_filter import KalmanFilter
import time

total_time_steps = 800
dt = 0.01

clean_data = np.linspace((1,4,10), (25,5,10), total_time_steps)
gaussian_noise = np.random.normal(loc = 0, scale = 0.5, size = (total_time_steps,3))
erratic_noise = np.zeros((total_time_steps,3))
for i in range(total_time_steps):
    if np.random.random() < 0.05:
        erratic_noise[i] += np.random.normal(loc = 0, scale = 150, size = 3)

real_data = clean_data + gaussian_noise + erratic_noise

k = KalmanFilter(0.5, 1000)
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