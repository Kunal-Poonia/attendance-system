"""
Simple face encoder fallback using OpenCV
"""
import cv2
import numpy as np
import os

class FaceEncoder:
    def __init__(self, tolerance=0.6):
        self.tolerance = tolerance
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        print("FaceEncoder initialized with OpenCV fallback")
    
    def encode_face_from_image(self, image_path):
        """Extract face encoding from image"""
        try:
            if not os.path.exists(image_path):
                return None
            
            image = cv2.imread(image_path)
            if image is None:
                return None
            
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)
            
            if len(faces) == 0:
                return None
            
            # Use the largest face
            largest_face = max(faces, key=lambda f: f[2] * f[3])
            x, y, w, h = largest_face
            
            # Extract face region and resize to standard size
            face_roi = gray[y:y+h, x:x+w]
            face_roi = cv2.resize(face_roi, (100, 100))
            
            # Return flattened array as "encoding"
            return face_roi.flatten().astype(np.float32)
            
        except Exception as e:
            print(f"Error encoding face: {e}")
            return None