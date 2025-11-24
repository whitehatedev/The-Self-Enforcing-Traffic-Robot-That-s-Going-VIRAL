import pygame
import requests
import time
import threading
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, db


class ESP32CarController:
    def __init__(self):
        # ESP32 connection
        self.esp32_ip = "192.168.1.4"
        self.base_url = f"http://{self.esp32_ip}"

        # Initialize Firebase
        self.init_firebase()

        # Initialize pygame
        pygame.init()
        self.screen = pygame.display.set_mode((600, 500))
        pygame.display.set_caption("🤖 ESP32 Car Controller - Home Position System")

        # Control states
        self.moving = False
        self.current_direction = "STOP"
        self.vehicle_blocked = False
        self.emergency_stop = False
        self.at_home_position = False
        self.current_distance = 0
        self.connection_ok = False
        self.last_successful_connection = 0

        # Vehicle data
        self.current_plate = "MH19EQ0009"
        self.check_interval = 3

        # Key state tracking
        self.key_states = {
            pygame.K_UP: False,
            pygame.K_DOWN: False,
            pygame.K_LEFT: False,
            pygame.K_RIGHT: False
        }

        # Start status monitoring
        self.status_thread = threading.Thread(target=self.monitor_vehicle_status, daemon=True)
        self.status_thread.start()

        # Start ultrasonic monitoring
        self.ultrasonic_thread = threading.Thread(target=self.monitor_ultrasonic, daemon=True)
        self.ultrasonic_thread.start()

        print("🤖 ESP32 Car Controller Started")
        print(f"🎯 Monitoring vehicle: {self.current_plate}")
        print("🎮 Controls: Arrow Keys to move, Space to stop, E for emergency stop, ESC to quit")
        print("🏠 Home Position System: Vehicle stops ONLY when reaching home after fine notice")

    def init_firebase(self):
        """Initialize Firebase connection"""
        try:
            cred = credentials.Certificate("robot-dec4c-firebase-adminsdk.json")
            firebase_admin.initialize_app(cred, {
                'databaseURL': 'https://robot-dec4c-default-rtdb.firebaseio.com/'
            })
            self.db_ref = db.reference()
            print("Firebase initialized successfully")
        except Exception as e:
            print(f"Firebase initialization error: {e}")

    def send_command(self, command):
        """Send command to ESP32"""
        # Allow all movements until vehicle is blocked AND at home position
        if self.vehicle_blocked and self.at_home_position and command != "stop" and command != "emergency_stop":
            print("❌ Vehicle BLOCKED at home position - Cannot move. Pay fine first.")
            return False

        try:
            url = f"{self.base_url}/{command}"
            response = requests.get(url, timeout=3)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Command sent: {command} - Status: {data.get('status', 'unknown')}")
                self.connection_ok = True
                self.last_successful_connection = time.time()
                return True
            return False
        except Exception as e:
            print(f"❌ Failed to send command {command}: {e}")
            self.connection_ok = False
            return False

    def move_forward(self):
        if not self.emergency_stop:
            if self.send_command("forward"):
                self.moving = True
                self.current_direction = "FORWARD"

    def move_backward(self):
        if not self.emergency_stop:
            if self.send_command("backward"):
                self.moving = True
                self.current_direction = "BACKWARD"

    def turn_left(self):
        if not self.emergency_stop:
            if self.send_command("left"):
                self.moving = True
                self.current_direction = "LEFT"

    def turn_right(self):
        if not self.emergency_stop:
            if self.send_command("right"):
                self.moving = True
                self.current_direction = "RIGHT"

    def stop_car(self):
        if self.send_command("stop"):
            self.moving = False
            self.current_direction = "STOP"
            self.emergency_stop = False

    def emergency_stop_car(self):
        if self.send_command("emergency_stop"):
            self.moving = False
            self.current_direction = "EMERGENCY_STOP"
            self.emergency_stop = True
            print("🚨 EMERGENCY STOP ACTIVATED")

    def test_ultrasonic_sensor(self):
        """Test ultrasonic sensor functionality"""
        try:
            response = requests.get(f"{self.base_url}/test_ultrasonic", timeout=5)
            if response.status_code == 200:
                print("🔊 Ultrasonic sensor test page opened in browser")
                return True
            return False
        except Exception as e:
            print(f"❌ Ultrasonic test failed: {e}")
            return False

    def debug_esp32(self):
        """Get debug information from ESP32"""
        try:
            response = requests.get(f"{self.base_url}/debug", timeout=3)
            if response.status_code == 200:
                data = response.json()
                print("🔍 ESP32 Debug Info:")
                print(f"   Distance: {data.get('ultrasonic_distance', 'N/A')}cm")
                print(f"   Home Position: {data.get('at_home_position', 'N/A')}")
                print(f"   Blocked: {data.get('is_blocked', 'N/A')}")
                print(f"   Moving: {data.get('is_moving', 'N/A')}")
                print(f"   Direction: {data.get('current_direction', 'N/A')}")
                return True
            return False
        except Exception as e:
            print(f"❌ Debug request failed: {e}")
            return False

    def simple_status(self):
        """Get simple status from ESP32"""
        try:
            response = requests.get(f"{self.base_url}/simple_status", timeout=3)
            if response.status_code == 200:
                print(f"📊 Simple Status: {response.text}")
                return True
            return False
        except Exception as e:
            print(f"❌ Simple status failed: {e}")
            return False

    def check_vehicle_status(self):
        """Check if vehicle has reached fine notice stage (3+ detections)"""
        try:
            clean_plate = self.current_plate.replace(" ", "")
            vehicle_ref = self.db_ref.child(f'vehicles/{clean_plate}')
            vehicle_data = vehicle_ref.get()

            if vehicle_data:
                detection_count = vehicle_data.get('detection_count', 0)
                status = vehicle_data.get('status', 'active')

                # Vehicle is only blocked when it has 3+ detections AND reaches home position
                return detection_count >= 3

            return False
        except Exception as e:
            print(f"Error checking vehicle status: {e}")
            return False

    def get_ultrasonic_distance(self):
        """Get current distance from ultrasonic sensor"""
        try:
            response = requests.get(f"{self.base_url}/status", timeout=3)
            if response.status_code == 200:
                # First, let's see the raw response
                raw_response = response.text
                print(f"🔧 Raw response: {raw_response}")  # Debug line

                # Try to parse JSON
                try:
                    data = response.json()
                    distance = data.get('distance', 0)
                    home_status = data.get('home', 'not_home') == 'home'
                    self.connection_ok = True
                    self.last_successful_connection = time.time()
                    return distance, home_status
                except json.JSONDecodeError as e:
                    print(f"❌ JSON parsing error: {e}")
                    print(f"🔧 Response text: {response.text}")
                    # Try to fix common JSON issues
                    fixed_json = self.fix_json(response.text)
                    try:
                        data = json.loads(fixed_json)
                        distance = data.get('distance', 0)
                        home_status = data.get('home', 'not_home') == 'home'
                        self.connection_ok = True
                        self.last_successful_connection = time.time()
                        return distance, home_status
                    except:
                        self.connection_ok = False
                        return 0, False
            else:
                self.connection_ok = False
                return 0, False
        except Exception as e:
            print(f"❌ Error getting ultrasonic distance: {e}")
            self.connection_ok = False
            return 0, False

    def fix_json(self, json_string):
        """Attempt to fix common JSON formatting issues"""
        # Remove extra quotes and fix common issues
        fixed = json_string.replace('"distance":0"', '"distance":0')
        fixed = fixed.replace('""', '"')
        return fixed

    def monitor_vehicle_status(self):
        """Monitor vehicle status in background"""
        while True:
            try:
                was_blocked = self.vehicle_blocked
                self.vehicle_blocked = self.check_vehicle_status()

                if self.vehicle_blocked and not was_blocked:
                    print("🚫 FINE NOTICE RECEIVED! Vehicle will stop when reaching home position.")
                    print("📍 You can still move the vehicle until it reaches the home position.")
                    # Send block command to ESP32 (but allow movement until home)
                    try:
                        requests.get(f"{self.base_url}/block", timeout=3)
                    except:
                        pass
                elif not self.vehicle_blocked and was_blocked:
                    print("✅ Vehicle UNBLOCKED! Fine paid. You can move freely now.")
                    # Send unblock command to ESP32
                    try:
                        requests.get(f"{self.base_url}/unblock", timeout=3)
                    except:
                        pass

                time.sleep(self.check_interval)
            except Exception as e:
                print(f"Status monitor error: {e}")
                time.sleep(5)

    def monitor_ultrasonic(self):
        """Monitor ultrasonic sensor in background"""
        while True:
            try:
                distance, home_status = self.get_ultrasonic_distance()
                self.current_distance = distance
                self.at_home_position = home_status

                # If vehicle is blocked and reaches home position, stop it
                if self.vehicle_blocked and home_status and self.moving:
                    print("🏠 Vehicle reached home position while blocked - Stopping vehicle")
                    self.stop_car()

                time.sleep(2)
            except Exception as e:
                print(f"Ultrasonic monitor error: {e}")
                time.sleep(5)

    def display_interface(self):
        """Display controller interface"""
        self.screen.fill((0, 0, 0))

        # Title
        font_large = pygame.font.Font(None, 36)
        title = font_large.render("🤖 ESP32 Car Controller", True, (255, 255, 255))
        self.screen.blit(title, (20, 20))

        # Vehicle info
        font_medium = pygame.font.Font(None, 24)
        plate_text = font_medium.render(f"Vehicle: {self.current_plate}", True, (255, 255, 0))
        self.screen.blit(plate_text, (20, 60))

        # Connection status
        connection_color = (0, 255, 0) if self.connection_ok else (255, 0, 0)
        connection_text = "🟢 Connected to ESP32" if self.connection_ok else "🔴 ESP32 Connection Error"
        connection_surface = font_medium.render(connection_text, True, connection_color)
        self.screen.blit(connection_surface, (20, 90))

        # Status
        if self.emergency_stop:
            status_color = (255, 165, 0)
            status_text = "EMERGENCY STOP"
        elif self.vehicle_blocked:
            if self.at_home_position:
                status_color = (255, 100, 100)
                status_text = "BLOCKED AT HOME - Pay Fine Required"
            else:
                status_color = (255, 200, 0)
                status_text = "FINE NOTICE - Will stop at home position"
        else:
            status_color = (0, 255, 0)
            status_text = "ACTIVE - Ready to Move"

        status_surface = font_medium.render(f"Status: {status_text}", True, status_color)
        self.screen.blit(status_surface, (20, 120))

        # Home position status
        home_color = (0, 255, 0) if self.at_home_position else (255, 100, 100)
        home_text = f"Home Position: {'✅ AT HOME' if self.at_home_position else '❌ NOT AT HOME'}"
        home_surface = font_medium.render(home_text, True, home_color)
        self.screen.blit(home_surface, (20, 150))

        # Distance
        distance_color = (100, 255, 255) if self.at_home_position else (255, 255, 100)
        distance_text = f"Distance: {self.current_distance} cm"
        distance_surface = font_medium.render(distance_text, True, distance_color)
        self.screen.blit(distance_surface, (20, 180))

        # Movement status
        if self.moving:
            move_color = (0, 255, 0)
            move_text = f"Movement: {self.current_direction}"
        else:
            move_color = (255, 0, 0)
            move_text = "Movement: STOPPED"

        move_surface = font_medium.render(move_text, True, move_color)
        self.screen.blit(move_surface, (20, 210))

        # Controls section
        controls_font = pygame.font.Font(None, 22)
        controls_title = controls_font.render("🎮 CONTROLS:", True, (255, 255, 0))
        self.screen.blit(controls_title, (20, 250))

        controls = [
            "↑ - Move Forward",
            "↓ - Move Backward",
            "← - Turn Left",
            "→ - Turn Right",
            "SPACE - Stop",
            "E - Emergency Stop",
            "U - Test Ultrasonic Sensor",
            "D - Debug ESP32",
            "S - Simple Status",
            "ESC - Quit"
        ]

        for i, control in enumerate(controls):
            color = (200, 200, 200)
            control_surface = controls_font.render(control, True, color)
            self.screen.blit(control_surface, (40, 280 + i * 25))

        # Fine information
        if self.vehicle_blocked:
            fine_info = [
                "💰 FINE NOTICE ACTIVE:",
                "• Vehicle has 3+ traffic violations",
                "• Fine Amount: ₹500",
                "• Vehicle will STOP when reaching home position",
                "• You can still move until home position is reached",
                "",
                "🏠 HOME POSITION SYSTEM:",
                "• Move vehicle within 15cm of ultrasonic sensor",
                "• Green home indicator = at home position",
                "• Vehicle stops automatically when home is reached",
                "",
                "🌐 Payment Portal:",
                "https://admirable-madeleine-8f1a08.netlify.app"
            ]

            for i, info in enumerate(fine_info):
                if i == 0:
                    color = (255, 100, 100)
                elif "https://" in info:
                    color = (100, 100, 255)
                elif "HOME POSITION" in info:
                    color = (255, 255, 100)
                else:
                    color = (255, 150, 150)

                info_surface = controls_font.render(info, True, color)
                self.screen.blit(info_surface, (300, 60 + i * 20))

        # Draw control visualization
        self.draw_control_visualization()

        pygame.display.flip()

    def draw_control_visualization(self):
        """Draw a visual representation of current controls"""
        center_x, center_y = 450, 200
        size = 80

        pygame.draw.circle(self.screen, (50, 50, 50), (center_x, center_y), size)
        pygame.draw.circle(self.screen, (100, 100, 100), (center_x, center_y), size, 2)

        arrow_color = (0, 255, 0) if self.moving else (100, 100, 100)

        if self.current_direction == "FORWARD":
            pygame.draw.polygon(self.screen, arrow_color, [
                (center_x, center_y - size + 20),
                (center_x - 15, center_y - size + 50),
                (center_x + 15, center_y - size + 50)
            ])
        elif self.current_direction == "BACKWARD":
            pygame.draw.polygon(self.screen, arrow_color, [
                (center_x, center_y + size - 20),
                (center_x - 15, center_y + size - 50),
                (center_x + 15, center_y + size - 50)
            ])
        elif self.current_direction == "LEFT":
            pygame.draw.polygon(self.screen, arrow_color, [
                (center_x - size + 20, center_y),
                (center_x - size + 50, center_y - 15),
                (center_x - size + 50, center_y + 15)
            ])
        elif self.current_direction == "RIGHT":
            pygame.draw.polygon(self.screen, arrow_color, [
                (center_x + size - 20, center_y),
                (center_x + size - 50, center_y - 15),
                (center_x + size - 50, center_y + 15)
            ])
        else:
            pygame.draw.circle(self.screen, (255, 0, 0), (center_x, center_y), 20)
            stop_font = pygame.font.Font(None, 30)
            stop_text = stop_font.render("STOP", True, (255, 255, 255))
            text_rect = stop_text.get_rect(center=(center_x, center_y))
            self.screen.blit(stop_text, text_rect)

        # Draw home position indicator
        home_color = (0, 255, 0) if self.at_home_position else (255, 0, 0)
        pygame.draw.circle(self.screen, home_color, (center_x, center_y + 120), 10)
        home_font = pygame.font.Font(None, 20)
        home_text = home_font.render("HOME", True, home_color)
        home_rect = home_text.get_rect(center=(center_x, center_y + 140))
        self.screen.blit(home_text, home_rect)

    def run(self):
        """Main controller loop"""
        clock = pygame.time.Clock()
        running = True

        print("🤖 Controller ready. Use arrow keys to control the robot.")
        print("🔊 Press 'U' to test ultrasonic sensor")
        print("🔍 Press 'D' for ESP32 debug information")
        print("📊 Press 'S' for simple status")
        print("🏠 Home position system: Vehicle stops only when reaching home after fine notice")

        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_UP:
                        self.key_states[pygame.K_UP] = True
                        self.move_forward()
                    elif event.key == pygame.K_DOWN:
                        self.key_states[pygame.K_DOWN] = True
                        self.move_backward()
                    elif event.key == pygame.K_LEFT:
                        self.key_states[pygame.K_LEFT] = True
                        self.turn_left()
                    elif event.key == pygame.K_RIGHT:
                        self.key_states[pygame.K_RIGHT] = True
                        self.turn_right()
                    elif event.key == pygame.K_SPACE:
                        self.stop_car()
                    elif event.key == pygame.K_e:
                        self.emergency_stop_car()
                    elif event.key == pygame.K_u:
                        print("🔊 Testing ultrasonic sensor...")
                        self.test_ultrasonic_sensor()
                    elif event.key == pygame.K_d:
                        print("🔍 Getting ESP32 debug information...")
                        self.debug_esp32()
                    elif event.key == pygame.K_s:
                        print("📊 Getting simple status...")
                        self.simple_status()
                    elif event.key == pygame.K_ESCAPE:
                        running = False

                elif event.type == pygame.KEYUP:
                    if event.key in self.key_states:
                        self.key_states[event.key] = False

                    if not any(self.key_states.values()):
                        self.stop_car()

            self.display_interface()
            clock.tick(30)

        self.stop_car()
        pygame.quit()
        print("🤖 Controller stopped.")


def main():
    controller = ESP32CarController()
    controller.run()


if __name__ == "__main__":
    main()