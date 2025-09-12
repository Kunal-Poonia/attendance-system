import os
import pandas as pd
from datetime import datetime, date
import logging
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

def allowed_file(filename, allowed_extensions={'png', 'jpg', 'jpeg', 'gif'}):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def save_uploaded_file(file, upload_folder, prefix=""):
    """Save uploaded file with secure filename"""
    try:
        if file and allowed_file(file.filename):
            # Create secure filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = secure_filename(file.filename)
            name, ext = os.path.splitext(filename)
            secure_name = f"{prefix}{timestamp}_{name}{ext}"
            
            filepath = os.path.join(upload_folder, secure_name)
            file.save(filepath)
            return filepath
        return None
    except Exception as e:
        logger.error(f"Error saving file: {str(e)}")
        return None

def export_attendance_to_csv(attendance_records, filename=None):
    """Export attendance records to CSV file"""
    try:
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"attendance_export_{timestamp}.csv"
        
        # Convert records to DataFrame
        data = []
        for record in attendance_records:
            data.append({
                'Student ID': record.student.student_id if record.student else 'N/A',
                'Name': record.student.name if record.student else 'N/A',
                'Department': record.student.department if record.student else 'N/A',
                'Year': record.student.year if record.student else 'N/A',
                'Section': record.student.section if record.student else 'N/A',
                'Date': record.date.strftime('%Y-%m-%d') if record.date else 'N/A',
                'Time In': record.time_in.strftime('%H:%M:%S') if record.time_in else 'N/A',
                'Time Out': record.time_out.strftime('%H:%M:%S') if record.time_out else 'N/A',
                'Status': record.status,
                'Confidence': f"{record.confidence_score:.2f}" if record.confidence_score else 'N/A'
            })
        
        df = pd.DataFrame(data)
        
        # Ensure exports directory exists
        os.makedirs('exports', exist_ok=True)
        filepath = os.path.join('exports', filename)
        
        df.to_csv(filepath, index=False)
        logger.info(f"Attendance exported to {filepath}")
        return filepath
        
    except Exception as e:
        logger.error(f"Error exporting to CSV: {str(e)}")
        return None

def export_attendance_to_excel(attendance_records, filename=None):
    """Export attendance records to Excel file"""
    try:
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"attendance_export_{timestamp}.xlsx"
        
        # Convert records to DataFrame
        data = []
        for record in attendance_records:
            data.append({
                'Student ID': record.student.student_id if record.student else 'N/A',
                'Name': record.student.name if record.student else 'N/A',
                'Department': record.student.department if record.student else 'N/A',
                'Year': record.student.year if record.student else 'N/A',
                'Section': record.student.section if record.student else 'N/A',
                'Date': record.date.strftime('%Y-%m-%d') if record.date else 'N/A',
                'Time In': record.time_in.strftime('%H:%M:%S') if record.time_in else 'N/A',
                'Time Out': record.time_out.strftime('%H:%M:%S') if record.time_out else 'N/A',
                'Status': record.status,
                'Confidence': f"{record.confidence_score:.2f}" if record.confidence_score else 'N/A'
            })
        
        df = pd.DataFrame(data)
        
        # Ensure exports directory exists
        os.makedirs('exports', exist_ok=True)
        filepath = os.path.join('exports', filename)
        
        # Create Excel writer with formatting
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Attendance', index=False)
            
            # Get workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Attendance']
            
            # Auto-adjust column widths
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        logger.info(f"Attendance exported to {filepath}")
        return filepath
        
    except Exception as e:
        logger.error(f"Error exporting to Excel: {str(e)}")
        return None

def generate_attendance_summary(attendance_records):
    """Generate attendance summary statistics"""
    try:
        if not attendance_records:
            return {}
        
        total_records = len(attendance_records)
        present_count = sum(1 for record in attendance_records if record.status == 'Present')
        absent_count = sum(1 for record in attendance_records if record.status == 'Absent')
        late_count = sum(1 for record in attendance_records if record.status == 'Late')
        
        # Calculate percentages
        present_percentage = (present_count / total_records) * 100 if total_records > 0 else 0
        absent_percentage = (absent_count / total_records) * 100 if total_records > 0 else 0
        late_percentage = (late_count / total_records) * 100 if total_records > 0 else 0
        
        # Get date range
        dates = [record.date for record in attendance_records if record.date]
        date_range = {
            'start_date': min(dates) if dates else None,
            'end_date': max(dates) if dates else None
        }
        
        return {
            'total_records': total_records,
            'present_count': present_count,
            'absent_count': absent_count,
            'late_count': late_count,
            'present_percentage': round(present_percentage, 2),
            'absent_percentage': round(absent_percentage, 2),
            'late_percentage': round(late_percentage, 2),
            'date_range': date_range
        }
        
    except Exception as e:
        logger.error(f"Error generating summary: {str(e)}")
        return {}

def validate_student_data(data):
    """Validate student registration data"""
    errors = []
    
    # Required fields
    required_fields = ['student_id', 'name', 'email', 'department']
    for field in required_fields:
        if not data.get(field):
            errors.append(f"{field.replace('_', ' ').title()} is required")
    
    # Email validation (basic)
    email = data.get('email', '')
    if email and '@' not in email:
        errors.append("Invalid email format")
    
    # Student ID validation
    student_id = data.get('student_id', '')
    if student_id and len(student_id) < 3:
        errors.append("Student ID must be at least 3 characters")
    
    return errors

def format_datetime(dt):
    """Format datetime for display"""
    if not dt:
        return 'N/A'
    
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except:
            return dt
    
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def format_date(d):
    """Format date for display"""
    if not d:
        return 'N/A'
    
    if isinstance(d, str):
        try:
            d = datetime.strptime(d, '%Y-%m-%d').date()
        except:
            return d
    
    return d.strftime('%Y-%m-%d')

def get_attendance_status(time_in, late_threshold_minutes=15):
    """Determine attendance status based on time in"""
    if not time_in:
        return 'Absent'
    
    # Assuming class starts at 9:00 AM
    class_start_time = time_in.replace(hour=9, minute=0, second=0, microsecond=0)
    
    if time_in <= class_start_time:
        return 'Present'
    elif time_in <= class_start_time.replace(minute=late_threshold_minutes):
        return 'Late'
    else:
        return 'Absent'

def create_directory_structure():
    """Create necessary directory structure for the application"""
    directories = [
        'static/uploads',
        'static/css',
        'static/js',
        'static/images',
        'student_images',
        'exports',
        'database',
        'logs'
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        logger.info(f"Directory created/verified: {directory}")

def setup_logging():
    """Setup logging configuration"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Create logs directory
    os.makedirs('logs', exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler('logs/app.log'),
            logging.StreamHandler()
        ]
    )