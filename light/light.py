import asyncio
from bleak import BleakClient
import lgpio

# BLE settings
PICO_MAC = "2C:CF:67:B0:BF:19"
SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"  # Service UUID
RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # RX Characteristic UUID

# GPIO settings
FOOT_SWITCH_PIN = 14  # GPIO pin for the foot switch
CHIP_HANDLE = lgpio.gpiochip_open(0)  # Open the GPIO chip (chip 0)

# Configure GPIO pin as input with pull-up
lgpio.gpio_claim_input(CHIP_HANDLE, FOOT_SWITCH_PIN)

async def control_headlight():
    async with BleakClient(PICO_MAC) as client:
        print("Connected to Pico W")
        last_state = lgpio.gpio_read(CHIP_HANDLE, FOOT_SWITCH_PIN)

        while True:
            current_state = lgpio.gpio_read(CHIP_HANDLE, FOOT_SWITCH_PIN)
            if current_state != last_state:
                if current_state == 0:  # Foot switch pressed
                    await client.write_gatt_char(RX_CHAR_UUID, b"on")
                    print("Sent: on")
                else:  # Foot switch released
                    await client.write_gatt_char(RX_CHAR_UUID, b"off")
                    print("Sent: off")
                last_state = current_state

            await asyncio.sleep(0.1)

try:
    # Run the BLE control loop
    asyncio.run(control_headlight())
finally:
    lgpio.gpiochip_close(CHIP_HANDLE)  # Ensure GPIO is released
