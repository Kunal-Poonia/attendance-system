"""
Simple face detector fallback using OpenCV
"""
import cv2
import numpy as np
import threading
import time
from datetime import datetime

class FaceDetector:
    def __init__(self, camera_index=0, tolerance=0.6):
        self.camera_index = camera_index
        self.tolerance = tolerance
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        # Camera and detection state
        self.cap = None
        self.is_running = False
        self.current_frame = None
        self.detected_faces = []
        self.known_faces = []
        
        # Threading
        self.capture_thread = None
        self.detection_thread = None
        self.thread_lock = threading.Lock()
        
        print("FaceDetector initialized with OpenCV fallback")
    
    def load_known_faces(self, students_data):
        """Load known faces from student data"""
        self.known_faces = []
        for student in students_data:
            self.known_faces.append({
                'id': student['id'],
                'name': student['name'],
                'student_id': student['student_id'],
                'face_encoding': student['face_encoding']
            })
        print(f"Loaded {len(self.known_faces)} known faces")
    
    def start_detection(self):
        """Start face detection"""
        try:
            if self.is_running:
                return True
            
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                return False
            
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            
            self.is_running = True
            
            self.capture_thread = threading.Thread(target=self._capture_frames)
            self.capture_thread.daemon = True
            self.capture_thread.start()
            
            self.detection_thread = threading.Thread(target=self._detect_faces)
            self.detection_thread.daemon = True
            self.detection_thread.start()
            
            return True
            
        except Exception as e:
            print(f"Error starting detection: {e}")
            return False
    
    def stop_detection(self):
        """Stop face detection"""
        try:
            self.is_running = False
            
            if self.capture_thread:
                self.capture_thread.join(timeout=2)
            if self.detection_thread:
                self.detection_thread.join(timeout=2)
            
            if self.cap:
                self.cap.release()
                self.cap = None
            
            with self.thread_lock:
                self.detected_faces = []
                self.current_frame = None
            
            return True
            
        except Exception as e:
            print(f"Error stopping detection: {e}")
            return False
    
    def _capture_frames(self):
        """Capture frames from camera"""
        while self.is_running and self.cap:
            try:
                ret, frame = self.cap.read()
                if ret:
                    with self.thread_lock:
                        self.current_frame = frame.copy()
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"Error capturing frame: {e}")
                time.sleep(0.1)
    
    def _detect_faces(self):
        """Detect and recognize faces"""
        while self.is_running:
            try:
                with self.thread_lock:
                    if self.current_frame is None:
                        time.sleep(0.1)
                        continue
                    frame = self.current_frame.copy()
                
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)
                
                detected_faces_data = []
                
                for (x, y, w, h) in faces:
                    face_roi = gray[y:y+h, x:x+w]
                    face_roi = cv2.resize(face_roi, (100, 100))
                    face_encoding = face_roi.flatten().astype(np.float32)
                    
                    # Simple face matching (placeholder)
                    best_match = None
                    best_confidence = 0
                    
                    for known_face in self.known_faces:
                        if known_face['face_encoding'] is not None:
                            # Simple correlation-based matching
                            correlation = np.corrcoef(face_encoding, known_face['face_encoding'])[0, 1]
                            if not np.isnan(correlation) and correlation > best_confidence and correlation > 0.3:
                                best_confidence = correlation
                                best_match = known_face
                    
                    if best_match:
                        detected_faces_data.append({
                            'student_id': best_match['id'],
                            'name': best_match['name'],
                            'confidence': best_confidence,
                            'location': (x, y, w, h),
                            'timestamp': datetime.now()
                        })
                    else:
                        detected_faces_data.append({
                            'student_id': None,
                            'name': 'Unknown',
                            'confidence': 0,
                            'location': (x, y, w, h),
                            'timestamp': datetime.now()
                        })
                
                with self.thread_lock:
                    self.detected_faces = detected_faces_data
                
                time.sleep(0.2)
                
            except Exception as e:
                print(f"Error in face detection: {e}")
                time.sleep(0.5)
    
    def get_current_frame_with_annotations(self):
        """Get current frame with face detection annotations"""
        try:
            with self.thread_lock:
                if self.current_frame is None:
                    return None
                
                frame = self.current_frame.copy()
                detected_faces = self.detected_faces.copy()
            
            for face in detected_faces:
                x, y, w, h = face['location']
                
                if face['student_id']:
                    color = (0, 255, 0)  # Green
                    label = f"{face['name']} ({face['confidence']:.1%})"
                else:
                    color = (0, 0, 255)  # Red
                    label = "Unknown"
                
                cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
                cv2.rectangle(frame, (x, y-30), (x+w, y), color, -1)
                cv2.putText(frame, label, (x+5, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            
            return frame
            
        except Exception as e:
            print(f"Error annotating frame: {e}")
            return self.current_frame if self.current_frame is not None else None
    
    def get_detected_faces(self):
        """Get currently detected faces"""
        with self.thread_lock:
            return self.detected_faces.copy()