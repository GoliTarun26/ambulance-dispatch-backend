-- Create database
CREATE DATABASE ambulance_dispatch;
USE ambulance_dispatch;
-- Ambulances table
CREATE TABLE ambulances (
    ambulance_id INT AUTO_INCREMENT PRIMARY KEY,
    plate_number VARCHAR(20) UNIQUE NOT NULL,
    latitude FLOAT(9,6) NOT NULL,
    longitude FLOAT(9,6) NOT NULL,
    status ENUM('available', 'busy', 'maintenance') DEFAULT 'available'
);
-- Emergency requests table
CREATE TABLE emergency_requests (
    request_id INT AUTO_INCREMENT PRIMARY KEY,
    patient_name VARCHAR(100),
    latitude DECIMAL(9,6) NOT NULL,
    longitude DECIMAL(9,6) NOT NULL,
    request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status ENUM('pending', 'assigned', 'completed') DEFAULT 'pending'
);

-- Dispatch log
CREATE TABLE dispatch_log (
    dispatch_id INT AUTO_INCREMENT PRIMARY KEY,
    request_id INT,
    ambulance_id INT,
    dispatch_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (request_id) REFERENCES emergency_requests(request_id),
    FOREIGN KEY (ambulance_id) REFERENCES ambulances(ambulance_id)
);

-- Status history (audit trail)
CREATE TABLE status_history (
    history_id INT AUTO_INCREMENT PRIMARY KEY,
    ambulance_id INT,
    old_status ENUM('available','busy','maintenance'),
    new_status ENUM('available','busy','maintenance'),
    change_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ambulance_id) REFERENCES ambulances(ambulance_id)
);

-- Spam tracker table 
CREATE TABLE suspicious_requests (
    suspicious_id INT AUTO_INCREMENT PRIMARY KEY,
    ip_address VARCHAR(45),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reason VARCHAR(255)
);

-- This function calculates distance between two coordinates (in km) Haversine Formula
DELIMITER //
CREATE FUNCTION haversine(lat1 DECIMAL(10,6), lon1 DECIMAL(10,6),
                          lat2 DECIMAL(10,6), lon2 DECIMAL(10,6))
RETURNS DECIMAL(10,6)
DETERMINISTIC
BEGIN
    DECLARE r DECIMAL(10,6);
    SET r = 6371; -- Earth radius in KM
    RETURN r * 2 * ASIN(SQRT(POWER(SIN(RADIANS(lat2 - lat1)/2), 2) +
           COS(RADIANS(lat1)) * COS(RADIANS(lat2)) *
           POWER(SIN(RADIANS(lon2 - lon1)/2), 2)));
END//
DELIMITER ;
-- To Run The Function Globally Through The Database
SHOW FUNCTION STATUS WHERE Db = 'ambulance_dispatch'; 
-- Checking of the haversine formula--
SELECT haversine(17.3850, 78.4867, 16.5062, 80.6480) AS distance_km;
SELECT haversine(17.3850, 78.4867, 17.3850, 78.4867) AS distance_km;

-- Stored Procedure to Assign Nearest Ambulance
DELIMITER //
CREATE PROCEDURE assign_nearest_ambulance(IN req_id INT)
BEGIN
    DECLARE nearest_amb_id INT;

    -- Find the nearest available ambulance
    SELECT ambulance_id INTO nearest_amb_id
    FROM (
        SELECT a.ambulance_id,
               haversine(r.latitude, r.longitude, a.latitude, a.longitude) AS distance_km
        FROM ambulances a
        JOIN emergency_requests r ON r.request_id = req_id
        WHERE a.status = 'available'
        ORDER BY distance_km ASC
        LIMIT 1
    ) AS nearest;

    -- Update ambulance status
    UPDATE ambulances SET status = 'busy' WHERE ambulance_id = nearest_amb_id;

    -- Update request status
    UPDATE emergency_requests SET status = 'assigned' WHERE request_id = req_id;

    -- Log dispatch
    INSERT INTO dispatch_log (request_id, ambulance_id) VALUES (req_id, nearest_amb_id);
END//
DELIMITER ;


ALTER TABLE emergency_requests
ADD COLUMN flagged_for_review BOOLEAN DEFAULT FALSE;

-- procedure to autoflag fake requests
DELIMITER //
CREATE PROCEDURE check_fake_requests(IN user_ip VARCHAR(45), IN lat DECIMAL(9,6), IN lon DECIMAL(9,6))
BEGIN
    DECLARE req_count INT;
    SELECT COUNT(*) INTO req_count
    FROM emergency_requests
    WHERE ip_address = user_ip
      AND request_time >= (NOW() - INTERVAL 5 MINUTE);

    IF req_count >= 3 THEN
        INSERT INTO suspicious_requests (ip_address, latitude, longitude, reason)
        VALUES (user_ip, lat, lon, 'Repeated requests from same IP within 5 minutes');
    END IF;
END//
DELIMITER ;

INSERT INTO ambulances (plate_number, latitude, longitude, status)
VALUES
('AP09AB1234', 16.5062, 80.6480, 'available'),  -- Vijayawada center
('AP09XY5678', 16.5170, 80.6550, 'available'),  -- Near Benz Circle
('AP10CD9101', 16.5300, 80.6200, 'available');  -- Outskirts

select * from ambulances;
-- Add emergency_type as ENUM column to emergency_requests table
ALTER TABLE emergency_requests 
ADD COLUMN emergency_type ENUM(
    'cardiac', 
    'accident', 
    'respiratory', 
    'stroke', 
    'other'
) DEFAULT 'other';

-- Verify the column was added
DESCRIBE emergency_requests;

ALTER TABLE emergency_requests
ADD contact_number VARCHAR(20),
ADD notes TEXT,
ADD ip_address VARCHAR(45);

CREATE INDEX idx_ambulance_status ON ambulances(status);
CREATE INDEX idx_requests_status ON emergency_requests(status);

ALTER TABLE dispatch_log
ADD COLUMN distance_km DECIMAL(6,2) DEFAULT NULL,
ADD COLUMN eta_min INT DEFAULT NULL;

-- Check results
SELECT * FROM ambulances;
SELECT * FROM emergency_requests;
SELECT * FROM dispatch_log;

-- Add drivers table
CREATE TABLE drivers (
    driver_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,  -- Store hashed passwords
    ambulance_id INT,
    name VARCHAR(100) NOT NULL,
    contact_number VARCHAR(20),
    status ENUM('available', 'busy', 'offline') DEFAULT 'offline',
    FOREIGN KEY (ambulance_id) REFERENCES ambulances(ambulance_id)
);

-- Update ambulances table to link with drivers
ALTER TABLE ambulances ADD COLUMN driver_id INT;
ALTER TABLE ambulances ADD FOREIGN KEY (driver_id) REFERENCES drivers(driver_id);

-- Add completion tracking to dispatch_log
ALTER TABLE dispatch_log ADD COLUMN completed_at TIMESTAMP NULL;
ALTER TABLE dispatch_log ADD COLUMN completion_notes TEXT;


-- Insert sample drivers
INSERT INTO drivers (username, password, name, contact_number, ambulance_id, status) VALUES
('driver_raj', 'password123', 'Raj Kumar', '9876543210', 1, 'available'),
('driver_suresh', 'password123', 'Suresh Reddy', '9876543211', 2, 'available'),
('driver_arun', 'password123', 'Arun Varma', '9876543212', 3, 'available');

-- Update ambulances with driver IDs
UPDATE ambulances SET driver_id = 1 WHERE ambulance_id = 1;
UPDATE ambulances SET driver_id = 2 WHERE ambulance_id = 2;
UPDATE ambulances SET driver_id = 3 WHERE ambulance_id = 3;

select * from drivers;





 
