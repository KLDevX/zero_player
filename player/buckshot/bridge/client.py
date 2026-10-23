"""Python side of the bridge: talk to bridge.gd inside the lab copy of the game over localhost."""
import json
import socket

PORT = 47800


class Bridge:
    def __init__(self, host: str = "127.0.0.1", port: int = PORT, timeout: float = 5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.file = self.sock.makefile("rw", encoding="utf-8", newline="\n")

    def _call(self, **msg) -> dict:
        self.file.write(json.dumps(msg) + "\n")
        self.file.flush()
        line = self.file.readline()
        if not line:
            raise ConnectionError("bridge closed the connection (game exited?)")
        return json.loads(line)

    def state(self) -> dict:
        """Scene name, public state (if at the table) and the list of legal action keys."""
        return self._call(cmd="state")

    def act(self, key: str) -> dict:
        return self._call(cmd="act", key=key)

    def speed(self, x: float) -> dict:
        return self._call(cmd="speed", x=x)

    def mute(self, on: bool = True) -> dict:
        return self._call(cmd="mute", on=on)

    def close(self) -> None:
        self.sock.close()
