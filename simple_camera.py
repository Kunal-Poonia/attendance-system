import cv2
import threading
import time
import logging

logger = logging.getLogger(__name__)

class SimpleCamera:
    def __init__(self, camera_index=0):
        self.camera_index = camera_index
        self.cap = None
        self.running = False
        self.current_frame = None
        self.lock = threading.Lock()
        
    def start_camera(self):
        """Start the camera"""
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                logger.error(f"Cannot open camera {self.camera_index}")
                return False
            
            # Set camera properties
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            
            self.running = True
            
            # Start frame capture thread
            self.capture_thread = threading.Thread(target=self._capture_frames)
            self.capture_thread.daemon = True
            self.capture_thread.start()
            
            logger.info(f"Camera {self.camera_index} started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error starting camera: {str(e)}")
            return False
    
    def _capture_frames(self):
        """Capture frames in a separate thread"""
        while self.running and self.cap and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
                if ret:
                    with self.lock:
                        self.current_frame = frame.copy()
                else:
                    logger.warning("Failed to read frame from camera")
                    break
                    
                time.sleep(0.033)  # ~30 FPS
                
            except Exception as e:
                logger.error(f"Error capturing frame: {str(e)}")
                break
    
    def get_frame(self):
        """Get the current frame"""
        with self.lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
            return None
    
    def get_frame_with_overlay(self):
        """Get frame with simple overlay text"""
        frame = self.get_frame()
        if frame is not None:
            # Add timestamp overlay
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, timestamp, (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            # Add status text
            cv2.putText(frame, "Camera Active - Manual Attendance Mode", (10, 60), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            
            return frame
        return None
    
    def stop_camera(self):
        """Stop the camera"""
        try:
            self.running = False
            
            if hasattr(self, 'capture_thread'):
                self.capture_thread.join(timeout=2)
            
            if self.cap:
                self.cap.release()
                self.cap = None
            
            with self.lock:
                self.current_frame = None
            
            logger.info("Camera stopped successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping camera: {str(e)}")
            return False
    
    def is_running(self):
        """Check if camera is running"""
        return self.running and self.cap and self.cap.isOpened()