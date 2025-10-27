document.addEventListener('DOMContentLoaded', () => {
    let isProcessing = false;
    let currentDriver = null;
    let checkAssignmentInterval = null;
    let currentAssignment = null;

    // ==================== HELPER FUNCTIONS ====================
    function delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    function updateStatus(message, color) {
        const statusDisplay = document.getElementById('statusDisplay');
        statusDisplay.innerHTML = `
            <div class="status-message">
                <i class="fas fa-info-circle"></i>
                <p style="color: ${color};">${message}</p>
            </div>
        `;
    }

    // ==================== SIDEBAR NAVIGATION ====================
    function initializeSidebar() {
        const sidebar = document.getElementById('sidebar');
        const sidebarOverlay = document.getElementById('sidebarOverlay');
        const menuToggle = document.getElementById('menuToggle');
        const sidebarClose = document.getElementById('sidebarClose');

        menuToggle.addEventListener('click', () => {
            sidebar.classList.add('active');
            sidebarOverlay.classList.add('active');
        });

        sidebarClose.addEventListener('click', () => {
            sidebar.classList.remove('active');
            sidebarOverlay.classList.remove('active');
        });

        sidebarOverlay.addEventListener('click', () => {
            sidebar.classList.remove('active');
            sidebarOverlay.classList.remove('active');
        });

        // Navigation between sections
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const target = item.getAttribute('data-target');
                
                // Update active nav item
                document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active'));
                item.classList.add('active');
                
                // Show target section, hide others
                document.querySelectorAll('.dashboard-section').forEach(section => {
                    section.classList.add('hidden');
                });
                document.getElementById(target).classList.remove('hidden');

                // Close sidebar on mobile after selection
                if (window.innerWidth <= 768) {
                    sidebar.classList.remove('active');
                    sidebarOverlay.classList.remove('active');
                }
            });
        });
    }

    // ==================== DRIVER DASHBOARD FUNCTIONALITY ====================
    function initializeDriverDashboard() {
        // Driver Login
        document.getElementById('driverLoginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const username = document.getElementById('driverUsername').value;
            const password = document.getElementById('driverPassword').value;
            
            try {
                const response = await fetch('/driver_login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    currentDriver = result.driver;
                    localStorage.setItem('driverToken', result.token);
                    showDriverDashboard();
                    startAssignmentChecking();
                } else {
                    alert('Login failed: ' + result.error);
                }
            } catch (error) {
                console.error('Login error:', error);
                alert('Login failed. Please try again.');
            }
        });

        // Complete Emergency Button with Location Update
        document.getElementById('completeBtn').addEventListener('click', async () => {
            if (!currentDriver || !currentAssignment || !confirm('Mark this emergency as completed and update your current location?')) return;
            
            try {
                // Get driver's current location
                const position = await new Promise((resolve, reject) => {
                    navigator.geolocation.getCurrentPosition(resolve, reject, {
                        enableHighAccuracy: true,
                        timeout: 10000,
                        maximumAge: 0
                    });
                });

                const current_lat = position.coords.latitude;
                const current_lon = position.coords.longitude;

                console.log(`📍 Driver current location: ${current_lat}, ${current_lon}`);

                const response = await fetch('/complete_emergency', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        driver_id: currentDriver.driver_id,
                        dispatch_id: currentAssignment.dispatch_id,
                        current_lat: current_lat,  // Send driver's current location
                        current_lon: current_lon   // Send driver's current location
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert('Emergency marked as completed! Your location has been updated.');
                    currentAssignment = null;
                    checkCurrentAssignment(); // Refresh display
                } else {
                    alert('Error: ' + result.error);
                }
            } catch (error) {
                console.error('Error getting location or completing emergency:', error);
                
                // Fallback: Complete without location update
                if (confirm('Unable to get your location. Complete without updating ambulance location?')) {
                    const response = await fetch('/complete_emergency', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ 
                            driver_id: currentDriver.driver_id,
                            dispatch_id: currentAssignment.dispatch_id
                            // No location data
                        })
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        alert('Emergency marked as completed (location not updated).');
                        currentAssignment = null;
                        checkCurrentAssignment();
                    } else {
                        alert('Error: ' + result.error);
                    }
                }
            }
        });

        // Logout Button
        document.getElementById('logoutBtn').addEventListener('click', () => {
            currentDriver = null;
            currentAssignment = null;
            localStorage.removeItem('driverToken');
            if (checkAssignmentInterval) {
                clearInterval(checkAssignmentInterval);
                checkAssignmentInterval = null;
            }
            
            document.getElementById('driver-dashboard').classList.add('hidden');
            document.getElementById('driver-login').classList.remove('hidden');
            document.querySelector('[data-target="user-dashboard"]').classList.add('active');
            document.getElementById('user-dashboard').classList.remove('hidden');
            
            // Reset login form
            document.getElementById('driverLoginForm').reset();
        });
    }

    // Show driver dashboard
    function showDriverDashboard() {
        document.getElementById('driver-login').classList.add('hidden');
        document.getElementById('driver-dashboard').classList.remove('hidden');
        document.querySelector('[data-target="user-dashboard"]').classList.remove('active');
        
        // Update driver status display
        updateDriverStatus();
        checkCurrentAssignment();
    }

    // Check for current assignments
    async function checkCurrentAssignment() {
        if (!currentDriver) return;
        
        try {
            const response = await fetch(`/driver_assignment/${currentDriver.driver_id}`);
            const result = await response.json();
            
            if (result.hasAssignment) {
                currentAssignment = result.emergency;
                displayEmergencyDetails(result.emergency);
                document.getElementById('completeBtn').disabled = false;
                document.getElementById('currentStatus').textContent = 'ON MISSION';
                document.querySelector('.driver-status .status-indicator').className = 'status-indicator busy';
            } else {
                currentAssignment = null;
                document.getElementById('emergencyDetails').innerHTML = '<p>No active emergency assignments</p>';
                document.getElementById('completeBtn').disabled = true;
                document.getElementById('currentStatus').textContent = 'AVAILABLE';
                document.querySelector('.driver-status .status-indicator').className = 'status-indicator available';
            }
        } catch (error) {
            console.error('Error checking assignment:', error);
        }
    }

    // Display emergency details
    function displayEmergencyDetails(emergency) {
        const detailsHtml = `
            <div class="patient-info">
                <div class="info-item">
                    <div class="info-label">Patient Name</div>
                    <div class="info-value">${escapeHtml(emergency.patient_name || 'Anonymous')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Contact Number</div>
                    <div class="info-value">${escapeHtml(emergency.contact_number || 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Emergency Type</div>
                    <div class="info-value">${formatEmergencyType(emergency.emergency_type)}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Distance</div>
                    <div class="info-value">${emergency.distance_km || 'Unknown'} km</div>
                </div>
            </div>
            
            <div class="location-section">
                <div class="info-label">Patient Location</div>
                <a href="https://www.google.com/maps?q=${emergency.latitude},${emergency.longitude}" 
                   target="_blank" class="coordinate-link">
                    <i class="fas fa-map-marker-alt"></i>
                    ${emergency.latitude}, ${emergency.longitude}
                </a>
                <p class="location-address" id="locationAddress">Fetching address...</p>
            </div>
            
            ${emergency.notes ? `
                <div class="notes-section">
                    <div class="info-label">Additional Notes</div>
                    <div class="info-value">${escapeHtml(emergency.notes)}</div>
                </div>
            ` : ''}
        `;
        
        document.getElementById('emergencyDetails').innerHTML = detailsHtml;
        
        // Get address from coordinates
        getAddressFromCoordinates(emergency.latitude, emergency.longitude);
    }

    // Get address from coordinates (reverse geocoding)
    async function getAddressFromCoordinates(lat, lon) {
        try {
            // Using OpenStreetMap Nominatim (free)
            const response = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&zoom=18&addressdetails=1`);
            const data = await response.json();
            
            if (data.display_name) {
                document.getElementById('locationAddress').textContent = data.display_name;
            } else {
                document.getElementById('locationAddress').textContent = 'Address not available';
            }
        } catch (error) {
            console.error('Error fetching address:', error);
            document.getElementById('locationAddress').textContent = 'Error fetching address';
        }
    }

    // Format emergency type
    function formatEmergencyType(type) {
        const types = {
            'cardiac': 'Cardiac Arrest',
            'accident': 'Accident',
            'respiratory': 'Respiratory Distress',
            'stroke': 'Stroke',
            'other': 'Other'
        };
        return types[type] || type;
    }

    // Escape HTML to prevent XSS
    function escapeHtml(unsafe) {
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Update driver status
    function updateDriverStatus() {
        // Implementation for updating driver status in the future
        console.log('Driver status updated');
    }

    // Start checking for assignments
    function startAssignmentChecking() {
        // Check immediately first
        checkCurrentAssignment();
        
        // Then set up interval for continuous checking
        checkAssignmentInterval = setInterval(checkCurrentAssignment, 5000); // Check every 5 seconds
    }

    // ==================== EMERGENCY PROTOCOL ====================
    async function initiateEmergencyProtocol(patientName, contactNumber, notes, lat, lon, emergencyType) {
        if (isProcessing) return;
        isProcessing = true;

        const btn = document.getElementById('book-btn');
        const alertOverlay = document.getElementById('alertOverlay');
        const metricsDashboard = document.getElementById('metricsDashboard');

        btn.disabled = true;
        alertOverlay.classList.add('active');

        updateStatus('INITIATING EMERGENCY PROTOCOL...', '#e74c3c'); await delay(800);
        updateStatus('ACQUIRING GEOLOCATION DATA...', '#e67e22'); await delay(800);
        updateStatus('ANALYZING NEAREST AVAILABLE UNITS...', '#f39c12'); await delay(1200);
        updateStatus('DISPATCHING EMERGENCY UNIT...', '#3498db'); await delay(800);

        try {
            const response = await fetch('/book_ambulance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ patientName, contactNumber, notes, lat, lon, emergencyType })
            });

            const result = await response.json();

            if (result.success) {
                // Show dispatched ambulance info
                document.getElementById('ambulanceId').textContent = result.ambulancePlate || 'N/A';
                document.getElementById('distance').textContent = (result.distance !== undefined ? result.distance + ' km' : '---');
                document.getElementById('eta').textContent = (result.eta !== undefined ? result.eta + ' min' : '---');
                metricsDashboard.classList.add('visible');

                updateStatus(`🚑 UNIT ${result.ambulancePlate} DISPATCHED | DRIVER: ${result.driverName}`, '#2ecc71');
            } else {
                updateStatus(result.error || 'NO AVAILABLE AMBULANCE NEARBY', '#e74c3c');
            }
        } catch (err) {
            console.error(err);
            updateStatus('ERROR BOOKING AMBULANCE. TRY AGAIN', '#e74c3c');
        }

        alertOverlay.classList.remove('active');
        btn.disabled = false;
        isProcessing = false;
    }

    // ==================== BOOK BUTTON HANDLER ====================
    document.getElementById('book-btn').addEventListener('click', () => {
        const patientName = document.getElementById('patientName').value.trim();
        const contactNumber = document.getElementById('contactNumber').value.trim();
        const notes = document.getElementById('notes').value.trim();
        const emergencyType = document.getElementById('emergencyType').value;

        // ===== FORM VALIDATION =====
        const nameRegex = /^[A-Za-z\s]+$/;
        const phoneRegex = /^[0-9]{10}$/;

        if (!patientName || !nameRegex.test(patientName)) {
            alert('⚠️ Please enter a valid name (alphabets only).');
            return;
        }

        if (!phoneRegex.test(contactNumber)) {
            alert('⚠️ Please enter a valid 10-digit contact number.');
            return;
        }

        if (!emergencyType) {
            alert('⚠️ Please select an emergency type.');
            return;
        }

        // ===== GEOLOCATION =====
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    const lat = position.coords.latitude;
                    const lon = position.coords.longitude;
                    document.getElementById('user-lat').value = lat;
                    document.getElementById('user-lon').value = lon;
                    initiateEmergencyProtocol(patientName, contactNumber, notes, lat, lon, emergencyType);
                },
                (error) => alert('Unable to get your location. Please allow location access or enter manually.')
            );
        } else {
            alert('Geolocation not supported by this browser.');
        }
    });

    // ==================== METRICS & STATUS ====================
    function resetForm() {
        document.getElementById('patientName').value = '';
        document.getElementById('contactNumber').value = '';
        document.getElementById('notes').value = '';
        document.getElementById('emergencyType').value = '';
        document.getElementById('user-lat').value = '';
        document.getElementById('user-lon').value = '';
        document.getElementById('ambulanceId').textContent = '---';
        document.getElementById('distance').textContent = '---';
        document.getElementById('eta').textContent = '---';
        document.getElementById('metricsDashboard').classList.remove('visible');
        updateStatus('AWAITING EMERGENCY REQUEST', '#3498db');
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') resetForm();
    });

    // ==================== INITIALIZE ====================
    function initializeApp() {
        // Initialize sidebar navigation
        initializeSidebar();
        
        // Initialize driver dashboard functionality
        initializeDriverDashboard();
        
        // Check if driver was previously logged in
        const savedDriverToken = localStorage.getItem('driverToken');
        if (savedDriverToken) {
            // In a real app, you would verify the token with the backend
            // For now, we'll just show the login page
            localStorage.removeItem('driverToken');
        }

        // Animate cards on load
        const cards = document.querySelectorAll('.card');
        cards.forEach((card, index) => {
            card.style.opacity = '0';
            card.style.transform = 'translateY(20px)';
            setTimeout(() => {
                card.style.transition = 'all 0.6s ease';
                card.style.opacity = '1';
                card.style.transform = 'translateY(0)';
            }, 100 + (index * 200));
        });

        updateStatus('AWAITING EMERGENCY REQUEST', '#3498db');
        console.log('LifeLine Emergency Dispatch System Initialized');
    }

    // Start the application
    initializeApp();
});