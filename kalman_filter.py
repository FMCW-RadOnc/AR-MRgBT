"""
This is a Kalman filter class, which should help stabilize position data. Input should
just be x, y, and z position. Output should be stablized x, y, and z position. Internally,
we also keep track of velocities and accelerations for each axis.

"""

import numpy as np
from typing import Tuple
import time

MAX_DIST_DIFF = 200 # Maximum speed in mm per second allowed between updates. Anything higher results in the newest measurement being ignored. 5000 mm/s ~ 0.44 m/h

class KalmanFilter:

    """
    x_k = Fx_(k-1) + Bu_k + w_k
    F is the state transition model
    B is the control input model
    w_k is process noise with covariance Q
    
    z_k = Hx_k + v_k
    H is the observation model (true state space to observed space)
    v_k is observation noise with covariance R

    In this case, we are working with a needle with no explicit control input, so B is not relevant.
    F is just the identify matrix. 

    Because we want to internally use velocities and accelerations for each axis, the observation model becomes

    H = [
            [1  dt  0.5dt^2 0   0   0           0   0   0   ],
            [0  0   0       1   dt  0.5dt^2 0   0   0       ],
            [0  0   0       0   0   0       1   dt   0.5dt^2]
    ]

    """

    def __init__(self, process_noise_coef : float, observation_noise_coef : float):
        #self.state_estimate = np.zeros((9,1))
        #self.covariance = np.identity(9)
        self.state_estimate = None
        self.covariance = None
        self.Q = np.identity(9) * process_noise_coef # TODO: Placeholder for now
        self.R = np.identity(3) * observation_noise_coef # TODO: Placeholder for now, we trust predictions more
        self.prev_time = time.perf_counter()

    def update(self, x : float, y : float, z : float):
        

        # For the start, we trust our first measurement
        if self.state_estimate is None:
            self.state_estimate = np.array([x,0,0,y,0,0,z,0,0]).reshape(-1,1)
            self.covariance = np.identity(9) * 0.1
            return

        t = time.perf_counter() 
        dt = t - self.prev_time
        #dt = 0.2
        

        # Quick sanity check. If the new measurement is too far away from the previous one, ignore it entirely.
        prev_loc = self.state_estimate[::3].flatten()
        new_loc = np.array([x,y,z])
        dist = np.linalg.norm(prev_loc - new_loc)
        #print(prev_loc)
        #print(new_loc)
        #print(dist)
        #print(dist, MAX_DIST_DIFF * dt, dt)
        if dist > (MAX_DIST_DIFF * dt):
            return

        self.prev_time = t

        H = np.array([
            [1, dt, dt*dt*0.5, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, dt, dt*dt*0.5, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 1, dt, dt*dt*0.5]
        ])
         

        # PREDICT (trivial in this case)
        pred_x = self.state_estimate
        pred_covariance = self.covariance + self.Q

        # UPDATE
        z = np.array([x,y,z]).reshape(-1,1)
        innovation = z - H @ pred_x 
        innovation_cov = H @ pred_covariance @ H.T + self.R
        kalman_gain = pred_covariance @ H.T @ np.linalg.inv(innovation_cov)
        #print(kalman_gain)
        self.state_estimate = pred_x + kalman_gain @ innovation
        self.covariance = (np.identity(9) - kalman_gain @ H) @ pred_covariance

    def get(self) -> Tuple[float,float,float]:
        return (self.state_estimate[0].item(), self.state_estimate[3].item(), self.state_estimate[6].item())
    
