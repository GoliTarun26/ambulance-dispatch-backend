from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import mysql.connector.pooling
import math
import traceback
import requests
from datetime import datetime
import os


app = Flask(__name__)
CORS(app)

# -------------------- MySQL Connection Pool --------------------
''' dbconfig = {
    "host": "localhost",
    "user": "root",
    "password": "0826",
    "database": "ambulance_dispatch"
}

pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="ambulance_pool",
    pool_size=5,
    **dbconfig
) '''

pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="mypool",
    pool_size=5,
    host=os.environ.get("DB_HOST"),
    user=os.environ.get("DB_USER"),
    password=os.environ.get("DB_PASSWORD"),
    database=os.environ.get("DB_NAME")
)

# -------------------- GraphHopper API Key --------------------
GRAPH_HOPPER_KEY = "c8e3e007-a97c-4e74-b432-94892c8fe7e3"

# -------------------- Helper Functions --------------------
def get_db_connection():
    return pool.get_connection()

def haversine(lat1, lon1, lat2, lon2):
    r = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return round(r * c, 2)

def get_graphhopper_distance(lat1, lon1, lat2, lon2):
    try:
        url = (
            f"https://graphhopper.com/api/1/route?"
            f"point={lat1},{lon1}&point={lat2},{lon2}"
            f"&vehicle=car&locale=en&calc_points=false&key={GRAPH_HOPPER_KEY}"
        )
        response = requests.get(url)
        data = response.json()

        if "paths" in data and len(data["paths"]) > 0:
            distance_m = data["paths"][0]["distance"]
            time_ms = data["paths"][0]["time"]
            distance_km = round(distance_m / 1000, 2)
            eta_min = round(time_ms / (1000 * 60))
            return distance_km, eta_min
        else:
            return None, None
    except Exception as e:
        print("GraphHopper Error:", e)
        return None, None

def assign_nearest_ambulance(req_id):
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        #  Get emergency coordinates (user location from browser)
        cursor.execute("SELECT latitude, longitude FROM emergency_requests WHERE request_id=%s", (req_id,))
        request_row = cursor.fetchone()
        if not request_row:
            return None
        req_lat, req_lon = float(request_row["latitude"]), float(request_row["longitude"])

        #  Get available ambulances WITH their drivers and ambulance locations FROM DATABASE
        cursor.execute("""
            SELECT a.*, d.driver_id, d.name as driver_name 
            FROM ambulances a 
            JOIN drivers d ON a.ambulance_id = d.ambulance_id 
            WHERE a.status='available' AND d.status='available'
        """)
        ambulances = cursor.fetchall()
        
        if not ambulances:
            return None

        #  Use ambulance locations FROM DATABASE (not browser)
        for amb in ambulances:
            amb['latitude'] = float(amb['latitude'])  # From database
            amb['longitude'] = float(amb['longitude'])  # From database

        # Quick Haversine filter (nearest 3 ambulances)
        ambulances.sort(key=lambda amb: haversine(req_lat, req_lon, amb['latitude'], amb['longitude']))
        candidates = ambulances[:3]

        #  Use GraphHopper to select real nearest by road
        best_amb = None
        best_eta = float('inf')

        for amb in candidates:
            # Use ambulance location FROM DATABASE and user location from browser
            distance, eta = get_graphhopper_distance(req_lat, req_lon, amb['latitude'], amb['longitude'])
            if distance is None:
                distance = haversine(req_lat, req_lon, amb['latitude'], amb['longitude'])
                eta = round((distance / 50) * 60)
            if eta < best_eta:
                best_eta = eta
                best_amb = {
                    "id": amb["ambulance_id"],
                    "plate": amb["plate_number"],
                    "distance": distance,
                    "eta": eta,
                    "driver_id": amb["driver_id"],
                    "driver_name": amb["driver_name"],
                    "ambulance_lat": amb["latitude"],  # Store ambulance location
                    "ambulance_lon": amb["longitude"]   # Store ambulance location
                }

        if not best_amb:
            return None

        # 6️⃣ Update DB - Update ambulance, driver, and emergency request status
        cursor.execute("UPDATE ambulances SET status='busy' WHERE ambulance_id=%s", (best_amb["id"],))
        cursor.execute("UPDATE drivers SET status='busy' WHERE driver_id=%s", (best_amb["driver_id"],))
        cursor.execute("UPDATE emergency_requests SET status='assigned' WHERE request_id=%s", (req_id,))
        
        cursor.execute(
            "INSERT INTO dispatch_log (request_id, ambulance_id, distance_km, eta_min) VALUES (%s, %s, %s, %s)",
            (req_id, best_amb["id"], best_amb["distance"], best_amb["eta"])
        )
        
        conn.commit()

        print(f"🚑 ASSIGNED: Ambulance {best_amb['plate']} at ({best_amb['ambulance_lat']}, {best_amb['ambulance_lon']}) to Driver {best_amb['driver_name']}")

        return {
            "success": True,
            "ambulancePlate": best_amb["plate"],
            "distance": best_amb["distance"],
            "eta": best_amb["eta"],
            "driverName": best_amb["driver_name"]
        }

    except Exception as e:
        print("Error in assign_nearest_ambulance:", e)
        traceback.print_exc()
        if conn:
            conn.rollback()
        return None
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# -------------------- Driver Dashboard Routes --------------------
@app.route("/driver_login", methods=["POST"])
def driver_login():
    conn = cursor = None
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Check driver credentials - CORRECTED QUERY
        cursor.execute("""
            SELECT d.*, a.ambulance_id, a.plate_number 
            FROM drivers d 
            JOIN ambulances a ON d.ambulance_id = a.ambulance_id 
            WHERE d.username = %s AND d.password = %s
        """, (username, password))
        
        driver = cursor.fetchone()
        
        if driver:
            # Update driver status to available
            cursor.execute("UPDATE drivers SET status='available' WHERE driver_id=%s", (driver['driver_id'],))
            
            # Update ambulance status to available
            cursor.execute("UPDATE ambulances SET status='available' WHERE ambulance_id=%s", (driver['ambulance_id'],))
            
            conn.commit()
            
            return jsonify({
                'success': True,
                'driver': {
                    'driver_id': driver['driver_id'],
                    'name': driver['name'],
                    'username': driver['username'],
                    'ambulance_id': driver['ambulance_id'],
                    'plate_number': driver['plate_number']
                },
                'token': f"driver_{driver['driver_id']}_{datetime.now().timestamp()}"
            })
        else:
            return jsonify({'success': False, 'error': 'Invalid username or password'})
            
    except Exception as e:
        print("Driver login error:", e)
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Server error during login'})
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/driver_assignment/<int:driver_id>')
def driver_assignment(driver_id):
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get current active assignment for driver - CORRECTED QUERY
        cursor.execute("""
            SELECT 
                dl.dispatch_id,
                er.request_id,
                er.patient_name,
                er.contact_number,
                er.emergency_type,
                er.latitude,
                er.longitude,
                er.notes,
                dl.distance_km,
                dl.eta_min,
                a.plate_number,
                d.name as driver_name
            FROM dispatch_log dl
            JOIN emergency_requests er ON dl.request_id = er.request_id
            JOIN ambulances a ON dl.ambulance_id = a.ambulance_id
            JOIN drivers d ON a.ambulance_id = d.ambulance_id
            WHERE d.driver_id = %s AND dl.completed_at IS NULL
            ORDER BY dl.dispatch_time DESC 
            LIMIT 1
        """, (driver_id,))
        
        assignment = cursor.fetchone()
        
        if assignment:
            return jsonify({
                'hasAssignment': True,
                'emergency': assignment
            })
        else:
            return jsonify({'hasAssignment': False})
            
    except Exception as e:
        print("Driver assignment error:", e)
        traceback.print_exc()
        return jsonify({'hasAssignment': False, 'error': str(e)})
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/complete_emergency', methods=['POST'])
def complete_emergency():
    conn = cursor = None
    try:
        data = request.json
        driver_id = data.get('driver_id')
        dispatch_id = data.get('dispatch_id')
        current_lat = data.get('current_lat')  # New: Driver's current location
        current_lon = data.get('current_lon')  # New: Driver's current location
        
        if not driver_id or not dispatch_id:
            return jsonify({'success': False, 'error': 'Missing driver_id or dispatch_id'})
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Verify the dispatch belongs to this driver - CORRECTED QUERY
        cursor.execute("""
            SELECT dl.dispatch_id, dl.ambulance_id
            FROM dispatch_log dl
            JOIN ambulances a ON dl.ambulance_id = a.ambulance_id
            JOIN drivers d ON a.ambulance_id = d.ambulance_id
            WHERE dl.dispatch_id = %s AND d.driver_id = %s AND dl.completed_at IS NULL
        """, (dispatch_id, driver_id))
        
        valid_dispatch = cursor.fetchone()
        
        if not valid_dispatch:
            return jsonify({'success': False, 'error': 'Invalid dispatch or already completed'})
        
        # Get request_id for this dispatch
        cursor.execute("SELECT request_id FROM dispatch_log WHERE dispatch_id = %s", (dispatch_id,))
        dispatch_data = cursor.fetchone()
        request_id = dispatch_data['request_id'] if dispatch_data else None
        
        # MARK 1: Update ambulance location with driver's current location
        if current_lat and current_lon:
            cursor.execute("""
                UPDATE ambulances 
                SET latitude = %s, longitude = %s 
                WHERE ambulance_id = %s
            """, (current_lat, current_lon, valid_dispatch['ambulance_id']))
            print(f"📍 Updated ambulance location to: ({current_lat}, {current_lon})")
        
        # Mark dispatch as completed
        cursor.execute("UPDATE dispatch_log SET completed_at = NOW() WHERE dispatch_id = %s", (dispatch_id,))
        
        # Update ambulance status to available
        cursor.execute("UPDATE ambulances SET status = 'available' WHERE ambulance_id = %s", (valid_dispatch['ambulance_id'],))
        
        # Update driver status to available
        cursor.execute("UPDATE drivers SET status = 'available' WHERE driver_id = %s", (driver_id,))
        
        # Update emergency request status to completed
        if request_id:
            cursor.execute("UPDATE emergency_requests SET status = 'completed' WHERE request_id = %s", (request_id,))
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Emergency marked as completed and ambulance location updated'
        })
        
    except Exception as e:
        print("Complete emergency error:", e)
        traceback.print_exc()
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/driver_status/<int:driver_id>', methods=['GET'])
def get_driver_status(driver_id):
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT d.status, d.name, a.plate_number 
            FROM drivers d 
            JOIN ambulances a ON d.ambulance_id = a.ambulance_id 
            WHERE d.driver_id = %s
        """, (driver_id,))
        
        driver = cursor.fetchone()
        
        if driver:
            return jsonify({
                'success': True,
                'status': driver['status'],
                'name': driver['name'],
                'plate_number': driver['plate_number']
            })
        else:
            return jsonify({'success': False, 'error': 'Driver not found'})
            
    except Exception as e:
        print("Driver status error:", e)
        return jsonify({'success': False, 'error': str(e)})
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# -------------------- Debug Route --------------------
@app.route("/debug_drivers", methods=['GET'])
def debug_drivers():
    """Debug route to check driver-ambulance relationships"""
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT d.driver_id, d.name as driver_name, d.username, d.status as driver_status,
                   a.ambulance_id, a.plate_number, a.status as ambulance_status,
                   a.latitude, a.longitude
            FROM drivers d 
            JOIN ambulances a ON d.ambulance_id = a.ambulance_id
        """)
        drivers = cursor.fetchall()
        
        return jsonify({'drivers': drivers})
    except Exception as e:
        return jsonify({'error': str(e)})
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# -------------------- Existing Routes --------------------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/book_ambulance", methods=["POST"])
def book_ambulance():
    try:
        data = request.json
        patient_name = data.get("patientName", "Anonymous")
        lat = data.get("lat")
        lon = data.get("lon")
        emergency_type = data.get("emergencyType", "other")
        contact_number = data.get("contactNumber", "")
        notes = data.get("notes", "")
        ip_address = request.remote_addr

        if lat is None or lon is None:
            return jsonify({"success": False, "error": "Missing coordinates"}), 400

        conn = cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """INSERT INTO emergency_requests 
                (patient_name, latitude, longitude, emergency_type, contact_number, notes, ip_address) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (patient_name, lat, lon, emergency_type, contact_number, notes, ip_address)
            )
            conn.commit()
            req_id = cursor.lastrowid
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

        result = assign_nearest_ambulance(req_id)
        if result:
            return jsonify(result)
        else:
            return jsonify({"success": False, "error": "No available ambulance nearby"}), 404

    except Exception as e:
        print("Error in /book_ambulance:", e)
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/ambulances", methods=["GET"])
def get_ambulances():
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT a.*, d.name as driver_name, d.contact_number as driver_contact
            FROM ambulances a 
            JOIN drivers d ON a.ambulance_id = d.ambulance_id
        """)
        data = cursor.fetchall()
        return jsonify(data)
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/requests", methods=["GET"])
def get_requests():
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT er.*, a.plate_number, d.name as driver_name
            FROM emergency_requests er
            LEFT JOIN dispatch_log dl ON er.request_id = dl.request_id
            LEFT JOIN ambulances a ON dl.ambulance_id = a.ambulance_id
            LEFT JOIN drivers d ON a.ambulance_id = d.ambulance_id
            ORDER BY er.request_time DESC
        """)
        data = cursor.fetchall()
        return jsonify(data)
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/drivers", methods=["GET"])
def get_drivers():
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT d.*, a.plate_number, a.status as ambulance_status
            FROM drivers d 
            JOIN ambulances a ON d.ambulance_id = a.ambulance_id
        """)
        data = cursor.fetchall()
        return jsonify(data)
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/active_emergencies", methods=["GET"])
def get_active_emergencies():
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT er.*, a.plate_number, d.name as driver_name, dl.distance_km, dl.eta_min
            FROM emergency_requests er
            JOIN dispatch_log dl ON er.request_id = dl.request_id
            JOIN ambulances a ON dl.ambulance_id = a.ambulance_id
            JOIN drivers d ON a.ambulance_id = d.ambulance_id
            WHERE er.status = 'assigned' AND dl.completed_at IS NULL
            ORDER BY er.request_time DESC
        """)
        data = cursor.fetchall()
        return jsonify(data)
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# -------------------- Run Server --------------------
if __name__ == "__main__":
    app.run(debug=True, threaded=True) 
    
