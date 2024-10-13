from enum import Enum
import json
import queue
import struct
import threading
import time
from websockets.sync import client as ws_client
import socket
from zeroconf import Zeroconf, ServiceInfo


class DataType(Enum):
    INT = 0
    FLOAT = 1
    BOOL = 2


class OpType(Enum):
    SET_OFFSET = 0
    SET_AUTO_AVOIDANCE = 1
    SET_MOTOR_MONITOR = 2
    FORWARD = 3
    BACKWARD = 4
    TURN_LEFT = 5
    TURN_RIGHT = 6
    STAND = 7
    CONTINUE = 8


class HostOpType(Enum):
    SERVO_ANGLE = 0
    TRIGGER_OBSTACLE = 1


class SentryServer:
    ws_command: ws_client.ClientConnection = None
    tcp_sock: socket.socket = None
    zeroconf: Zeroconf = None
    response_listen_thread: threading.Thread = None
    stop_event: threading.Event = None

    def __init__(self, ws_command: str):
        self.stop_event = threading.Event()
        self.ws_command = ws_client.connect(ws_command)
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.settimeout(1)
        self.zeroconf = Zeroconf()
        self.discover_server()
        self.response_listen_thread = threading.Thread(
            target=self.response_listen,
            daemon=True
        )
        print("Connected to sentry")

    def __del__(self):
        self.quit()

    def discover_server(self):
        while True:
            info = self.zeroconf.get_service_info(
                "_driver._tcp.local.",
                "esp32-bot._driver._tcp.local."
            )
            if info and len(info.addresses) > 0:
                address = socket.inet_ntoa(info.addresses[0])
                port = info.port
                self.tcp_sock.connect((address, port))
                return
            time.sleep(1)

    def send_data(self, op_type: OpType, *data):
        packed_data = bytearray()
        header = struct.pack('II', op_type.value, len(data))
        packed_data.extend(header)

        for d in data:
            if isinstance(d, int):
                packed_data.extend(struct.pack('Ii', DataType.INT.value, d))
            elif isinstance(d, float):
                packed_data.extend(struct.pack('If', DataType.FLOAT.value, d))
            elif isinstance(d, bool):
                packed_data.extend(struct.pack('I?', DataType.BOOL.value, d))
            else:
                return

        self.tcp_sock.send(packed_data)

    def set_offset(self, index: int, offset: int):
        self.send_data(OpType.SET_OFFSET, index, offset)

    def set_auto_avoidance(self, enable: bool):
        self.send_data(OpType.SET_AUTO_AVOIDANCE, enable)

    def send_forward(self, steps: int):
        self.send_data(OpType.FORWARD, steps)

    def send_backward(self, steps: int):
        self.send_data(OpType.BACKWARD, steps)

    def send_turn_left(self, steps: int):
        self.send_data(OpType.TURN_LEFT, steps)

    def send_turn_right(self, steps: int):
        self.send_data(OpType.TURN_RIGHT, steps)

    def send_stand(self):
        self.send_data(OpType.STAND)

    def set_monitor(self, enable: bool):
        self.send_data(OpType.SET_MOTOR_MONITOR, enable)

    def send_continue(self):
        self.send_data(OpType.CONTINUE)

    def response_listen(self):
        while not self.stop_event.is_set():
            try:
                op = HostOpType(struct.unpack('I', self.tcp_sock.recv(4))[0])
                print(f"Op: {op}")
                if op == HostOpType.SERVO_ANGLE:
                    servos = []
                    for _ in range(12):
                        servos.append(struct.unpack('I', self.tcp_sock.recv(4))[0])
                    self.ws_command.send(json.dumps(["servo", servos]))
                elif op == HostOpType.TRIGGER_OBSTACLE:
                    self.ws_command.send(json.dumps(["obstacle"]))
            except socket.timeout:
                pass
            except Exception as e:
                print(f"An error occurred: {e}")

    def main_loop(self):
        self.response_listen_thread.start()

        while not self.stop_event.is_set():
            try:
                event = self.ws_command.recv(timeout=1)
                event = json.loads(event)

                if not 1 <= len(event) <= 3:
                    continue

                match event[0]:
                    case "offset":
                        self.set_offset(event[1], event[2])
                    case "autoAvoidance":
                        self.set_auto_avoidance(event[1])
                    case "forward":
                        self.send_forward(event[1])
                    case "backward":
                        self.send_backward(event[1])
                    case "turnLeft":
                        self.send_turn_left(event[1])
                    case "turnRight":
                        self.send_turn_right(event[1])
                    case "stand":
                        self.send_stand()
                    case "monitor":
                        self.set_monitor(event[1])
                    case "continue":
                        self.send_continue()

            except TimeoutError:
                continue

    def quit(self):
        self.stop_event.set()
        if self.response_listen_thread and self.response_listen_thread.is_alive():
            self.response_listen_thread.join()
        self.tcp_sock.close()
        self.zeroconf.close()


if __name__ == "__main__":
    uuid = "bbd3bebc-2c61-4ae1-a9ce-bc4de8bf38d2"
    sentry = SentryServer(
        f"ws://10.29.105.201:8000/ws/client/{uuid}/command/",
    )
    sentry.main_loop()
