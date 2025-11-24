import cv2
import numpy as np
import pygame
import time
from datetime import datetime
import os
from ultralytics import YOLO
import pytesseract
import re
import firebase_admin
from firebase_admin import credentials, db
import smtplib
from email.message import EmailMessage
import mimetypes
from pathlib import Path
import requests
import threading


class NumberPlateDetectionSystem:
    def __init__(self):
        # Initialize pygame for sound
        pygame.mixer.init()

        # Load beep sound
        self.beep_sound = pygame.mixer.Sound(self.generate_beep_sound())

        # Initialize Firebase
        self.init_firebase()

        # Traffic signal states
        self.signal_state = "red"
        self.signal_timer = 0
        self.signal_durations = {"red": 10, "yellow": 3, "green": 15}

        # Violation tracking
        self.violations = []
        self.last_detection_time = 0
        self.detection_cooldown = 2

        # Zone configuration
        self.red_line_y = 300
        self.red_line_thickness = 3

        # Green zone configuration
        self.green_zone_top = self.red_line_y
        self.green_zone_bottom = 480
        self.green_zone_color = (0, 255, 0)
        self.green_zone_alpha = 0.2

        # Detection control
        self.detection_active = False

        # Load number plate model
        self.load_plate_model()

        # Set Tesseract path
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

        # Create directories
        if not os.path.exists("violations"):
            os.makedirs("violations")
        if not os.path.exists("detections"):
            os.makedirs("detections")

        # Email configuration
        self.SMTP_SERVER = "smtp.gmail.com"
        self.SMTP_PORT = 465
        self.SENDER_EMAIL = "sb284160@gmail.com"
        self.SENDER_PASSWORD = "almg jghc wvws imli"

        # Payment configuration
        self.payment_url = "https://admirable-madeleine-8f1a08.netlify.app/"

        # Video capture
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        # Detection variables
        self.last_detected_plate = None
        self.plate_detection_count = 0
        self.email_cooldown = {}
        self.detected_plates_history = {}
        self.last_target_detection_time = 0
        self.target_detection_cooldown = 30

        # Target vehicle configuration
        self.target_plate = "MH 19 EQ 0009"
        self.target_email = "sb284160@gmail.com"
        self.target_phone = "+919657270849"

        # Detection count tracking
        self.target_detection_count = 0
        self.last_detection_count_update = 0
        self.detection_count_cooldown = 10

        # Payment monitoring
        self.last_payment_check = 0
        self.payment_check_interval = 5  # Check every 5 seconds

        print("Number Plate Detection System Initialized")
        print(f"🎯 TARGET VEHICLE: {self.target_plate}")
        print(f"📧 TARGET EMAIL: {self.target_email}")

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

    def load_plate_model(self):
        """Load number plate detection model"""
        try:
            self.plate_model = YOLO('best.pt')
            print("Number plate detection model loaded successfully")
        except Exception as e:
            print(f"Number plate model not found: {e}")
            self.plate_model = None

    def generate_beep_sound(self):
        """Generate beep sound"""
        sample_rate = 44100
        duration = 1000
        frequency = 800

        n_samples = int(round(duration * 0.001 * sample_rate))
        buf = np.zeros((n_samples, 2), dtype=np.float32)
        max_amplitude = 2 ** 15 - 1

        for i in range(n_samples):
            t = float(i) / sample_rate
            buf[i][0] = int(round(max_amplitude * np.sin(2 * np.pi * frequency * t)))
            buf[i][1] = int(round(max_amplitude * np.sin(2 * np.pi * frequency * t)))

        return pygame.sndarray.make_sound(buf)

    def check_payment_status(self):
        """Check if fine has been paid and reset detection count"""
        current_time = time.time()

        if current_time - self.last_payment_check < self.payment_check_interval:
            return

        self.last_payment_check = current_time

        try:
            clean_plate = self.target_plate.replace(" ", "")
            vehicle_ref = self.db_ref.child(f'vehicles/{clean_plate}')
            vehicle_data = vehicle_ref.get()

            if vehicle_data:
                # Check if payment was made recently (last 10 seconds)
                last_payment = vehicle_data.get('last_payment')
                if last_payment:
                    payment_time = datetime.fromisoformat(last_payment)
                    current_time_dt = datetime.now()
                    time_diff = (current_time_dt - payment_time).total_seconds()

                    # If payment was made recently and detection count is high, reset it
                    if time_diff < 10 and self.target_detection_count >= 3:
                        print("💰 Payment detected! Resetting detection count and unblocking vehicle...")
                        self.target_detection_count = 0

                        # Update Firebase
                        vehicle_data['detection_count'] = 0
                        vehicle_data['status'] = 'active'
                        vehicle_ref.set(vehicle_data)

                        # Send unblock command to robot
                        self.send_robot_command("unblock")

                        print("✅ Detection count reset to 0. Vehicle unblocked.")

        except Exception as e:
            print(f"Error checking payment status: {e}")

    def update_signal_state(self):
        """Update traffic signal state"""
        current_time = time.time()

        if current_time - self.signal_timer >= self.signal_durations[self.signal_state]:
            if self.signal_state == "red":
                self.signal_state = "green"
                self.detection_active = False
                print("🟢 GREEN LIGHT - Detection OFF")
            elif self.signal_state == "green":
                self.signal_state = "yellow"
                self.detection_active = False
                print("🟡 YELLOW LIGHT - Detection OFF")
            else:
                self.signal_state = "red"
                self.detection_active = True
                print("🔴 RED LIGHT - Detection ON")

            self.signal_timer = current_time

    def draw_traffic_signal(self, frame):
        """Draw traffic signal on frame"""
        signal_x, signal_y = 50, 50
        circle_radius = 20
        spacing = 60

        # Draw signal box
        cv2.rectangle(frame, (signal_x - 10, signal_y - 10),
                      (signal_x + 40, signal_y + spacing * 3 - 30), (50, 50, 50), -1)
        cv2.rectangle(frame, (signal_x - 10, signal_y - 10),
                      (signal_x + 40, signal_y + spacing * 3 - 30), (255, 255, 255), 2)

        # Draw lights
        red_color = (0, 0, 255) if self.signal_state == "red" else (0, 0, 100)
        yellow_color = (0, 255, 255) if self.signal_state == "yellow" else (0, 100, 100)
        green_color = (0, 255, 0) if self.signal_state == "green" else (0, 100, 0)

        cv2.circle(frame, (signal_x + 15, signal_y + 15), circle_radius, red_color, -1)
        cv2.circle(frame, (signal_x + 15, signal_y + 15 + spacing), circle_radius, yellow_color, -1)
        cv2.circle(frame, (signal_x + 15, signal_y + 15 + spacing * 2), circle_radius, green_color, -1)

        # Add borders
        cv2.circle(frame, (signal_x + 15, signal_y + 15), circle_radius, (255, 255, 255), 2)
        cv2.circle(frame, (signal_x + 15, signal_y + 15 + spacing), circle_radius, (255, 255, 255), 2)
        cv2.circle(frame, (signal_x + 15, signal_y + 15 + spacing * 2), circle_radius, (255, 255, 255), 2)

        # Timer
        elapsed = time.time() - self.signal_timer
        remaining = max(0, self.signal_durations[self.signal_state] - elapsed)
        timer_text = f"{remaining:.1f}s"
        cv2.putText(frame, timer_text, (signal_x - 5, signal_y + spacing * 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # Detection status
        detection_status = "DETECTION: ON" if self.detection_active else "DETECTION: OFF"
        detection_color = (0, 255, 0) if self.detection_active else (0, 0, 255)
        cv2.putText(frame, detection_status, (signal_x - 10, signal_y + spacing * 3 + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, detection_color, 2)

    def draw_zones(self, frame):
        """Draw red line and green zone"""
        height, width = frame.shape[:2]

        # Draw green zone
        green_zone_overlay = frame.copy()
        cv2.rectangle(green_zone_overlay,
                      (0, self.green_zone_top),
                      (width, self.green_zone_bottom),
                      self.green_zone_color, -1)
        cv2.addWeighted(green_zone_overlay, self.green_zone_alpha, frame, 1 - self.green_zone_alpha, 0, frame)

        # Draw red stop line
        line_color = (0, 0, 255)
        cv2.line(frame, (0, self.red_line_y), (width, self.red_line_y),
                 line_color, self.red_line_thickness)

        # Add labels
        cv2.putText(frame, "STOP LINE", (width - 150, self.red_line_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, line_color, 2)
        cv2.putText(frame, "GREEN ZONE", (width - 150, self.red_line_y + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 100, 0), 2)

    def detect_number_plates(self, frame):
        """Detect number plates in frame"""
        plates_detected = []

        if not self.detection_active or not self.plate_model:
            return plates_detected

        try:
            results = self.plate_model(frame, verbose=False)

            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for box in boxes:
                        conf = float(box.conf[0])
                        if conf > 0.5:
                            x1, y1, x2, y2 = map(int, box.xyxy[0])

                            plate_roi = frame[y1:y2, x1:x2]

                            if plate_roi.size > 0:
                                plate_text = self.extract_plate_text(plate_roi)

                                if plate_text and len(plate_text.replace(" ", "")) >= 6:
                                    plates_detected.append({
                                        'bbox': (x1, y1, x2, y2),
                                        'confidence': conf,
                                        'plate_text': plate_text,
                                        'center_y': (y1 + y2) // 2
                                    })

        except Exception as e:
            print(f"Plate detection error: {e}")

        return plates_detected

    def extract_plate_text(self, plate_roi):
        """Extract text from number plate and format with spaces"""
        try:
            gray = cv2.cvtColor(plate_roi, cv2.COLOR_BGR2GRAY)
            gray = cv2.bilateralFilter(gray, 11, 17, 17)

            thresh = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV, 35, 15
            )

            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

            texts = []

            configs = [
                '--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                '--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                '--psm 13 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            ]

            for config in configs:
                text = pytesseract.image_to_string(thresh, config=config).strip()
                if text and len(text.replace(" ", "")) >= 6:
                    texts.append(text)

            if texts:
                best_text = max(texts, key=len)
                formatted_text = self.format_number_plate_with_spaces(best_text)
                return formatted_text
            else:
                return None

        except Exception as e:
            print(f"OCR error: {e}")
            return None

    def format_number_plate_with_spaces(self, text):
        """Format number plate with proper spacing"""
        try:
            clean_text = re.sub(r'[^A-Z0-9]', '', text.upper())

            if len(clean_text) < 6:
                return clean_text

            if len(clean_text) == 10:
                formatted = f"{clean_text[0:2]} {clean_text[2:4]} {clean_text[4:6]} {clean_text[6:10]}"
            elif len(clean_text) == 9:
                formatted = f"{clean_text[0:2]} {clean_text[2:4]} {clean_text[4:5]} {clean_text[5:9]}"
            elif len(clean_text) == 8:
                formatted = f"{clean_text[0:2]} {clean_text[2:4]} {clean_text[4:6]} {clean_text[6:8]}"
            elif len(clean_text) > 10:
                clean_text = clean_text[:10]
                formatted = f"{clean_text[0:2]} {clean_text[2:4]} {clean_text[4:6]} {clean_text[6:10]}"
            else:
                formatted = ' '.join([clean_text[i:i + 2] for i in range(0, len(clean_text), 2)])

            return formatted.strip()

        except Exception as e:
            print(f"Plate formatting error: {e}")
            return text

    def is_target_vehicle(self, detected_plate):
        """Check if detected plate matches target plate"""
        if not detected_plate:
            return False

        detected_clean = detected_plate.replace(" ", "").upper()
        target_clean = self.target_plate.replace(" ", "").upper()

        return detected_clean == target_clean

    def check_red_light_violation(self, frame, plates):
        """Check for red light violations"""
        current_time = time.time()

        if not self.detection_active or self.signal_state != "red":
            return False

        if current_time - self.last_detection_time < self.detection_cooldown:
            return False

        violation_detected = False

        for plate in plates:
            plate_center_y = plate['center_y']

            if plate_center_y > self.red_line_y:
                violation_detected = True

                x1, y1, x2, y2 = plate['bbox']

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                cv2.putText(frame, "RED LIGHT VIOLATION!", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                plate_text = plate['plate_text'] if plate['plate_text'] else "UNREADABLE"
                cv2.putText(frame, f"Plate: {plate_text}", (x1, y1 - 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                if plate['plate_text']:
                    self.process_violation(frame, plate)

                self.beep_sound.play()
                self.last_detection_time = current_time
                break

        return violation_detected

    def update_target_detection_count(self):
        """Update target vehicle detection count with cooldown"""
        current_time = time.time()

        if current_time - self.last_detection_count_update < self.detection_count_cooldown:
            return self.target_detection_count

        self.last_detection_count_update = current_time
        self.target_detection_count += 1

        try:
            clean_plate = self.target_plate.replace(" ", "")
            vehicle_ref = self.db_ref.child(f'vehicles/{clean_plate}')
            vehicle_data = vehicle_ref.get() or {}
            vehicle_data['detection_count'] = self.target_detection_count
            vehicle_data['last_detection'] = datetime.now().isoformat()
            vehicle_ref.set(vehicle_data)
        except Exception as e:
            print(f"Error updating detection count in Firebase: {e}")

        print(f"🎯 Target Detection Count: #{self.target_detection_count}")
        return self.target_detection_count

    def process_target_vehicle_detection(self, frame, plate):
        """Process target vehicle detection"""
        try:
            current_time = time.time()

            if current_time - self.last_target_detection_time < self.target_detection_cooldown:
                return

            self.last_target_detection_time = current_time

            detection_count = self.update_target_detection_count()

            plate_text = plate['plate_text']
            confidence = plate['confidence']

            print(f"🎯 TARGET VEHICLE SPOTTED: {plate_text} - Detection #{detection_count}")

            evidence_filename = self.save_detection_evidence(frame, plate, plate_text)

            # Only block vehicle and send fine notice on 3rd detection
            if detection_count == 3:
                self.send_fine_notice(plate_text, confidence, plate, evidence_filename, detection_count)
                self.block_vehicle(plate_text)
            elif detection_count < 3:
                # For 1st and 2nd detection, just send warnings but don't block
                if detection_count == 1:
                    self.send_first_detection_notification(plate_text, confidence, plate, evidence_filename)
                elif detection_count == 2:
                    self.send_second_detection_notification(plate_text, confidence, plate, evidence_filename)

        except Exception as e:
            print(f"Error processing target detection: {e}")

    def process_violation(self, frame, plate):
        """Process violation"""
        plate_text = plate['plate_text']
        evidence_filename = self.save_violation_evidence(frame, plate, plate_text)
        violation_count = self.update_violation_count(plate_text)

        print(f"🚨 Red light violation! Plate: {plate_text} - Violation #{violation_count}")

        if self.is_target_vehicle(plate_text):
            print(f"🎯 TARGET VEHICLE VIOLATION! Sending email to {self.target_email}")
            self.send_immediate_violation_notification(plate_text, violation_count, plate, evidence_filename)

    def update_violation_count(self, plate_number):
        """Update violation count and return current count"""
        try:
            is_target = self.is_target_vehicle(plate_number)

            if is_target:
                vehicle_data = {
                    'violation_count': 0,
                    'phone': self.target_phone,
                    'email': self.target_email,
                    'status': 'active'
                }

                try:
                    clean_plate = plate_number.replace(" ", "")
                    vehicle_ref = self.db_ref.child(f'vehicles/{clean_plate}')
                    existing_data = vehicle_ref.get()
                    if existing_data and 'violation_count' in existing_data:
                        vehicle_data['violation_count'] = existing_data['violation_count']
                except:
                    pass
            else:
                clean_plate = plate_number.replace(" ", "")
                vehicle_ref = self.db_ref.child(f'vehicles/{clean_plate}')
                vehicle_data = vehicle_ref.get() or {
                    'violation_count': 0,
                    'phone': '+919657270849',
                    'email': 'sb284160@gmail.com',
                    'status': 'active'
                }

            vehicle_data['violation_count'] = vehicle_data.get('violation_count', 0) + 1
            vehicle_data['last_violation'] = datetime.now().isoformat()

            clean_plate = plate_number.replace(" ", "")
            vehicle_ref = self.db_ref.child(f'vehicles/{clean_plate}')
            vehicle_ref.set(vehicle_data)

            violation_count = vehicle_data['violation_count']

            return violation_count

        except Exception as e:
            print(f"Error updating violation count: {e}")
            return 1

    def send_first_detection_notification(self, plate_number, confidence, plate, evidence_filename):
        """Send first detection warning email"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            subject = f"⚠️ FIRST DETECTION: {plate_number} Spotted - Warning #1"

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.SENDER_EMAIL
            msg["To"] = self.target_email

            plain_text = f"""
            ⚠️ FIRST DETECTION WARNING - TARGET VEHICLE SPOTTED

            🚗 VEHICLE: {plate_number}
            📊 DETECTION COUNT: #1
            ⏰ TIME: {timestamp}
            🎯 CONFIDENCE: {confidence:.2%}
            📍 STATUS: First Detection - Warning Issued

            This is your FIRST detection warning.
            Your vehicle has been spotted in the monitoring area.

            EVIDENCE: Image attached with timestamp.
            """
            msg.set_content(plain_text)

            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 3px solid #ffc107; border-radius: 10px; background: #fff;">
                    <div style="text-align: center; background: #ffc107; color: white; padding: 15px; border-radius: 8px 8px 0 0; margin: -20px -20px 20px -20px;">
                        <h1 style="margin: 0; font-size: 24px;">⚠️ FIRST DETECTION WARNING</h1>
                        <p style="margin: 5px 0 0 0; font-size: 16px;">Target Vehicle Monitoring System</p>
                    </div>
                    <div style="background: #fff3cd; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #ffc107;">
                        <h3 style="color: #856404; margin-top: 0;">🎯 TARGET VEHICLE FIRST DETECTION</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 8px; border-bottom: 1px solid #ffeaa7; font-weight: bold; width: 40%;">Vehicle Number:</td>
                                <td style="padding: 8px; border-bottom: 1px solid #ffeaa7;"><strong style="color: #856404; font-size: 18px;">{plate_number}</strong></td>
                            </tr>
                            <tr>
                                <td style="padding: 8px; border-bottom: 1px solid #ffeaa7; font-weight: bold;">Detection Count:</td>
                                <td style="padding: 8px; border-bottom: 1px solid #ffeaa7;">
                                    <span style="background: #ffc107; color: white; padding: 2px 8px; border-radius: 10px; font-weight: bold;">
                                        #1 - FIRST DETECTION
                                    </span>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding: 8px; border-bottom: 1px solid #ffeaa7; font-weight: bold;">Detection Confidence:</td>
                                <td style="padding: 8px; border-bottom: 1px solid #ffeaa7;">
                                    <span style="color: #28a745; font-weight: bold;">{confidence:.2%}</span>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding: 8px; border-bottom: 1px solid #ffeaa7; font-weight: bold;">Detection Time:</td>
                                <td style="padding: 8px; border-bottom: 1px solid #ffeaa7;">{timestamp}</td>
                            </tr>
                        </table>
                    </div>
                </div>
            </body>
            </html>
            """
            msg.add_alternative(html_content, subtype="html")

            if os.path.exists(evidence_filename):
                ctype, encoding = mimetypes.guess_type(evidence_filename)
                if ctype is None:
                    ctype = "application/octet-stream"
                maintype, subtype = ctype.split("/", 1)
                with open(evidence_filename, "rb") as f:
                    msg.add_attachment(f.read(),
                                       maintype=maintype,
                                       subtype=subtype,
                                       filename=os.path.basename(evidence_filename))

            email_thread = threading.Thread(
                target=self.send_email_message,
                args=(msg,)
            )
            email_thread.daemon = True
            email_thread.start()

            print(f"📧 FIRST DETECTION WARNING SENT to {self.target_email}")

        except Exception as e:
            print(f"❌ Error sending first detection notification: {e}")

    def send_second_detection_notification(self, plate_number, confidence, plate, evidence_filename):
        """Send second detection warning email"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            subject = f"🚨 SECOND DETECTION: {plate_number} Spotted - Warning #2"

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.SENDER_EMAIL
            msg["To"] = self.target_email

            plain_text = f"""
            🚨 SECOND DETECTION WARNING

            🚗 VEHICLE: {plate_number}
            📊 DETECTION COUNT: #2
            ⏰ TIME: {timestamp}
            🎯 CONFIDENCE: {confidence:.2%}
            📍 STATUS: Second Detection - Warning

            This is your SECOND detection warning.
            Your vehicle has been spotted again in the monitoring area.

            NEXT DETECTION WILL RESULT IN FINE: ₹500
            EVIDENCE: Image attached with timestamp.
            """
            msg.set_content(plain_text)

            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 3px solid #fd7e14; border-radius: 10px; background: #fff;">
                    <div style="text-align: center; background: #fd7e14; color: white; padding: 15px; border-radius: 8px 8px 0 0; margin: -20px -20px 20px -20px;">
                        <h1 style="margin: 0; font-size: 24px;">🚨 SECOND DETECTION WARNING</h1>
                        <p style="margin: 5px 0 0 0; font-size: 16px;">Target Vehicle Monitoring System</p>
                    </div>
                    <div style="background: #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #fd7e14;">
                        <h3 style="color: #856404; margin-top: 0;">🎯 TARGET VEHICLE SECOND DETECTION</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 8px; border-bottom: 1px solid #fdcb6e; font-weight: bold; width: 40%;">Vehicle Number:</td>
                                <td style="padding: 8px; border-bottom: 1px solid #fdcb6e;"><strong style="color: #856404; font-size: 18px;">{plate_number}</strong></td>
                            </tr>
                            <tr>
                                <td style="padding: 8px; border-bottom: 1px solid #fdcb6e; font-weight: bold;">Detection Count:</td>
                                <td style="padding: 8px; border-bottom: 1px solid #fdcb6e;">
                                    <span style="background: #fd7e14; color: white; padding: 2px 8px; border-radius: 10px; font-weight: bold;">
                                        #2 - WARNING
                                    </span>
                                </td>
                            </tr>
                        </table>
                    </div>
                </div>
            </body>
            </html>
            """
            msg.add_alternative(html_content, subtype="html")

            if os.path.exists(evidence_filename):
                ctype, encoding = mimetypes.guess_type(evidence_filename)
                if ctype is None:
                    ctype = "application/octet-stream"
                maintype, subtype = ctype.split("/", 1)
                with open(evidence_filename, "rb") as f:
                    msg.add_attachment(f.read(),
                                       maintype=maintype,
                                       subtype=subtype,
                                       filename=os.path.basename(evidence_filename))

            email_thread = threading.Thread(
                target=self.send_email_message,
                args=(msg,)
            )
            email_thread.daemon = True
            email_thread.start()

            print(f"📧 SECOND DETECTION WARNING SENT to {self.target_email}")

        except Exception as e:
            print(f"❌ Error sending second detection notification: {e}")

    def send_fine_notice(self, plate_number, confidence, plate, evidence_filename, detection_count):
        """Send fine notice email with payment link - ONLY on 3rd detection"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            subject = f"💰 FINE NOTICE: {plate_number} - ₹500 Fine - Detection #{detection_count}"

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.SENDER_EMAIL
            msg["To"] = self.target_email

            plain_text = f"""
            💰 FINE NOTICE - MULTIPLE DETECTIONS

            🚗 VEHICLE: {plate_number}
            📊 DETECTION COUNT: #{detection_count}
            ⏰ TIME: {timestamp}
            🎯 CONFIDENCE: {confidence:.2%}
            💰 FINE AMOUNT: ₹500
            📍 STATUS: FINE IMPOSED - VEHICLE WILL BE STOPPED AT HOME POSITION

            Your vehicle has been detected {detection_count} times in the monitoring area.
            A fine of ₹500 has been imposed.
            Your vehicle will be STOPPED when it reaches the home position until the fine is paid.

            PAYMENT LINK: {self.payment_url}/?plate={plate_number.replace(' ', '')}&amount=500

            EVIDENCE: Image attached with timestamp.
            """
            msg.set_content(plain_text)

            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 3px solid #dc3545; border-radius: 10px; background: #fff;">
                    <div style="text-align: center; background: #dc3545; color: white; padding: 15px; border-radius: 8px 8px 0 0; margin: -20px -20px 20px -20px;">
                        <h1 style="margin: 0; font-size: 24px;">💰 FINE NOTICE - MULTIPLE DETECTIONS</h1>
                        <p style="margin: 5px 0 0 0; font-size: 16px;">Target Vehicle Monitoring System</p>
                    </div>
                    <div style="background: #f8d7da; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #dc3545;">
                        <h3 style="color: #721c24; margin-top: 0;">🎯 TARGET VEHICLE MULTIPLE DETECTIONS</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 8px; border-bottom: 1px solid #f5c6cb; font-weight: bold; width: 40%;">Vehicle Number:</td>
                                <td style="padding: 8px; border-bottom: 1px solid #f5c6cb;"><strong style="color: #721c24; font-size: 18px;">{plate_number}</strong></td>
                            </tr>
                            <tr>
                                <td style="padding: 8px; border-bottom: 1px solid #f5c6cb; font-weight: bold;">Detection Count:</td>
                                <td style="padding: 8px; border-bottom: 1px solid #f5c6cb;">
                                    <span style="background: #dc3545; color: white; padding: 2px 8px; border-radius: 10px; font-weight: bold;">
                                        #{detection_count} - FINE IMPOSED
                                    </span>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding: 8px; font-weight: bold;">Fine Amount:</td>
                                <td style="padding: 8px;"><strong style="color: #dc3545; font-size: 20px;">₹500</strong></td>
                            </tr>
                        </table>
                    </div>
                    <div style="text-align: center; margin: 20px 0;">
                        <a href="{self.payment_url}/?plate={plate_number.replace(' ', '')}&amount=500" 
                           style="background: #dc3545; color: white; padding: 15px 40px; 
                                  text-decoration: none; border-radius: 5px; font-weight: bold;
                                  font-size: 18px; display: inline-block;">
                           💳 PAY FINE NOW - ₹500
                        </a>
                    </div>
                    <div style="background: #d1ecf1; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #0c5460;">
                        <h4 style="color: #0c5460; margin-top: 0;">🏠 Home Position System</h4>
                        <p style="color: #0c5460; margin: 5px 0;">
                            Your vehicle will be <strong>stopped automatically</strong> when it reaches the home position 
                            (within 15cm of ultrasonic sensor). You can still move the vehicle until it reaches home.
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """
            msg.add_alternative(html_content, subtype="html")

            if os.path.exists(evidence_filename):
                ctype, encoding = mimetypes.guess_type(evidence_filename)
                if ctype is None:
                    ctype = "application/octet-stream"
                maintype, subtype = ctype.split("/", 1)
                with open(evidence_filename, "rb") as f:
                    msg.add_attachment(f.read(),
                                       maintype=maintype,
                                       subtype=subtype,
                                       filename=os.path.basename(evidence_filename))

            email_thread = threading.Thread(
                target=self.send_email_message,
                args=(msg,)
            )
            email_thread.daemon = True
            email_thread.start()

            print(f"📧 FINE NOTICE SENT to {self.target_email}")

        except Exception as e:
            print(f"❌ Error sending fine notice: {e}")

    def send_immediate_violation_notification(self, plate_number, violation_count, plate, evidence_filename):
        """Send immediate violation notification"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            subject = f"🚨 IMMEDIATE VIOLATION: {plate_number} - Red Light Violation"

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.SENDER_EMAIL
            msg["To"] = self.target_email

            plain_text = f"""
            🚨 IMMEDIATE RED LIGHT VIOLATION

            🚗 VEHICLE: {plate_number}
            📊 VIOLATION COUNT: #{violation_count}
            ⏰ TIME: {timestamp}
            📍 STATUS: Red Light Violation Detected

            Your vehicle has been detected crossing the red light.
            This is violation #{violation_count}.

            EVIDENCE: Image attached with timestamp.
            """
            msg.set_content(plain_text)

            email_thread = threading.Thread(
                target=self.send_email_message,
                args=(msg,)
            )
            email_thread.daemon = True
            email_thread.start()

            print(f"📧 IMMEDIATE VIOLATION NOTIFICATION SENT to {self.target_email}")

        except Exception as e:
            print(f"❌ Error sending immediate violation notification: {e}")

    def send_email_message(self, msg):
        """Send email using the provided method"""
        try:
            with smtplib.SMTP_SSL(self.SMTP_SERVER, self.SMTP_PORT) as smtp:
                smtp.login(self.SENDER_EMAIL, self.SENDER_PASSWORD)
                smtp.send_message(msg)
                print("✅ EMAIL SENT SUCCESSFULLY!")
                return True
        except Exception as e:
            print(f"❌ Email sending failed: {e}")
            return False

    def save_detection_evidence(self, frame, plate, plate_text):
        """Save detection evidence and return filename"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plate_info = plate_text if plate_text else "UNKNOWN"
        filename = f"detections/detection_{timestamp}_{plate_info.replace(' ', '_')}.jpg"

        detection_frame = frame.copy()

        info_text = f"TARGET VEHICLE DETECTED - {timestamp}"
        cv2.putText(detection_frame, info_text, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

        plate_text_display = f"Plate: {plate_info}"
        cv2.putText(detection_frame, plate_text_display, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

        x1, y1, x2, y2 = plate['bbox']
        cv2.rectangle(detection_frame, (x1, y1), (x2, y2), (0, 165, 255), 3)
        cv2.putText(detection_frame, "TARGET DETECTED", (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

        cv2.imwrite(filename, detection_frame)

        print(f"📸 Target detection evidence saved: {filename}")
        return filename

    def save_violation_evidence(self, frame, plate, plate_text):
        """Save violation evidence and return filename"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plate_info = plate_text if plate_text else "UNKNOWN"
        filename = f"violations/violation_{timestamp}_{plate_info.replace(' ', '_')}.jpg"

        violation_frame = frame.copy()

        info_text = f"RED LIGHT VIOLATION - {timestamp}"
        cv2.putText(violation_frame, info_text, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        plate_text_display = f"Plate: {plate_info}"
        cv2.putText(violation_frame, plate_text_display, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        x1, y1, x2, y2 = plate['bbox']
        cv2.rectangle(violation_frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
        cv2.putText(violation_frame, "VIOLATION", (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        cv2.imwrite(filename, violation_frame)

        violation_info = {
            'timestamp': timestamp,
            'plate_number': plate_text,
            'filename': filename
        }
        self.violations.append(violation_info)

        print(f"📸 Violation evidence saved: {filename}")
        return filename

    def block_vehicle(self, plate_number):
        """Block vehicle - only on 3rd detection"""
        try:
            print(f"🚫 Vehicle {plate_number} MARKED FOR STOPPING AT HOME POSITION due to multiple detections")
            self.send_robot_command("block")
        except Exception as e:
            print(f"Error blocking vehicle: {e}")

    def send_robot_command(self, command):
        """Send command to ESP32 robot"""
        try:
            esp32_ip = "192.168.1.4"
            url = f"http://{esp32_ip}/{command}"
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                print(f"🤖 Robot command: {command}")
        except Exception as e:
            print(f"Robot communication error: {e}")

    def display_statistics(self, frame):
        """Display system statistics"""
        stats_y = 400

        cv2.putText(frame, f"Signal: {self.signal_state.upper()}", (10, stats_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame, f"Violations: {len(self.violations)}", (10, stats_y + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        detection_status = "DETECTION: ACTIVE" if self.detection_active else "DETECTION: INACTIVE"
        detection_color = (0, 255, 0) if self.detection_active else (0, 0, 255)
        cv2.putText(frame, detection_status, (10, stats_y + 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, detection_color, 2)

        cv2.putText(frame, f"TARGET: {self.target_plate}", (10, stats_y + 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        cv2.putText(frame, f"Detections: #{self.target_detection_count}", (10, stats_y + 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        if self.last_detected_plate:
            plate_color = (0, 255, 0) if self.is_target_vehicle(self.last_detected_plate) else (255, 255, 0)
            status_text = "🎯 TARGET!" if self.is_target_vehicle(self.last_detected_plate) else "Other"
            cv2.putText(frame, f"Last: {self.last_detected_plate} [{status_text}]", (10, stats_y + 150),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, plate_color, 1)

        instructions = [
            "🔴 RED: Detection ON",
            "🟢 GREEN: Detection OFF",
            "🟡 YELLOW: Detection OFF",
            f"🎯 Targeting: {self.target_plate}",
            f"📧 Escalation: 1=Warning, 2=Warning, 3=Fine+Home Stop",
            f"Current Detection Count: #{self.target_detection_count}",
            "Press 'q' to quit",
            "Press 't' to test email"
        ]

        for i, instruction in enumerate(instructions):
            cv2.putText(frame, instruction, (10, stats_y + 180 + i * 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    def run(self):
        """Main system loop"""
        print("=" * 60)
        print("🎯 ESCALATING DETECTION SYSTEM")
        print("=" * 60)
        print(f"TARGET VEHICLE: {self.target_plate}")
        print(f"NOTIFICATION EMAIL: {self.target_email}")
        print(f"PHONE: {self.target_phone}")
        print("📧 EMAIL ESCALATION SYSTEM:")
        print("  1st Detection: ⚠️ Warning Email")
        print("  2nd Detection: 🚨 Warning Email")
        print("  3rd Detection: 💰 Fine Notice + Stop at Home Position")
        print("🏠 VEHICLE MOVEMENT:")
        print("  - 1st/2nd detection: Vehicle can move freely")
        print("  - 3rd detection: Vehicle stops ONLY when reaching home position")
        print("PLATE FORMAT: With spaces (MH 19 EQ 0009)")
        print("=" * 60)

        while True:
            ret, frame = self.cap.read()
            if not ret:
                break

            # Update system
            self.update_signal_state()
            self.check_payment_status()  # Check for payments
            self.draw_traffic_signal(frame)
            self.draw_zones(frame)

            # Detect number plates
            plates = []
            if self.detection_active:
                plates = self.detect_number_plates(frame)

                for plate in plates:
                    if plate['plate_text']:
                        self.last_detected_plate = plate['plate_text']

                        if self.is_target_vehicle(plate['plate_text']):
                            print(f"🎯 TARGET VEHICLE SPOTTED: {self.target_plate}")
                            self.process_target_vehicle_detection(frame, plate)

            # Check for violations
            if self.signal_state == "red":
                self.check_red_light_violation(frame, plates)

            # Draw detected plates
            for plate in plates:
                x1, y1, x2, y2 = plate['bbox']

                if self.is_target_vehicle(plate['plate_text']):
                    color = (0, 255, 255)
                    label = "🎯 TARGET"
                else:
                    color = (0, 0, 255)
                    label = "Vehicle"

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)

                plate_text = plate['plate_text'] if plate['plate_text'] else f"Conf: {plate['confidence']:.2f}"
                cv2.putText(frame, f"{label}: {plate_text}", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            self.display_statistics(frame)
            cv2.imshow(f'Escalating Detection: {self.target_plate}', frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('t'):
                print("🧪 Testing detection escalation system...")
                self.target_detection_count += 1
                test_plate = {
                    'plate_text': self.target_plate,
                    'confidence': 0.95,
                    'bbox': (100, 100, 200, 200),
                    'center_y': 150
                }
                test_filename = "detections/test_detection.jpg"
                cv2.imwrite(test_filename, np.zeros((100, 100, 3), dtype=np.uint8))

                if self.target_detection_count == 1:
                    self.send_first_detection_notification(self.target_plate, 0.95, test_plate, test_filename)
                elif self.target_detection_count == 2:
                    self.send_second_detection_notification(self.target_plate, 0.95, test_plate, test_filename)
                else:
                    self.send_fine_notice(self.target_plate, 0.95, test_plate, test_filename, self.target_detection_count)

        self.cap.release()
        cv2.destroyAllWindows()
        pygame.mixer.quit()


def main():
    system = NumberPlateDetectionSystem()
    system.run()


if __name__ == "__main__":
    main()