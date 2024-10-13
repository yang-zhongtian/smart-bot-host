from cam import CamServer
from sentry import SentryServer
from threading import Thread, Event

uuid = "bbd3bebc-2c61-4ae1-a9ce-bc4de8bf38d2"
ws_endpoint = "ws://10.29.105.201:8000/ws/client"

cam = CamServer(
    f"{ws_endpoint}/{uuid}/cam/",
    f"{ws_endpoint}/{uuid}/analyze/"
)

sentry = SentryServer(
    f"{ws_endpoint}/{uuid}/command/",
)

cam_thread = Thread(target=cam.main_loop, daemon=True)
sentry_thread = Thread(target=sentry.main_loop, daemon=True)

if __name__ == "__main__":
    cam_thread.start()
    sentry_thread.start()
    input("Press Enter to quit\n")
    cam.quit()
    sentry.quit()
    cam_thread.join()
    sentry_thread.join()
