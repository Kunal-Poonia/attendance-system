from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
import cv2
import os
import json
import base64
from datetime import datetime, date, timedelta
import threading
import time
import logging

# Import custom modules
from config import Config
from database.models import db, Student, AttendanceRecord, AttendanceSession
from simple_camera import SimpleCamera

# Try to import face recognition modules (graceful fallback if not available)
try:
    from face_recognition.face_encoder import FaceEncoder
    from face_recognition.face_detector import FaceDetector
    FACE_RECOGNITION_AVAILABLE = True
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.warning(f"Face recognition not available: {str(e)}")
    FaceEncoder = None
    FaceDetector = None
    FACE_RECOGNITION_AVAILABLE = False
from utils.helpers import (
    save_uploaded_file, export_attendance_to_csv, export_attendance_to_excel,
    generate_attendance_summary, validate_student_data, create_directory_structure,
    setup_logging, get_attendance_status
)

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize database
db.init_app(app)

# Initialize components
simple_camera = SimpleCamera(camera_index=0)
detection_active = False
face_recognition_active = False

# Initialize face recognition components if available
if FACE_RECOGNITION_AVAILABLE:
    face_encoder = FaceEncoder(tolerance=app.config.get('FACE_RECOGNITION_TOLERANCE', 0.6))
    face_detector = FaceDetector(camera_index=0, tolerance=app.config.get('FACE_RECOGNITION_TOLERANCE', 0.6))
else:
    face_encoder = None
    face_detector = None

# Create directory structure
Config.init_app(app)
create_directory_structure()

def create_tables():
    """Create database tables"""
    with app.app_context():
        db.create_all()
        logger.info("Database tables created")

# Initialize database tables
create_tables()

# Add datetime to template context
@app.context_processor
def inject_datetime():
    return {'datetime': datetime, 'date': date}

# Routes
@app.route('/')
def index():
    """Main dashboard"""
    try:
        # Get statistics
        total_students = Student.query.filter_by(is_active=True).count()
        today = date.today()
        today_attendance = AttendanceRecord.query.filter_by(date=today).count()
        
        # Get recent attendance records
        recent_records = AttendanceRecord.query.order_by(
            AttendanceRecord.created_at.desc()
        ).limit(10).all()
        
        return render_template('index.html', 
                             total_students=total_students,
                             today_attendance=today_attendance,
                             recent_records=recent_records)
    except Exception as e:
        logger.error(f"Error in index route: {str(e)}")
        flash('Error loading dashboard', 'error')
        return render_template('index.html')

@app.route('/students')
def students():
    """Student management page"""
    try:
        students = Student.query.filter_by(is_active=True).all()
        return render_template('students.html', students=students)
    except Exception as e:
        logger.error(f"Error in students route: {str(e)}")
        flash('Error loading students', 'error')
        return render_template('students.html', students=[])

@app.route('/register_student', methods=['GET', 'POST'])
def register_student():
    """Register new student"""
    if request.method == 'GET':
        return render_template('register_student.html')
    
    try:
        # Get form data
        data = {
            'student_id': request.form.get('student_id'),
            'name': request.form.get('name'),
            'email': request.form.get('email'),
            'phone': request.form.get('phone'),
            'department': request.form.get('department'),
            'year': request.form.get('year'),
            'section': request.form.get('section')
        }
        
        # Validate data
        errors = validate_student_data(data)
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register_student.html', data=data)
        
        # Check if student already exists
        existing_student = Student.query.filter_by(student_id=data['student_id']).first()
        if existing_student:
            flash('Student ID already exists', 'error')
            return render_template('register_student.html', data=data)
        
        # Handle image upload
        if 'image' not in request.files:
            flash('Student photo is required', 'error')
            return render_template('register_student.html', data=data)
        
        file = request.files['image']
        if file.filename == '':
            flash('No image selected', 'error')
            return render_template('register_student.html', data=data)
        
        # Save uploaded image
        image_path = save_uploaded_file(
            file, 
            app.config['STUDENT_IMAGES_FOLDER'],
            f"student_{data['student_id']}_"
        )
        
        if not image_path:
            flash('Error uploading image', 'error')
            return render_template('register_student.html', data=data)
        
        # Extract face encoding (if face recognition is available)
        face_encoding = None
        if FACE_RECOGNITION_AVAILABLE and face_encoder:
            face_encoding = face_encoder.encode_face_from_image(image_path)
            if face_encoding is None:
                flash('No face detected in the image. Please upload a clear photo.', 'error')
                os.remove(image_path)  # Remove uploaded file
                return render_template('register_student.html', data=data)
        
        # Create new student
        student = Student(
            student_id=data['student_id'],
            name=data['name'],
            email=data['email'],
            phone=data['phone'],
            department=data['department'],
            year=data['year'],
            section=data['section'],
            image_path=image_path
        )
        
        if face_encoding is not None:
            student.set_face_encoding(face_encoding)
        
        db.session.add(student)
        db.session.commit()
        
        flash('Student registered successfully!', 'success')
        logger.info(f"Student registered: {data['student_id']} - {data['name']}")
        return redirect(url_for('students'))
        
    except Exception as e:
        logger.error(f"Error registering student: {str(e)}")
        flash('Error registering student', 'error')
        return render_template('register_student.html')

@app.route('/attendance')
def attendance():
    """Attendance management page"""
    try:
        # Get filter parameters
        date_filter = request.args.get('date', date.today().isoformat())
        department_filter = request.args.get('department', '')
        year_filter = request.args.get('year', '')
        
        # Build query
        query = AttendanceRecord.query
        
        if date_filter:
            query = query.filter(AttendanceRecord.date == date_filter)
        
        if department_filter:
            query = query.join(Student).filter(Student.department == department_filter)
        
        if year_filter:
            query = query.join(Student).filter(Student.year == year_filter)
        
        records = query.order_by(AttendanceRecord.created_at.desc()).all()
        
        # Get unique departments and years for filters
        departments = db.session.query(Student.department).distinct().all()
        years = db.session.query(Student.year).distinct().all()
        
        return render_template('attendance.html', 
                             records=records,
                             departments=[d[0] for d in departments if d[0]],
                             years=[y[0] for y in years if y[0]],
                             current_date=date_filter,
                             current_department=department_filter,
                             current_year=year_filter)
    except Exception as e:
        logger.error(f"Error in attendance route: {str(e)}")
        flash('Error loading attendance records', 'error')
        return render_template('attendance.html', records=[])

@app.route('/mark_attendance')
def mark_attendance():
    """Face recognition attendance marking page"""
    return render_template('mark_attendance.html')

@app.route('/start_detection', methods=['POST'])
def start_detection():
    """Start camera detection"""
    global simple_camera, detection_active
    
    try:
        if detection_active:
            return jsonify({'success': False, 'message': 'Camera already active'})
        
        # Start simple camera
        if simple_camera.start_camera():
            detection_active = True
            logger.info("Camera started successfully")
            return jsonify({'success': True, 'message': 'Camera started successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to start camera. Please check if camera is available.'})
            
    except Exception as e:
        logger.error(f"Error starting camera: {str(e)}")
        return jsonify({'success': False, 'message': f'Camera error: {str(e)}'})

@app.route('/start_face_recognition', methods=['POST'])
def start_face_recognition():
    """Start face recognition detection"""
    global face_detector, face_recognition_active
    
    try:
        if not FACE_RECOGNITION_AVAILABLE:
            return jsonify({'success': False, 'message': 'Face recognition libraries not installed. Please run setup_face_recognition.py'})
        
        if face_recognition_active:
            return jsonify({'success': False, 'message': 'Face recognition already active'})
        
        if not face_detector:
            return jsonify({'success': False, 'message': 'Face detector not initialized'})
        
        # Load known faces from database
        students = Student.query.filter_by(is_active=True).all()
        students_data = []
        
        for student in students:
            face_encoding = student.get_face_encoding()
            if face_encoding is not None:
                students_data.append({
                    'id': student.id,
                    'name': student.name,
                    'student_id': student.student_id,
                    'face_encoding': face_encoding
                })
        
        if not students_data:
            return jsonify({'success': False, 'message': 'No students with face encodings found. Please register students first.'})
        
        # Load known faces into detector
        face_detector.load_known_faces(students_data)
        
        # Start face detection
        if face_detector.start_detection():
            face_recognition_active = True
            logger.info(f"Face recognition started with {len(students_data)} known faces")
            return jsonify({'success': True, 'message': f'Face recognition started with {len(students_data)} known faces'})
        else:
            return jsonify({'success': False, 'message': 'Failed to start face recognition'})
            
    except Exception as e:
        logger.error(f"Error starting face recognition: {str(e)}")
        return jsonify({'success': False, 'message': f'Face recognition error: {str(e)}'})

@app.route('/stop_detection', methods=['POST'])
def stop_detection():
    """Stop camera detection"""
    global simple_camera, detection_active
    
    try:
        if simple_camera:
            simple_camera.stop_camera()
        
        detection_active = False
        logger.info("Camera stopped")
        return jsonify({'success': True, 'message': 'Camera stopped'})
        
    except Exception as e:
        logger.error(f"Error stopping camera: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/stop_face_recognition', methods=['POST'])
def stop_face_recognition():
    """Stop face recognition detection"""
    global face_detector, face_recognition_active
    
    try:
        if FACE_RECOGNITION_AVAILABLE and face_detector:
            face_detector.stop_detection()
        
        face_recognition_active = False
        logger.info("Face recognition stopped")
        return jsonify({'success': True, 'message': 'Face recognition stopped'})
        
    except Exception as e:
        logger.error(f"Error stopping face recognition: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/get_video_feed')
def get_video_feed():
    """Get video feed from camera"""
    def generate_frames():
        global simple_camera, face_detector, detection_active, face_recognition_active
        
        while (detection_active or face_recognition_active):
            try:
                frame = None
                
                # Use face recognition feed if active
                if face_recognition_active and FACE_RECOGNITION_AVAILABLE and face_detector:
                    frame = face_detector.get_current_frame_with_annotations()
                
                # Fallback to simple camera
                if frame is None and detection_active and simple_camera and simple_camera.is_running():
                    frame = simple_camera.get_frame_with_overlay()
                
                if frame is not None:
                    # Encode frame as JPEG
                    ret, buffer = cv2.imencode('.jpg', frame)
                    if ret:
                        frame_bytes = buffer.tobytes()
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                
                time.sleep(0.033)  # ~30 FPS
                
            except Exception as e:
                logger.error(f"Error in video feed: {str(e)}")
                break
    
    from flask import Response
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/get_detected_faces')
def get_detected_faces():
    """Get currently detected faces"""
    try:
        global face_detector, face_recognition_active
        
        if face_recognition_active and FACE_RECOGNITION_AVAILABLE and face_detector:
            detected_faces = face_detector.get_detected_faces()
            
            # Format faces for frontend
            faces_data = []
            for face in detected_faces:
                faces_data.append({
                    'student_id': face['student_id'],
                    'name': face['name'],
                    'confidence': round(float(face['confidence']), 2),
                    'location': [int(x) for x in face['location']],
                    'timestamp': face['timestamp'].isoformat()
                })
            
            return jsonify({'faces': faces_data})
        else:
            return jsonify({'faces': []})
        
    except Exception as e:
        logger.error(f"Error getting detected faces: {str(e)}")
        return jsonify({'faces': []})

@app.route('/mark_manual_attendance', methods=['POST'])
def mark_manual_attendance():
    """Mark attendance manually using student ID"""
    try:
        student_id = request.form.get('student_id')
        
        if not student_id:
            flash('Student ID is required', 'error')
            return redirect(url_for('mark_attendance'))
        
        # Get student by student_id (not database ID)
        student = Student.query.filter_by(student_id=student_id, is_active=True).first()
        if not student:
            flash(f'Student with ID {student_id} not found', 'error')
            return redirect(url_for('mark_attendance'))
        
        # Check if already marked present today
        today = date.today()
        existing_record = AttendanceRecord.query.filter_by(
            student_id=student.id,  # Use database ID for the record
            date=today
        ).first()
        
        if existing_record:
            flash(f'{student.name} already marked present today', 'warning')
            return redirect(url_for('mark_attendance'))
        
        # Create attendance record
        now = datetime.now()
        # For manual attendance marking, always mark as Present
        status = 'Present'
        
        attendance_record = AttendanceRecord(
            student_id=student.id,  # Use database ID
            date=today,
            time_in=now,
            status=status,
            confidence_score=1.0  # Manual entry gets 100% confidence
        )
        
        db.session.add(attendance_record)
        db.session.commit()
        
        logger.info(f"Manual attendance marked: {student.name} ({student.student_id}) - {status}")
        flash(f'{student.name} marked {status.lower()} at {now.strftime("%H:%M:%S")}', 'success')
        
        return redirect(url_for('mark_attendance'))
        
    except Exception as e:
        logger.error(f"Error marking manual attendance: {str(e)}")
        flash('Error marking attendance', 'error')
        return redirect(url_for('mark_attendance'))

@app.route('/mark_student_present', methods=['POST'])
def mark_student_present():
    """Mark detected student as present"""
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        confidence = data.get('confidence', 0)
        
        if not student_id:
            return jsonify({'success': False, 'message': 'Student ID required'})
        
        # Get student
        student = Student.query.get(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'})
        
        # Check if already marked present today
        today = date.today()
        existing_record = AttendanceRecord.query.filter_by(
            student_id=student_id,
            date=today
        ).first()
        
        if existing_record:
            return jsonify({
                'success': False, 
                'message': f'{student.name} already marked present today'
            })
        
        # Create attendance record
        now = datetime.now()
        # When manually marking a student present, always mark as Present
        status = 'Present'
        
        attendance_record = AttendanceRecord(
            student_id=student_id,
            date=today,
            time_in=now,
            status=status,
            confidence_score=confidence
        )
        
        db.session.add(attendance_record)
        db.session.commit()
        
        logger.info(f"Attendance marked: {student.name} ({student.student_id}) - {status}")
        
        return jsonify({
            'success': True,
            'message': f'{student.name} marked {status.lower()}',
            'student_name': student.name,
            'status': status,
            'time': now.strftime('%H:%M:%S')
        })
        
    except Exception as e:
        logger.error(f"Error marking attendance: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/auto_mark_attendance', methods=['POST'])
def auto_mark_attendance():
    """Automatically mark attendance for detected faces"""
    try:
        global face_detector, face_recognition_active
        
        if not FACE_RECOGNITION_AVAILABLE:
            return jsonify({'success': False, 'message': 'Face recognition not available'})
        
        if not face_recognition_active or not face_detector:
            return jsonify({'success': False, 'message': 'Face recognition not active'})
        
        detected_faces = face_detector.get_detected_faces()
        marked_students = []
        
        logger.info(f"Auto mark: Found {len(detected_faces)} detected faces")
        
        for face in detected_faces:
            logger.info(f"Face: {face['name']}, ID: {face['student_id']}, Confidence: {face['confidence']}")
            if face['student_id'] and face['confidence'] > 0.3:  # Lower confidence threshold
                student = Student.query.get(face['student_id'])
                if not student:
                    continue
                
                # Check if already marked present today
                today = date.today()
                existing_record = AttendanceRecord.query.filter_by(
                    student_id=face['student_id'],
                    date=today
                ).first()
                
                if existing_record:
                    continue  # Skip if already marked
                
                # Create attendance record
                now = datetime.now()
                status = 'Present'  # Default status for auto-marked attendance
                
                attendance_record = AttendanceRecord(
                    student_id=face['student_id'],
                    date=today,
                    time_in=now,
                    status=status,
                    confidence_score=face['confidence']
                )
                
                db.session.add(attendance_record)
                marked_students.append({
                    'name': student.name,
                    'student_id': student.student_id,
                    'status': status,
                    'confidence': face['confidence']
                })
        
        if marked_students:
            db.session.commit()
            logger.info(f"Auto-marked attendance for {len(marked_students)} students")
            
            return jsonify({
                'success': True,
                'message': f'Marked {len(marked_students)} students present',
                'marked_students': marked_students
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No new students to mark present'
            })
        
    except Exception as e:
        logger.error(f"Error in auto attendance marking: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/export_attendance')
def export_attendance():
    """Export attendance records"""
    try:
        format_type = request.args.get('format', 'csv')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        # Build query
        query = AttendanceRecord.query
        
        if date_from:
            query = query.filter(AttendanceRecord.date >= date_from)
        
        if date_to:
            query = query.filter(AttendanceRecord.date <= date_to)
        
        records = query.order_by(AttendanceRecord.date.desc()).all()
        
        if not records:
            flash('No records found for export', 'warning')
            return redirect(url_for('attendance'))
        
        # Export based on format
        if format_type == 'excel':
            filepath = export_attendance_to_excel(records)
        else:
            filepath = export_attendance_to_csv(records)
        
        if filepath and os.path.exists(filepath):
            return send_file(filepath, as_attachment=True)
        else:
            flash('Error exporting attendance', 'error')
            return redirect(url_for('attendance'))
            
    except Exception as e:
        logger.error(f"Error exporting attendance: {str(e)}")
        flash('Error exporting attendance', 'error')
        return redirect(url_for('attendance'))

@app.route('/reports')
def reports():
    """Attendance reports and analytics"""
    try:
        # Get date range from query parameters
        date_from = request.args.get('date_from', (date.today() - timedelta(days=30)).isoformat())
        date_to = request.args.get('date_to', date.today().isoformat())
        
        # Get attendance records for the date range
        records = AttendanceRecord.query.filter(
            AttendanceRecord.date >= date_from,
            AttendanceRecord.date <= date_to
        ).all()
        
        # Generate summary
        summary = generate_attendance_summary(records)
        
        # Get department-wise statistics
        dept_stats = {}
        for record in records:
            if record.student and record.student.department:
                dept = record.student.department
                if dept not in dept_stats:
                    dept_stats[dept] = {'present': 0, 'absent': 0, 'late': 0, 'total': 0}
                
                dept_stats[dept][record.status.lower()] += 1
                dept_stats[dept]['total'] += 1
        
        return render_template('reports.html', 
                             summary=summary,
                             dept_stats=dept_stats,
                             date_from=date_from,
                             date_to=date_to)
        
    except Exception as e:
        logger.error(f"Error in reports route: {str(e)}")
        flash('Error loading reports', 'error')
        return render_template('reports.html')

@app.route('/api/student/<int:student_id>')
def get_student(student_id):
    """Get student details API"""
    try:
        student = Student.query.get_or_404(student_id)
        return jsonify(student.to_dict())
    except Exception as e:
        logger.error(f"Error getting student: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/attendance_summary')
def attendance_summary_api():
    """Get attendance summary API"""
    try:
        today = date.today()
        records = AttendanceRecord.query.filter_by(date=today).all()
        summary = generate_attendance_summary(records)
        return jsonify(summary)
    except Exception as e:
        logger.error(f"Error getting attendance summary: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/today_attendance')
def today_attendance_api():
    """Get today's attendance records API"""
    try:
        today = date.today()
        records = AttendanceRecord.query.filter_by(date=today).order_by(
            AttendanceRecord.created_at.desc()
        ).limit(10).all()
        
        attendance_data = []
        for record in records:
            attendance_data.append({
                'student_name': record.student.name,
                'student_id': record.student.student_id,
                'time': record.time_in.strftime('%H:%M:%S'),
                'status': record.status
            })
        
        return jsonify({
            'date': today.strftime('%Y-%m-%d'),
            'total_present': len(records),
            'records': attendance_data
        })
    except Exception as e:
        logger.error(f"Error getting today's attendance: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/face_recognition_status')
def face_recognition_status():
    """Get face recognition availability status"""
    return jsonify({
        'available': FACE_RECOGNITION_AVAILABLE,
        'active': face_recognition_active,
        'camera_active': detection_active
    })

@app.route('/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    """Delete a student (soft delete)"""
    try:
        student = Student.query.get_or_404(student_id)
        student_name = student.name
        
        # Soft delete - just mark as inactive
        student.is_active = False
        db.session.commit()
        
        flash(f'Student {student_name} deleted successfully', 'success')
        logger.info(f"Student deleted: {student_name} (ID: {student_id})")
        
        return jsonify({
            'success': True,
            'message': f'Student {student_name} deleted successfully'
        })
        
    except Exception as e:
        logger.error(f"Error deleting student: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error deleting student: {str(e)}'
        }), 500

@app.route('/permanently_delete_student/<int:student_id>', methods=['POST'])
def permanently_delete_student(student_id):
    """Permanently delete a student and all records"""
    try:
        student = Student.query.get_or_404(student_id)
        student_name = student.name
        
        # Delete attendance records first
        AttendanceRecord.query.filter_by(student_id=student_id).delete()
        
        # Delete student image if exists
        if student.image_path and os.path.exists(student.image_path):
            os.remove(student.image_path)
        
        # Delete student record
        db.session.delete(student)
        db.session.commit()
        
        flash(f'Student {student_name} permanently deleted', 'success')
        logger.info(f"Student permanently deleted: {student_name} (ID: {student_id})")
        
        return jsonify({
            'success': True,
            'message': f'Student {student_name} permanently deleted'
        })
        
    except Exception as e:
        logger.error(f"Error permanently deleting student: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error permanently deleting student: {str(e)}'
        }), 500

@app.route('/update_attendance_status', methods=['POST'])
def update_attendance_status():
    """Update attendance status for a student"""
    try:
        data = request.get_json()
        record_id = data.get('record_id')
        new_status = data.get('status')
        
        if not record_id or not new_status:
            return jsonify({
                'success': False,
                'message': 'Record ID and status are required'
            }), 400
        
        # Validate status
        valid_statuses = ['Present', 'Absent', 'Late', 'Excused']
        if new_status not in valid_statuses:
            return jsonify({
                'success': False,
                'message': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'
            }), 400
        
        # Get attendance record
        attendance_record = AttendanceRecord.query.get_or_404(record_id)
        student = attendance_record.student
        
        if not student:
            return jsonify({
                'success': False,
                'message': 'Student not found for this record'
            }), 404
        
        # Update record status
        old_status = attendance_record.status
        attendance_record.status = new_status
        
        db.session.commit()
        
        logger.info(f"Attendance status updated: {student.name} {old_status} -> {new_status}")
        
        return jsonify({
            'success': True,
            'message': f'Updated {student.name} status from {old_status} to {new_status}',
            'student_name': student.name,
            'status': new_status
        })
        
    except Exception as e:
        logger.error(f"Error updating attendance status: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error updating status: {str(e)}'
        }), 500

@app.route('/mark_student_status/<int:student_id>/<status>', methods=['POST'])
def mark_student_status(student_id, status):
    """Quick mark student status (Present/Absent/Late)"""
    try:
        # Validate status
        valid_statuses = ['Present', 'Absent', 'Late', 'Excused']
        if status not in valid_statuses:
            return jsonify({
                'success': False,
                'message': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'
            }), 400
        
        # Get student
        student = Student.query.get(student_id)
        if not student:
            return jsonify({
                'success': False,
                'message': 'Student not found'
            }), 404
        
        # Check if attendance record exists for today
        today = date.today()
        attendance_record = AttendanceRecord.query.filter_by(
            student_id=student_id,
            date=today
        ).first()
        
        if attendance_record:
            # Update existing record
            attendance_record.status = status
            message = f'Updated {student.name} status to {status}'
        else:
            # Create new record
            attendance_record = AttendanceRecord(
                student_id=student_id,
                date=today,
                time_in=datetime.now(),
                status=status,
                marked_by='Manual'
            )
            db.session.add(attendance_record)
            message = f'Marked {student.name} as {status}'
        
        db.session.commit()
        
        logger.info(f"Student status marked: {student.name} -> {status}")
        flash(message, 'success')
        
        return jsonify({
            'success': True,
            'message': message,
            'student_name': student.name,
            'status': status
        })
        
    except Exception as e:
        logger.error(f"Error marking student status: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error marking status: {str(e)}'
        }), 500

@app.route('/mark_time_out/<int:record_id>', methods=['POST'])
def mark_time_out(record_id):
    """Mark time out for an attendance record"""
    try:
        record = AttendanceRecord.query.get_or_404(record_id)
        
        if record.time_out:
            return jsonify({
                'success': False,
                'message': 'Time out already marked for this record'
            }), 400
        
        record.time_out = datetime.now()
        db.session.commit()
        
        logger.info(f"Time out marked for record ID: {record_id}")
        
        return jsonify({
            'success': True,
            'message': f'Time out marked at {record.time_out.strftime("%H:%M:%S")}'
        })
        
    except Exception as e:
        logger.error(f"Error marking time out: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error marking time out: {str(e)}'
        }), 500

@app.route('/delete_attendance/<int:record_id>', methods=['POST'])
def delete_attendance(record_id):
    """Delete an attendance record"""
    try:
        record = AttendanceRecord.query.get_or_404(record_id)
        student_name = record.student.name if record.student else 'Unknown'
        
        db.session.delete(record)
        db.session.commit()
        
        logger.info(f"Attendance record deleted: {student_name} (Record ID: {record_id})")
        
        return jsonify({
            'success': True,
            'message': f'Attendance record for {student_name} deleted successfully'
        })
        
    except Exception as e:
        logger.error(f"Error deleting attendance record: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error deleting record: {str(e)}'
        }), 500

if __name__ == '__main__':
    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    finally:
        # Cleanup on exit
        if simple_camera:
            simple_camera.stop_camera()
        if FACE_RECOGNITION_AVAILABLE and face_detector:
            face_detector.stop_detection()