import sys
import json
import time
import socket
import subprocess
import os
from urllib.parse import urlparse
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QListWidget, 
                             QLabel, QMessageBox, QGraphicsDropShadowEffect, QTextEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QColor


class PingWorker(QThread):
    ping_done = pyqtSignal(int, str)

    def __init__(self, row_index, address):
        super().__init__()
        self.row_index = row_index
        self.address = address

    def run(self):
        try:
            host = self.address
            if "://" in host:
                parsed = urlparse(host)
                host = parsed.netloc.split('@')[-1].split(':')[0] or parsed.netloc
            
            port = 443
            if ":" in host:
                host, port_str = host.split(":")
                try: port = int(port_str)
                except ValueError: pass

            start_time = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect((host, port))
            sock.close()
            
            ms = int((time.time() - start_time) * 1000)
            self.ping_done.emit(self.row_index, f"{ms} ms")
        except Exception:
            self.ping_done.emit(self.row_index, "Таймаут")


class VpnCoreManager:
    def __init__(self):
        self.process = None

    def generate_xray_config(self, url):
        """Парсит ссылку и создает базовый рабочий JSON для Xray-core."""
        try:
            parsed = urlparse(url)
            protocol = parsed.scheme.lower()
            
            user_info = parsed.username or ""
            host = parsed.hostname or ""
            port = parsed.port or 443
            
            # Поддержка кастомного happ:// протокола (подменяем на базовый vless для xray)
            if protocol == "happ":
                protocol = "vless"

            config = {
                "log": {"loglevel": "warning"},
                "inbounds": [
                    {
                        "port": 10808,
                        "protocol": "socks",
                        "settings": {"auth": "noauth", "udp": True}
                    },
                    {
                        "port": 10809,
                        "protocol": "http",
                        "settings": {"allowTransparent": False}
                    }
                ],
                "outbounds": [
                    {
                        "protocol": protocol,
                        "settings": {
                            "vnext": [{
                                "address": host,
                                "port": int(port),
                                "users": [{"id": user_info, "encryption": "none"}]
                            }]
                        },
                        "streamSettings": {
                            "network": "tcp",
                            "security": "none"
                        }
                    },
                    {
                        "protocol": "freedom",
                        "tag": "direct"
                    }
                ]
            }
            
            if protocol in ["trojan", "shadowsocks", "ss"]:
                config["outbounds"][0]["settings"] = {
                    "servers": [{
                        "address": host,
                        "port": int(port),
                        "password": user_info
                    }]
                }
                
            return config
        except Exception as e:
            print(f"Ошибка генерации конфига: {e}")
            return None

    def start_tunnel(self, config_url, log_callback):
        log_callback(f"[KSOFT] Подготовка конфигурации...")
        
        config_data = self.generate_xray_config(config_url)
        if not config_data:
            log_callback("[KSOFT] Ошибка: Не удалось распарсить ссылку.")
            return False
            
        try:
            with open("xray_config.json", "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=4)
        except Exception as e:
            log_callback(f"[KSOFT] Ошибка записи конфига: {e}")
            return False

        if not os.path.exists("xray.exe"):
            log_callback("[KSOFT] КРИТИЧЕСКАЯ ОШИБКА: Файл xray.exe не найден в папке с программой!")
            QMessageBox.critical(None, "Ошибка ядра", "Положите xray.exe в папку с приложением.")
            return False

        log_callback("[KSOFT] Запуск ядра Xray-core...")
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            self.process = subprocess.Popen(
                ["xray.exe", "run", "-c", "xray_config.json"],
                startupinfo=startupinfo,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8"
            )
            
            log_callback("[KSOFT] VPN Туннель поднят локально (Порт: 10809).")
            log_callback("[KSOFT] ВНИМАНИЕ: Включите системный прокси (127.0.0.1:10809) для обхода блокировок Ютуба.")
            return True
        except Exception as e:
            log_callback(f"[KSOFT] Не удалось запустить ядро: {e}")
            return False

    def stop_tunnel(self, log_callback):
        if self.process:
            log_callback("[KSOFT] Останавливаем ядро Xray...")
            self.process.terminate()
            self.process.wait()
            self.process = None
            
            if os.path.exists("xray_config.json"):
                try: os.remove("xray_config.json")
                except: pass
                
            log_callback("[KSOFT] VPN Туннель остановлен.")


class KSoftApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KSOFT by KOICH")
        self.setMinimumSize(700, 550)
        
        self.settings = QSettings("KSOFT_Corp", "KSOFT_VPN_Client")
        self.subscriptions = self.load_from_system()
        self.vpn_manager = VpnCoreManager()
        self.is_connected = False
        
        self.init_ui()
        self.apply_styles()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.title_label = QLabel("KSOFT")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(" Вставьте ссылку: happ://, vless://, ss://, trojan://...")
        self.add_btn = QPushButton("Добавить")
        self.add_btn.clicked.connect(self.add_subscription)
        input_layout.addWidget(self.url_input, stretch=4)
        input_layout.addWidget(self.add_btn, stretch=1)
        layout.addLayout(input_layout)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Системные логи KSOFT...")
        self.log_output.setMaximumHeight(100)
        layout.addWidget(self.log_output)

        control_layout = QHBoxLayout()
        
        self.connect_btn = QPushButton("ПОДКЛЮЧИТЬ")
        self.connect_btn.setObjectName("ConnectButton")
        self.connect_btn.clicked.connect(self.toggle_connection)
        
        self.ping_btn = QPushButton("Проверить Пинг")
        self.ping_btn.clicked.connect(self.ping_all)
        
        self.delete_btn = QPushButton("Удалить")
        self.delete_btn.setObjectName("DeleteButton")
        self.delete_btn.clicked.connect(self.delete_subscription)

        control_layout.addWidget(self.connect_btn, stretch=2)
        control_layout.addWidget(self.ping_btn, stretch=1)
        control_layout.addWidget(self.delete_btn, stretch=1)
        layout.addLayout(control_layout)

        self.refresh_list()
        self.log("[KSOFT] Клиент запущен и готов к работе.")

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #0d0f14; }
            QLabel {
                font-family: 'Segoe UI', Arial;
                font-size: 24px;
                font-weight: bold;
                color: #00ffaa;
                letter-spacing: 3px;
                padding: 10px;
            }
            QLineEdit {
                background-color: #161a24;
                border: 1px solid #222a3a;
                border-radius: 6px;
                color: #ffffff;
                font-size: 13px;
                padding: 10px;
            }
            QLineEdit:focus { border: 1px solid #00ffaa; }
            QListWidget {
                background-color: #161a24;
                border: 1px solid #222a3a;
                border-radius: 8px;
                color: #e0e6ed;
                font-size: 13px;
            }
            QListWidget::item {
                background-color: #1c2331;
                border-radius: 6px;
                margin: 5px 8px;
                padding: 12px;
            }
            QListWidget::item:selected {
                background-color: #00ffaa;
                color: #0d0f14;
                font-weight: bold;
            }
            QTextEdit {
                background-color: #090b0e;
                border: 1px solid #1c2331;
                border-radius: 6px;
                color: #8892b0;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
            QPushButton {
                background-color: #1c2331;
                color: #00ffaa;
                border: 1px solid #00ffaa;
                border-radius: 6px;
                font-family: 'Segoe UI';
                font-size: 13px;
                font-weight: bold;
                padding: 12px;
            }
            QPushButton:hover { background-color: #00ffaa; color: #0d0f14; }
            QPushButton#ConnectButton {
                background-color: #00ffaa;
                color: #0d0f14;
                font-size: 14px;
            }
            QPushButton#ConnectButton:hover { background-color: #00cc88; }
            QPushButton#DeleteButton {
                background-color: #2a1b24;
                color: #ff5577;
                border: 1px solid #ff5577;
            }
            QPushButton#DeleteButton:hover { background-color: #ff5577; color: #ffffff; }
        """)
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor("#00ffaa"))
        shadow.setOffset(0, 0)
        self.title_label.setGraphicsEffect(shadow)

    def log(self, text):
        self.log_output.append(text)

    def load_from_system(self):
        saved = self.settings.value("ksoft_subs", "")
        if saved:
            try: return json.loads(saved)
            except: return []
        return []

    def save_to_system(self):
        self.settings.setValue("ksoft_subs", json.dumps(self.subscriptions))

    def refresh_list(self):
        self.list_widget.clear()
        for sub in self.subscriptions:
            logo = "🔒" if sub['type'] == "HAPP" else "🌐"
            item_text = f" {logo}  [{sub['type'].upper()}]  {sub['url'][:50]}...   |   Ping: {sub.get('ping', 'N/A')}"
            self.list_widget.addItem(item_text)

    def add_subscription(self):
        url = self.url_input.text().strip()
        if not url: return
        
        sub_type = url.split("://")[0].upper() if "://" in url else "LINK"
        self.subscriptions.append({"type": sub_type, "url": url, "ping": "N/A"})
        self.save_to_system()
        self.refresh_list()
        self.url_input.clear()
        self.log(f"[KSOFT] Добавлен новый сервер: {sub_type}")

    def delete_subscription(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            removed = self.subscriptions.pop(row)
            self.save_to_system()
            self.refresh_list()
            self.log(f"[KSOFT] Удален сервер: {removed['type']}")
        else:
            QMessageBox.warning(self, "KSOFT", "Выберите сервер из списка для удаления!")

    def ping_all(self):
        if not self.subscriptions: return
        self.log("[KSOFT] Запуск проверки задержки серверов...")
        self.threads = []
        for index, sub in enumerate(self.subscriptions):
            worker = PingWorker(index, sub['url'])
            worker.ping_done.connect(self.update_ping)
            self.threads.append(worker)
            worker.start()

    def update_ping(self, index, result):
        if index < len(self.subscriptions):
            self.subscriptions[index]['ping'] = result
            sub = self.subscriptions[index]
            logo = "🔒" if sub['type'] == "HAPP" else "🌐"
            item = self.list_widget.item(index)
            if item:
                item.setText(f" {logo}  [{sub['type'].upper()}]  {sub['url'][:50]}...   |   Ping: {result}")

    def toggle_connection(self):
        row = self.list_widget.currentRow()
        if not self.is_connected:
            if row < 0:
                QMessageBox.warning(self, "KSOFT", "Сначала выберите сервер из списка для подключения!")
                return
            
            selected_url = self.subscriptions[row]['url']
            success = self.vpn_manager.start_tunnel(selected_url, self.log)
            if success:
                self.is_connected = True
                self.connect_btn.setText("ОТКЛЮЧИТЬ")
                self.connect_btn.setStyleSheet("background-color: #ff5577; color: white;")
                self.log("[KSOFT] Соединение успешно установлено! Защита активна.")
        else:
            self.vpn_manager.stop_tunnel(self.log)
            self.is_connected = False
            self.connect_btn.setText("ПОДКЛЮЧИТЬ")
            self.connect_btn.setStyleSheet("background-color: #00ffaa; color: #0d0f14;")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = KSoftApp()
    window.show()
    sys.exit(app.exec())