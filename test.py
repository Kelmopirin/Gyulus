import pyautogui
import time
time.sleep(5)
t=0
while True:
    pyautogui.click()
    time.sleep(60)
    t += 1
    if t > 10:
        break
pyautogui.alert("Finished clicking!")