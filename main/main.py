import bluetooth
from machine import Pin, Timer

# Setup GPIO for headlight control
headlight = Pin(10, Pin.OUT)  # GPIO 10 controls the headlight
headlight.off()  # Default state: Headlight OFF

# Setup onboard LED for BLE status indication
led = Pin("LED", Pin.OUT)
led_timer = Timer()  # Timer for blinking LED

# Initialize BLE
bt = bluetooth.BLE()
bt.active(True)

# UUIDs for BLE service and characteristics
_UART_UUID = bluetooth.UUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
_UART_RX = bluetooth.UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e")  # Write characteristic

_UART_SERVICE = (
    _UART_UUID,
    ((_UART_RX, bluetooth.FLAG_WRITE),),
)

services = (_UART_SERVICE,)
handles = bt.gatts_register_services(services)
rx_handle = handles[0][0]  # Handle for RX characteristic

# Event handler for BLE
def on_ble_event(event, data):
    if event == 1:  # Client connected
        print("Device connected")
        led_timer.deinit()  # Stop blinking
        led.on()  # Stable LED when connected
    elif event == 2:  # Client disconnected
        print("Device disconnected")
        start_advertising()  # Restart advertising
    elif event == 3:  # Write to RX characteristic
        received = bt.gatts_read(rx_handle).decode().strip()
        print("Received command:", received)

        if received == "on":
            headlight.on()
            print("Headlight turned ON")
        elif received == "off":
            headlight.off()
            print("Headlight turned OFF")
        else:
            print("Invalid command received")

bt.irq(on_ble_event)

# Advertising payload
def advertising_payload(name):
    _ADV_FLAGS = 0x01
    _ADV_NAME = 0x09
    return bytes([
        2, _ADV_FLAGS, 0x06,
        len(name) + 1, _ADV_NAME
    ]) + name.encode()

# Start advertising with blinking LED
def start_advertising():
    def blink_led(timer):
        led.toggle()  # Blink the LED

    led_timer.init(period=500, mode=Timer.PERIODIC, callback=blink_led)  # Blink every 500ms
    bt.gap_advertise(100, advertising_payload("PicoW-Headlight"))
    print("Advertising as: PicoW-Headlight")

# Initial advertising
start_advertising()

# Keep the script running
while True:
    pass
