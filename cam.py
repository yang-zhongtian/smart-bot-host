from enum import Enum
import json
import queue
import struct
import threading
import time
from websockets.sync import client as ws_client
import socket
from zeroconf import Zeroconf, ServiceInfo


class Command(Enum):
    TAKE_PICTURE = 0
    START_STREAM = 1
    STOP_STREAM = 2
    START_LED = 3
    STOP_LED = 4


class CamServer:
    ws_cam: ws_client.ClientConnection = None
    ws_analyze: ws_client.ClientConnection = None
    udp_sock: socket.socket = None
    tcp_sock: socket.socket = None
    zeroconf: Zeroconf = None
    service_info: ServiceInfo = None
    video_queue: queue.Queue = None

    video_listen_thread: threading.Thread = None
    video_publish_thread: threading.Thread = None
    stop_event: threading.Event = None

    def __init__(self, ws_cam: str, ws_analyze: str, socket_port: int = 9876):
        self.stop_event = threading.Event()
        self.ws_cam = ws_client.connect(ws_cam)
        self.ws_analyze = ws_client.connect(ws_analyze)
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp_sock.bind(('', socket_port))
        self.udp_sock.settimeout(1)
        self.tcp_sock.settimeout(1)
        self.zeroconf = Zeroconf()
        self.video_queue = queue.Queue()
        self.register_service(socket_port)
        self.discover_server()
        print("Connected to cam")

        self.video_listen_thread = threading.Thread(
            target=self.video_listen,
            daemon=True
        )
        self.video_publish_thread = threading.Thread(
            target=self.video_publish,
            daemon=True
        )

    def __del__(self):
        self.quit()

    def register_service(self, socket_port: int):
        self.service_info = ServiceInfo(
            "_video._udp.local.",
            "host._video._udp.local.",
            port=socket_port,
            server="host.local.",
            addresses=[socket.inet_aton("192.168.137.1")],
        )
        self.zeroconf.register_service(self.service_info, socket_port)

    def discover_server(self):
        while True:
            info = self.zeroconf.get_service_info(
                "_video._tcp.local.",
                "esp32-cam._video._tcp.local."
            )
            if info and len(info.addresses) > 0:
                address = socket.inet_ntoa(info.addresses[0])
                port = info.port
                self.tcp_sock.connect((address, port))
                return
            time.sleep(1)

    def send_command(self, command: Command):
        pack = struct.pack("I", command.value)
        self.tcp_sock.send(pack)

    def take_picture(self):
        self.send_command(Command.TAKE_PICTURE)
        head_size = struct.calcsize("II")
        data = self.tcp_sock.recv(head_size)
        _, frame_size = struct.unpack("II", data)

        frame = bytearray()
        while len(frame) < frame_size:
            packet = self.tcp_sock.recv(frame_size - len(frame))
            if not packet:
                break
            frame.extend(packet)

        self.ws_analyze.send(frame)

    def set_streaming(self, start: bool):
        if start:
            self.send_command(Command.START_STREAM)
        else:
            self.send_command(Command.STOP_STREAM)

    def set_led(self, start: bool):
        if start:
            self.send_command(Command.START_LED)
        else:
            self.send_command(Command.STOP_LED)

    def video_listen(self):
        head_size = struct.calcsize("II")
        while not self.stop_event.is_set():
            try:
                data = self.udp_sock.recv(head_size)
                _, frame_size = struct.unpack("II", data)

                buf = bytearray()
                chunk_size = 1024
                while len(buf) < frame_size:
                    packet = self.udp_sock.recv(
                        min(chunk_size, frame_size - len(buf))
                    )
                    buf.extend(packet)

                self.video_queue.put(buf)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error in video_listen: {e}")
                continue

    def video_publish(self):
        while not self.stop_event.is_set():
            try:
                frame = self.video_queue.get(timeout=1)
                self.ws_cam.send(frame)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in video_publish: {e}")
                break

    def main_loop(self):
        self.video_listen_thread.start()
        self.video_publish_thread.start()

        while not self.stop_event.is_set():
            try:
                event = self.ws_cam.recv(timeout=1)
                event = json.loads(event)

                if not 1 <= len(event) <= 2:
                    continue

                match event[0]:
                    case "videoStream":
                        self.set_streaming(event[1])
                    case "led":
                        self.set_led(event[1])
                    case "capture":
                        self.take_picture()

            except TimeoutError:
                continue

    def quit(self):
        self.stop_event.set()
        if self.video_listen_thread and self.video_listen_thread.is_alive():
            self.video_listen_thread.join()
        if self.video_publish_thread and self.video_publish_thread.is_alive():
            self.video_publish_thread.join()
        self.ws_cam.close()
        self.ws_analyze.close()
        self.zeroconf.close()
        self.udp_sock.close()


if __name__ == "__main__":
    uuid = "bbd3bebc-2c61-4ae1-a9ce-bc4de8bf38d2"
    cam = CamServer(
        f"ws://10.29.105.201:8000/ws/client/{uuid}/cam/",
        f"ws://10.29.105.201:8000/ws/client/{uuid}/analyze/"
    )
    cam.main_loop()
