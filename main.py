from dotenv import load_dotenv
load_dotenv()
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
import os
import json
import sqlite3
import requests
import uuid
import io
import hashlib
import re
from datetime import datetime
from fpdf import FPDF
from flask_session import Session
from functools import wraps
import tempfile

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Gemini API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

# Database setup
def init_db():
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS projects (
        project_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        project_name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS house_details (
        detail_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        detail_type TEXT NOT NULL,
        detail_value TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects (project_id) ON DELETE CASCADE
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS outer_areas (
        area_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        area_type TEXT NOT NULL,
        description TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects (project_id) ON DELETE CASCADE
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS floors (
        floor_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        floor_number INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects (project_id) ON DELETE CASCADE
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rooms (
        room_id TEXT PRIMARY KEY,
        floor_id TEXT NOT NULL,
        room_name TEXT NOT NULL,
        confirmed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (floor_id) REFERENCES floors (floor_id) ON DELETE CASCADE
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS room_details (
        detail_id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL,
        detail_type TEXT NOT NULL,
        detail_value TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms (room_id) ON DELETE CASCADE
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chat_history (
        message_id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL,
        sender TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms (room_id) ON DELETE CASCADE
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS setup_chat_history (
        message_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        sender TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects (project_id) ON DELETE CASCADE
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS room_design_questions (
        question_id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL,
        question_type TEXT NOT NULL,
        answer TEXT,
        is_complete INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms (room_id) ON DELETE CASCADE
    )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return render_template('register.html', error="Invalid email format")
        
        if len(password) < 8:
            return render_template('register.html', error="Password must be at least 8 characters")
        
        conn = sqlite3.connect('housing_assistant.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            conn.close()
            return render_template('register.html', error="Email already registered")
        
        user_id = str(uuid.uuid4())
        hashed_password = hash_password(password)
        
        cursor.execute(
            "INSERT INTO users (user_id, email, password) VALUES (?, ?, ?)",
            (user_id, email, hashed_password)
        )
        conn.commit()
        conn.close()
        
        session['user_id'] = user_id
        session['email'] = email
        return redirect(url_for('dashboard'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        hashed_password = hash_password(password)
        
        conn = sqlite3.connect('housing_assistant.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, email FROM users WHERE email = ? AND password = ?",
            (email, hashed_password)
        )
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['email'] = user[1]
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid credentials")
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT project_id, project_name, created_at FROM projects WHERE user_id = ? ORDER BY created_at DESC",
        (session['user_id'],)
    )
    projects = cursor.fetchall()
    conn.close()
    
    return render_template('dashboard.html', projects=projects)

@app.route('/create-project', methods=['POST'])
@login_required
def create_project():
    project_name = request.form['project_name']
    project_id = str(uuid.uuid4())
    
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO projects (project_id, user_id, project_name) VALUES (?, ?, ?)",
        (project_id, session['user_id'], project_name)
    )
    message_id = str(uuid.uuid4())
    welcome_message = "How many floors would you like for your dream house?"
    cursor.execute(
        "INSERT INTO setup_chat_history (message_id, project_id, sender, message) VALUES (?, ?, ?, ?)",
        (message_id, project_id, "assistant", welcome_message)
    )
    conn.commit()
    conn.close()
    
    return redirect(url_for('project_setup', project_id=project_id))

@app.route('/project/<project_id>/setup', methods=['GET'])
@login_required
def project_setup(project_id):
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT project_id, project_name FROM projects WHERE project_id = ? AND user_id = ?",
        (project_id, session['user_id'])
    )
    project = cursor.fetchone()
    
    if not project:
        conn.close()
        return redirect(url_for('dashboard'))
    
    cursor.execute("""
        SELECT message_id, sender, message, timestamp
        FROM setup_chat_history
        WHERE project_id = ?
        ORDER BY timestamp
    """, (project_id,))
    
    chat_history = cursor.fetchall()
    
    cursor.execute("""
        SELECT detail_type, detail_value
        FROM house_details
        WHERE project_id = ?
    """, (project_id,))
    
    house_details = cursor.fetchall()
    
    cursor.execute("""
        SELECT area_type, description
        FROM outer_areas
        WHERE project_id = ?
    """, (project_id,))
    
    outer_areas = cursor.fetchall()
    
    cursor.execute("""
        SELECT room_name
        FROM rooms
        WHERE floor_id IN (SELECT floor_id FROM floors WHERE project_id = ?)
    """, (project_id,))
    
    rooms = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template('project_setup_chat.html',
                          project_id=project_id,
                          project_name=project[1],
                          chat_history=chat_history,
                          house_details=house_details,
                          outer_areas=outer_areas,
                          rooms=rooms)

@app.route('/api/project/<project_id>/setup-chat', methods=['POST'])
@login_required
def project_setup_chat(project_id):
    user_message = request.json.get('message')
    action = request.json.get('action', None)
    
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT project_name
        FROM projects
        WHERE project_id = ? AND user_id = ?
    """, (project_id, session['user_id']))
    
    project = cursor.fetchone()
    
    if not project:
        conn.close()
        return jsonify({"error": "Unauthorized"}), 403
    
    project_name = project[0]
    
    if user_message:
        message_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO setup_chat_history (message_id, project_id, sender, message) VALUES (?, ?, ?, ?)",
            (message_id, project_id, "user", user_message)
        )
        conn.commit()
    
    cursor.execute("""
        SELECT sender, message
        FROM setup_chat_history
        WHERE project_id = ?
        ORDER BY timestamp
        LIMIT 20
    """, (project_id,))
    
    chat_history = cursor.fetchall()
    
    cursor.execute("""
        SELECT detail_type, detail_value
        FROM house_details
        WHERE project_id = ?
    """, (project_id,))
    
    house_details = {row[0]: row[1] for row in cursor.fetchall()}
    
    cursor.execute("""
        SELECT room_id, room_name
        FROM rooms
        WHERE floor_id IN (SELECT floor_id FROM floors WHERE project_id = ?)
    """, (project_id,))
    
    rooms = cursor.fetchall()
    room_names = [room[1] for room in rooms]
    
    formatted_history = []
    for sender, message in chat_history:
        role = "user" if sender == "user" else "assistant"
        formatted_history.append({"role": role, "parts": [{"text": message}]})
    
    system_instruction = f"""You’re a house design assistant for project '{project_name}'. Your goal is to set up the house by asking ONE question at a time about:
1. Number of floors
2. Architectural style
3. House type
4. Size
5. Plot size
6. Orientation
7. Rooms
8. Outdoor features (only for 'Outer Area')

Rules:
- Ask EXACTLY ONE question, unless 'Finalize' or 'Outer Area' is selected.
- Be conversational, like a designer ensuring the layout fits perfectly.
- If user provides a detail, acknowledge it and ask for another detail or confirm rooms if appropriate.
- If rooms are provided, ask to confirm them (e.g., 'Are you good with {', '.join(room_names) or 'no rooms specified'}?').
- For 'Outer Area', ask about parking, garden, or balconies.
- For 'Finalize', do not ask questions. Instead, generate a summary of only the user-provided details (house, rooms, outdoor features), formatted as a single paragraph, followed by a suggestion to design rooms. Example:
  'Your house is a one-story contemporary modern 1BHK on a 1152 sq ft plot, facing north, with a Bedroom (king-size bed), Kitchen (granite countertops), and a garden with roses. Let’s start designing each room!'
- Include only details explicitly provided by the user in the summary.
- Do not mention unspecified or missing details.

Current details: {', '.join(f'{k}: {v}' for k, v in house_details.items()) or 'None'}.
Rooms: {', '.join(room_names) or 'None'}.
"""

    if action == "outer_area":
        assistant_message = "What outdoor features would you like, such as a garden, parking, or balconies?"
    elif action == "finalize":
        # Collect room details
        room_details_summary = {}
        for room_id, room_name in rooms:
            cursor.execute("""
                SELECT detail_type, detail_value
                FROM room_details
                WHERE room_id = ?
            """, (room_id,))
            room_details = {row[0]: row[1] for row in cursor.fetchall()}
            room_details_summary[room_name] = room_details
        
        cursor.execute("""
            SELECT area_type, description
            FROM outer_areas
            WHERE project_id = ?
        """, (project_id,))
        outer_areas = {row[0]: row[1] for row in cursor.fetchall()}
        
        summary_prompt = f"""Generate a structured summary for project '{project_name}' based on user-provided details only:

House Details:
{json.dumps(house_details, indent=2)}

Rooms and Their Details:
{json.dumps({name: details for name, details in room_details_summary.items()}, indent=2)}

Outdoor Areas:
{json.dumps(outer_areas, indent=2)}

Instructions:
- Structure the summary with sections like the reference report:
  - 1. General Information: House type, number of stories.
  - 2. Rooms & Spaces: Number of bedrooms, bathrooms, additional rooms (e.g., office, gym).
  - 3. Bedroom Specifications: Details for Master Bedroom, other bedrooms (e.g., closets, windows, bathrooms).
  - 4. Office Specifications: Size, features (e.g., desk space, lighting).
  - 5. Gym Specifications: Size, features (e.g., cardio equipment, ventilation).
  - 6. Living & Dining Area: Layout, special features.
  - 7. Kitchen Preferences: Layout, lighting, storage.
  - Overall Summary: A concise, friendly recap with emojis (e.g., 'This multi-story home with a gym and office is going to be amazing! 🏡😍').
- Include only details explicitly provided by the user (e.g., if style is given, include it; if not, omit it).
- Do not mention unspecified, missing, or default details.
- Use bullet points for each section.
- Example:
  '1. General Information
  - House Type: Multi-story
  - Number of Stories: 2
  2. Rooms & Spaces
  - Bedrooms: 3 (Spacious)
  - Bathrooms: 4
  - Additional Rooms: Office, Gym
  3. Bedroom Specifications
  - Master Bedroom: Spacious with a custom wall texture
  - Other Bedrooms: Slightly smaller than master, with closets
  Overall Summary: This multi-story home with a gym and office is going to be amazing! 🏡😍'

Return only the structured summary text."""
        
        payload = {
            "contents": [{"role": "user", "parts": [{"text": summary_prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
        }
        
        try:
            response = requests.post(GEMINI_URL, json=payload)
            response_data = response.json()
            assistant_message = response_data['candidates'][0]['content']['parts'][0]['text']
            
            # Finalize rooms and set up tabs
            cursor.execute("DELETE FROM floors WHERE project_id = ?", (project_id,))
            floor_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO floors (floor_id, project_id, floor_number) VALUES (?, ?, ?)",
                (floor_id, project_id, 1)
            )
            
            for room_id, room_name in rooms:
                cursor.execute(
                    "UPDATE rooms SET floor_id = ?, confirmed = 1 WHERE room_id = ?",
                    (floor_id, room_id)
                )
                cursor.execute("""
                    SELECT message_id
                    FROM chat_history
                    WHERE room_id = ? AND sender = 'assistant'
                """, (room_id,))
                if not cursor.fetchone():
                    message_id = str(uuid.uuid4())
                    cursor.execute(
                        "INSERT INTO chat_history (message_id, room_id, sender, message) VALUES (?, ?, ?, ?)",
                        (message_id, room_id, "assistant", f"What's the overall vibe you're going for in your {room_name}?")
                    )
            
            conn.commit()
            
        except Exception as e:
            print(f"Summary Error: {e}")
            assistant_message = "Sorry, I couldn’t generate the summary. Let’s proceed to room design."
    else:
        if user_message:
            formatted_history.append({"role": "user", "parts": [{"text": user_message}]})
        
        formatted_history.insert(0, {"role": "assistant", "parts": [{"text": system_instruction}]})
        
        payload = {
            "contents": formatted_history,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 100}
        }
        
        try:
            response = requests.post(GEMINI_URL, json=payload)
            response_data = response.json()
            assistant_message = response_data['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            print(f"Gemini Error: {e}")
            assistant_message = "Sorry, I’m having trouble. What’s next for your house?"
        
        if user_message:
            extract_prompt = f"""Based on the user message: '{user_message}', identify house details, rooms, or room-specific details.

Return JSON:
{{
    "house_details": [
        {{
            "detail_type": "plot_size",
            "detail_value": "1152 sq ft"
        }}
    ],
    "rooms": ["Bedroom", "Kitchen"],
    "room_details": [
        {{
            "room_name": "Bedroom",
            "detail_type": "furniture",
            "detail_value": "king-size bed"
        }}
    ]
}}

Only extract explicit details/rooms. Return empty arrays if none."""
            
            extract_payload = {
                "contents": [{"role": "user", "parts": [{"text": extract_prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024}
            }
            
            try:
                extract_response = requests.post(GEMINI_URL, json=extract_payload)
                extract_data = extract_response.json()
                extract_text = extract_data['candidates'][0]['content']['parts'][0]['text']
                json_match = re.search(r'```json\s*(.*?)\s*```', extract_text, re.DOTALL)
                if json_match:
                    extract_text = json_match.group(1)
                details_data = json.loads(extract_text)
                
                for detail in details_data.get('house_details', []):
                    cursor.execute("""
                        SELECT detail_id
                        FROM house_details
                        WHERE project_id = ? AND detail_type = ?
                    """, (project_id, detail['detail_type']))
                    if not cursor.fetchone():
                        detail_id = str(uuid.uuid4())
                        cursor.execute(
                            "INSERT INTO house_details (detail_id, project_id, detail_type, detail_value) VALUES (?, ?, ?, ?)",
                            (detail_id, project_id, detail['detail_type'], detail['detail_value'])
                        )
                
                for room in details_data.get('rooms', []):
                    cursor.execute("""
                        SELECT room_id
                        FROM rooms
                        WHERE floor_id IN (SELECT floor_id FROM floors WHERE project_id = ?) AND room_name = ?
                    """, (project_id, room))
                    if not cursor.fetchone():
                        floor_id = cursor.execute(
                            "SELECT floor_id FROM floors WHERE project_id = ? LIMIT 1", (project_id,)
                        ).fetchone()
                        if not floor_id:
                            floor_id = str(uuid.uuid4())
                            cursor.execute(
                                "INSERT INTO floors (floor_id, project_id, floor_number) VALUES (?, ?, ?)",
                                (floor_id, project_id, 1)
                            )
                        else:
                            floor_id = floor_id[0]
                        room_id = str(uuid.uuid4())
                        cursor.execute(
                            "INSERT INTO rooms (room_id, floor_id, room_name) VALUES (?, ?, ?)",
                            (room_id, floor_id, room)
                        )
                
                for room_detail in details_data.get('room_details', []):
                    cursor.execute("""
                        SELECT room_id
                        FROM rooms
                        WHERE floor_id IN (SELECT floor_id FROM floors WHERE project_id = ?) AND room_name = ?
                    """, (project_id, room_detail['room_name']))
                    room = cursor.fetchone()
                    if room:
                        room_id = room[0]
                        cursor.execute("""
                            SELECT detail_id
                            FROM room_details
                            WHERE room_id = ? AND detail_type = ?
                        """, (room_id, room_detail['detail_type']))
                        if not cursor.fetchone():
                            detail_id = str(uuid.uuid4())
                            cursor.execute(
                                "INSERT INTO room_details (detail_id, room_id, detail_type, detail_value) VALUES (?, ?, ?, ?)",
                                (detail_id, room_id, room_detail['detail_type'], room_detail['detail_value'])
                            )
            
            except Exception as e:
                print(f"Extract Error: {e}")
            
            if any(keyword in user_message.lower() for keyword in ['parking', 'garden', 'balcony']):
                cursor.execute("""
                    SELECT area_id
                    FROM outer_areas
                    WHERE project_id = ? AND description = ?
                """, (project_id, user_message))
                if not cursor.fetchone():
                    area_id = str(uuid.uuid4())
                    area_type = next((k for k in ['parking', 'garden', 'balcony'] if k in user_message.lower()), "other")
                    cursor.execute(
                        "INSERT INTO outer_areas (area_id, project_id, area_type, description) VALUES (?, ?, ?, ?)",
                        (area_id, project_id, area_type, user_message)
                    )
            
            conn.commit()
    
    message_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO setup_chat_history (message_id, project_id, sender, message) VALUES (?, ?, ?, ?)",
        (message_id, project_id, "assistant", assistant_message)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"message": assistant_message})

@app.route('/api/project/<project_id>/confirm-rooms', methods=['POST'])
@login_required
def confirm_rooms(project_id):
    user_message = request.json.get('message', '')
    
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT project_name
        FROM projects
        WHERE project_id = ? AND user_id = ?
    """, (project_id, session['user_id']))
    
    project = cursor.fetchone()
    
    if not project:
        conn.close()
        return jsonify({"error": "Unauthorized"}), 403
    
    project_name = project[0]
    
    cursor.execute("""
        SELECT room_name
        FROM rooms
        WHERE floor_id IN (SELECT floor_id FROM floors WHERE project_id = ?)
    """, (project_id,))
    
    current_rooms = [row[0] for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT sender, message
        FROM setup_chat_history
        WHERE project_id = ?
        ORDER BY timestamp
        LIMIT 20
    """, (project_id,))
    
    chat_history = cursor.fetchall()
    
    formatted_history = []
    for sender, message in chat_history:
        role = "user" if sender == "user" else "assistant"
        formatted_history.append({"role": role, "parts": [{"text": message}]})
    
    if user_message:
        formatted_history.append({"role": "user", "parts": [{"text": user_message}]})
        message_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO setup_chat_history (message_id, project_id, sender, message) VALUES (?, ?, ?, ?)",
            (message_id, project_id, "user", user_message)
        )
        conn.commit()
    
    # Initialize new_rooms as current_rooms before modifications
    new_rooms = current_rooms.copy()
    
    system_instruction = f"""You’re a house design assistant for project '{project_name}'. Current rooms: {', '.join(current_rooms) or 'None'}. Your goal is to confirm the room list or adjust based on user input, then finalize it. Ask ONE question or confirm rooms:

- If user confirms (e.g., 'Yes'), respond: 'Awesome, rooms confirmed: {', '.join(new_rooms)}! Let’s start designing them.'
- If user adjusts (e.g., 'Remove Study Room'), update the list and ask: 'Updated rooms: {{new_rooms}}. Is this final?'
- If no rooms or no input, ask: 'What rooms do you want, like Living Room, Kitchen, Bedroom?'
- After confirmation, set rooms as final.

Return only the response text."""
    
    formatted_history.insert(0, {"role": "assistant", "parts": [{"text": system_instruction}]})
    
    try:
        payload = {
            "contents": formatted_history,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 100}
        }
        response = requests.post(GEMINI_URL, json=payload)
        response_data = response.json()
        assistant_message = response_data['candidates'][0]['content']['parts'][0]['text']
        
        if user_message:
            extract_prompt = f"""Based on user message: '{user_message}', identify rooms to add/remove.

Return JSON:
{{
    "add": ["Bathroom"],
    "remove": ["Study Room"]
}}

Return empty arrays if none."""
            
            extract_payload = {
                "contents": [{"role": "user", "parts": [{"text": extract_prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024}
            }
            
            extract_response = requests.post(GEMINI_URL, json=extract_payload)
            extract_data = extract_response.json()
            extract_text = extract_data['candidates'][0]['content']['parts'][0]['text']
            json_match = re.search(r'```json\s*(.*?)\s*```', extract_text, re.DOTALL)
            if json_match:
                extract_text = json_match.group(1)
            rooms_data = json.loads(extract_text)
            
            floor_id = cursor.execute(
                "SELECT floor_id FROM floors WHERE project_id = ? LIMIT 1", (project_id,)
            ).fetchone()
            if not floor_id:
                floor_id = str(uuid.uuid4())
                cursor.execute(
                    "INSERT INTO floors (floor_id, project_id, floor_number) VALUES (?, ?, ?)",
                    (floor_id, project_id, 1)
                )
            else:
                floor_id = floor_id[0]
            
            # Update new_rooms based on removals and additions
            for room in rooms_data.get('remove', []):
                cursor.execute(
                    "DELETE FROM rooms WHERE floor_id = ? AND room_name = ?",
                    (floor_id, room)
                )
                if room in new_rooms:
                    new_rooms.remove(room)
            
            for room in rooms_data.get('add', []):
                cursor.execute("""
                    SELECT room_id
                    FROM rooms
                    WHERE floor_id = ? AND room_name = ?
                """, (floor_id, room))
                if not cursor.fetchone():
                    room_id = str(uuid.uuid4())
                    cursor.execute(
                        "INSERT INTO rooms (room_id, floor_id, room_name, confirmed) VALUES (?, ?, ?, ?)",
                        (room_id, floor_id, room, 0)
                    )
                    new_rooms.append(room)
            
            # If user confirms, include current rooms
            if user_message.lower().startswith('yes'):
                for room in current_rooms:
                    cursor.execute("""
                        SELECT room_id
                        FROM rooms
                        WHERE floor_id = ? AND room_name = ?
                    """, (floor_id, room))
                    if not cursor.fetchone():
                        room_id = str(uuid.uuid4())
                        cursor.execute(
                            "INSERT INTO rooms (room_id, floor_id, room_name, confirmed) VALUES (?, ?, ?, ?)",
                            (room_id, floor_id, room, 1)
                        )
            
            conn.commit()
            
            # Update system_instruction with new_rooms for the response
            if rooms_data.get('add') or rooms_data.get('remove'):
                system_instruction = f"""You’re a house design assistant for project '{project_name}'. Current rooms: {', '.join(current_rooms) or 'None'}. User modified the room list. Updated rooms: {', '.join(new_rooms) or 'None'}. Respond: 'Updated rooms: {', '.join(new_rooms)}. Is this final?'"""
                formatted_history[-1] = {"role": "assistant", "parts": [{"text": system_instruction}]}
                payload = {
                    "contents": formatted_history,
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 100}
                }
                response = requests.post(GEMINI_URL, json=payload)
                response_data = response.json()
                assistant_message = response_data['candidates'][0]['content']['parts'][0]['text']
            
            if user_message.lower().startswith('yes') or 'confirmed' in assistant_message.lower():
                cursor.execute(
                    "UPDATE rooms SET confirmed = 1 WHERE floor_id IN (SELECT floor_id FROM floors WHERE project_id = ?)",
                    (project_id,)
                )
                conn.commit()
                
                cursor.execute("""
                    SELECT room_id, room_name
                    FROM rooms
                    WHERE floor_id IN (SELECT floor_id FROM floors WHERE project_id = ?)
                """, (project_id,))
                
                for room_id, room_name in cursor.fetchall():
                    message_id = str(uuid.uuid4())
                    cursor.execute(
                        "INSERT INTO chat_history (message_id, room_id, sender, message) VALUES (?, ?, ?, ?)",
                        (message_id, room_id, "assistant", f"What's the overall vibe you're going for in your {room_name}?")
                    )
                
                conn.commit()
        
    except Exception as e:
        print(f"Room Confirm Error: {e}")
        assistant_message = "Sorry, I’m having trouble confirming rooms. What rooms do you want?"
    
    message_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO setup_chat_history (message_id, project_id, sender, message) VALUES (?, ?, ?, ?)",
        (message_id, project_id, "assistant", assistant_message)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"message": assistant_message})

@app.route('/project/<project_id>')
@login_required
def project_view(project_id):
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT project_name FROM projects WHERE project_id = ? AND user_id = ?",
        (project_id, session['user_id'])
    )
    project = cursor.fetchone()
    
    if not project:
        conn.close()
        return redirect(url_for('dashboard'))
    
    cursor.execute("""
        SELECT r.room_id, r.room_name, f.floor_number
        FROM rooms r
        JOIN floors f ON r.floor_id = f.floor_id
        WHERE f.project_id = ? AND r.confirmed = 1
        ORDER BY f.floor_number, r.room_name
    """, (project_id,))
    
    rooms = cursor.fetchall()
    conn.close()
    
    return render_template('project_view.html', 
                          project_id=project_id, 
                          project_name=project[0], 
                          rooms=rooms)

@app.route('/room/<room_id>/chat')
@login_required
def room_chat(room_id):
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT r.room_id, r.room_name, f.floor_number, p.project_id, p.project_name
        FROM rooms r
        JOIN floors f ON r.floor_id = f.floor_id
        JOIN projects p ON f.project_id = p.project_id
        WHERE r.room_id = ? AND p.user_id = ?
    """, (room_id, session['user_id']))
    
    room_info = cursor.fetchone()
    
    if not room_info:
        conn.close()
        return redirect(url_for('dashboard'))
    
    cursor.execute("""
        SELECT message_id, sender, message, timestamp
        FROM chat_history
        WHERE room_id = ?
        ORDER BY timestamp
    """, (room_id,))
    
    chat_history = cursor.fetchall()
    
    cursor.execute("""
        SELECT detail_type, detail_value
        FROM room_details
        WHERE room_id = ?
    """, (room_id,))
    
    room_details = cursor.fetchall()
    
    cursor.execute("""
        SELECT r.room_id, r.room_name, f.floor_number
        FROM rooms r
        JOIN floors f ON r.floor_id = f.floor_id
        WHERE f.project_id = ? AND r.confirmed = 1
        ORDER BY f.floor_number, r.room_name
    """, (room_info[3],))
    
    all_rooms = cursor.fetchall()
    
    conn.close()
    
    return render_template('room_chat.html',
                          room_id=room_id,
                          room_name=room_info[1],
                          floor_number=room_info[2],
                          project_id=room_info[3],
                          project_name=room_info[4],
                          chat_history=chat_history,
                          room_details=room_details,
                          all_rooms=all_rooms)

@app.route('/api/chat/<room_id>', methods=['POST'])
@login_required
def process_message(room_id):
    user_message = request.json.get('message')
    
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT r.room_name, f.floor_number, p.project_name
        FROM rooms r
        JOIN floors f ON r.floor_id = f.floor_id
        JOIN projects p ON f.project_id = p.project_id
        WHERE r.room_id = ? AND p.user_id = ?
    """, (room_id, session['user_id']))
    
    room_info = cursor.fetchone()
    
    if not room_info:
        conn.close()
        return jsonify({"error": "Unauthorized"}), 403
    
    room_name, floor_number, project_name = room_info
    
    message_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO chat_history (message_id, room_id, sender, message) VALUES (?, ?, ?, ?)",
        (message_id, room_id, "user", user_message)
    )
    conn.commit()
    
    # Initialize required details
    required_details = [
        'atmosphere', 'color_scheme', 'style', 'budget', 'activities', 'furniture',
        'lighting', 'textures', 'dimensions', 'storage', 'flooring', 'wall_treatments',
        'windows', 'decor', 'technology', 'accessibility', 'sustainability'
    ]
    
    # Check current state from room_design_questions
    cursor.execute("""
        SELECT question_type, answer, is_complete
        FROM room_design_questions
        WHERE room_id = ?
        ORDER BY created_at
    """, (room_id,))
    design_state = {row[0]: {'answer': row[1], 'is_complete': row[2]} for row in cursor.fetchall()}
    missing_details = [d for d in required_details if d not in design_state or not design_state[d]['is_complete']]
    is_confirmed = any('confirmed' in msg.lower() or 'yes' in msg.lower() for _, msg in cursor.execute("""
        SELECT message FROM chat_history WHERE room_id = ? AND sender = 'user'
    """, (room_id,)).fetchall())
    
    # Check if room design is already initiated
    cursor.execute("""
        SELECT COUNT(*) FROM room_design_questions WHERE room_id = ?
    """, (room_id,))
    design_initiated = cursor.fetchone()[0] > 0
    
    # Enhanced detail extraction
    extract_prompt = f"""Based on user message: '{user_message}', identify design details for the {room_name}. Handle structured input like 'Kitchen: ample shelves, marble sink, ...' by parsing all listed items.

Return JSON:
{{
    "details": [
        {{
            "detail_type": "furniture",
            "detail_value": "king-size bed"
        }},
        {{
            "detail_type": "dimensions",
            "detail_value": "12x12.5ft"
        }}
    ]
}}

Extract ALL explicit details, including from structured formats (e.g., 'Room: detail1, detail2'). Return empty array if none."""
    
    extract_payload = {
        "contents": [{"role": "user", "parts": [{"text": extract_prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024}
    }
    
    try:
        extract_response = requests.post(GEMINI_URL, json=extract_payload)
        extract_data = extract_response.json()
        extract_text = extract_data['candidates'][0]['content']['parts'][0]['text']
        json_match = re.search(r'```json\s*(.*?)\s*```', extract_text, re.DOTALL)
        if json_match:
            extract_text = json_match.group(1)
        details_data = json.loads(extract_text)
        
        for detail in details_data.get('details', []):
            if detail['detail_type'] not in design_state or not design_state[detail['detail_type']]['is_complete']:
                question_id = str(uuid.uuid4())
                cursor.execute(
                    "INSERT INTO room_design_questions (question_id, room_id, question_type, answer, is_complete) VALUES (?, ?, ?, ?, ?)",
                    (question_id, room_id, detail['detail_type'], detail['detail_value'], 1)
                )
                cursor.execute(
                    "INSERT INTO room_details (detail_id, room_id, detail_type, detail_value) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), room_id, detail['detail_type'], detail['detail_value'])
                )
    except Exception as e:
        print(f"Extract Error: {e}")
    
    # Determine next action with session-based tracking
    session.setdefault(f'design_{room_id}', {'last_action': 'start'})
    if session[f'design_{room_id}']['last_action'] == 'confirmed':
        missing_details = []
        is_confirmed = True
    
    if missing_details and not is_confirmed:
        next_detail = missing_details[0]
        current_answers = {k: v['answer'] for k, v in design_state.items() if v['answer']}
        
        system_instruction = f"""You’re an expert interior designer for the {room_name} on floor {floor_number} of project '{project_name}'. Craft a detailed, inspiring question to gather the next design detail for this room. The next detail to ask about is '{next_detail}'. Use the user's prior answers to tailor your suggestion:

- Be conversational and enthusiastic, e.g., 'Love the vibe so far!'.
- Provide creative, style-specific ideas based on prior answers (e.g., if 'modern' style, suggest sleek furniture or minimalist decor).
- Ask ONE question clearly focused on '{next_detail}'.
- Example: If next_detail is 'lighting' and prior answer is 'cozy', respond: 'Love that cozy vibe! How about warm pendant lights or soft recessed lighting to enhance the ambiance? 💡'

Prior answers: {', '.join(f'{k}: {v}' for k, v in current_answers.items()) or 'None'}.
"""
        
        payload = {
            "contents": [{"role": "user", "parts": [{"text": system_instruction}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 150}
        }
        
        try:
            response = requests.post(GEMINI_URL, json=payload)
            response_data = response.json()
            assistant_message = response_data['candidates'][0]['content']['parts'][0]['text']
            session[f'design_{room_id}']['last_action'] = 'question'
        except Exception as e:
            print(f"Gemini Error: {e}")
            assistant_message = f"Sorry, I’m having trouble. What about {next_detail} for your {room_name}?"
    elif not missing_details and not is_confirmed:
        current_answers = {k: v['answer'] for k, v in design_state.items() if v['is_complete']}
        system_instruction = f"""You’re an expert interior designer for the {room_name} on floor {floor_number} of project '{project_name}'. All required details have been provided. Craft a warm, encouraging message to confirm the design:

- Acknowledge the completed design with enthusiasm, e.g., 'Your {room_name} is shaping up beautifully!'.
- List the confirmed details briefly (e.g., 'with a king-size bed and cozy lighting').
- Ask for confirmation with: 'Can we confirm and move to the next room? Say "yes" or "confirmed"!'.
- Example: 'Your bedroom is shaping up beautifully with a king-size bed and cozy lighting! Can we confirm and move to the next room? Say "yes"!'

Confirmed details: {', '.join(f'{k}: {v}' for k, v in current_answers.items()) or 'None'}.
"""
        
        payload = {
            "contents": [{"role": "user", "parts": [{"text": system_instruction}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 150}
        }
        
        try:
            response = requests.post(GEMINI_URL, json=payload)
            response_data = response.json()
            assistant_message = response_data['candidates'][0]['content']['parts'][0]['text']
            session[f'design_{room_id}']['last_action'] = 'confirm'
        except Exception as e:
            print(f"Gemini Error: {e}")
            assistant_message = f"Your {room_name} design looks great! Can we confirm and move to the next room? Say 'yes'."
    else:  # All details complete and confirmed
        cursor.execute("""
            SELECT r.room_id, r.room_name, f.floor_number
            FROM rooms r
            JOIN floors f ON r.floor_id = f.floor_id
            WHERE f.project_id = ? AND r.confirmed = 1 AND r.room_id != ?
            ORDER BY f.floor_number, r.room_name
        """, (room_info[3], room_id))
        next_rooms = cursor.fetchall()
        
        system_instruction = f"""You’re an expert interior designer for the {room_name} on floor {floor_number} of project '{project_name}'. The {room_name} design is complete and confirmed. Craft an enthusiastic message to suggest the next step:

- Celebrate the completion, e.g., 'Awesome, {room_name} is fully designed!'.
- List available next rooms (e.g., 'Next up: Kitchen, Bathroom') or offer to finalize if no rooms remain.
- Ask: 'Want to move to another room or finalize the project? 🏡'
- Example: 'Awesome, bedroom is fully designed! Next up: Kitchen or Bathroom. Want to move to another room or finalize the project? 🏡'

Next rooms: {', '.join(f'{r[1]} (Floor {r[2]})' for r in next_rooms) or 'None'}.
"""
        
        payload = {
            "contents": [{"role": "user", "parts": [{"text": system_instruction}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 150}
        }
        
        try:
            response = requests.post(GEMINI_URL, json=payload)
            response_data = response.json()
            assistant_message = response_data['candidates'][0]['content']['parts'][0]['text']
            session[f'design_{room_id}']['last_action'] = 'completed'
        except Exception as e:
            print(f"Gemini Error: {e}")
            assistant_message = f"Awesome, {room_name} is done! Want to move to another room or finalize? 🏡"
    
    message_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO chat_history (message_id, room_id, sender, message) VALUES (?, ?, ?, ?)",
        (message_id, room_id, "assistant", assistant_message)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"message": assistant_message})

@app.route('/api/project/<project_id>/report', methods=['GET'])
@login_required
def generate_report(project_id):
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT project_name FROM projects WHERE project_id = ? AND user_id = ?",
        (project_id, session['user_id'])
    )
    project = cursor.fetchone()
    
    if not project:
        conn.close()
        return jsonify({"error": "Unauthorized"}), 403
    
    project_name = project[0]
    
    cursor.execute("""
        SELECT detail_type, detail_value
        FROM house_details
        WHERE project_id = ?
    """, (project_id,))
    
    house_details = {d[0]: d[1] for d in cursor.fetchall()}
    
    cursor.execute("""
        SELECT area_type, description
        FROM outer_areas
        WHERE project_id = ?
    """, (project_id,))
    
    outer_areas = {d[0]: d[1] for d in cursor.fetchall()}
    
    cursor.execute("""
        SELECT 
            r.room_id,
            r.room_name
        FROM 
            rooms r
        JOIN floors f ON r.floor_id = f.floor_id
        WHERE 
            f.project_id = ? AND r.confirmed = 1
        ORDER BY r.room_name
    """, (project_id,))
    
    rooms = cursor.fetchall()
    
    room_details_summary = {}
    for room_id, room_name in rooms:
        cursor.execute("""
            SELECT detail_type, detail_value
            FROM room_details
            WHERE room_id = ?
        """, (room_id,))
        room_details = {d[0]: d[1] for d in cursor.fetchall()}
        room_details_summary[room_name] = room_details
    
    summary_prompt = f"""Generate a structured summary for project '{project_name}' based on user-provided details only:

House Details:
{json.dumps(house_details, indent=2)}

Rooms and Their Details:
{json.dumps({name: details for name, details in room_details_summary.items()}, indent=2)}

Outdoor Areas:
{json.dumps(outer_areas, indent=2)}

Instructions:
- Structure the summary with sections like the reference report:
  - 1. General Information: House type, number of stories.
  - 2. Rooms & Spaces: Number of bedrooms, bathrooms, additional rooms (e.g., office, gym).
  - 3. Bedroom Specifications: Details for Master Bedroom, other bedrooms (e.g., closets, windows, bathrooms).
  - 4. Office Specifications: Size, features (e.g., desk space, lighting).
  - 5. Gym Specifications: Size, features (e.g., cardio equipment, ventilation).
  - 6. Living & Dining Area: Layout, special features.
  - 7. Kitchen Preferences: Layout, lighting, storage.
  - Overall Summary: A concise, friendly recap with emojis (e.g., 'This multi-story home with a gym and office is going to be amazing! 🏡😍').
- Include only details explicitly provided by the user (e.g., if style is given, include it; if not, omit it).
- Do not mention unspecified, missing, or default details.
- Use bullet points for each section.
- Example:
  '1. General Information
  - House Type: Multi-story
  - Number of Stories: 2
  2. Rooms & Spaces
  - Bedrooms: 3 (Spacious)
  - Bathrooms: 4
  - Additional Rooms: Office, Gym
  3. Bedroom Specifications
  - Master Bedroom: Spacious with a custom wall texture
  - Other Bedrooms: Slightly smaller than master, with closets
  Overall Summary: This multi-story home with a gym and office is going to be amazing! 🏡😍'

Return only the structured summary text."""
    
    payload = {
        "contents": [{"role": "user", "parts": [{"text": summary_prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
    }
    
    try:
        response = requests.post(GEMINI_URL, json=payload)
        response_data = response.json()
        report_text = response_data['candidates'][0]['content']['parts'][0]['text']
        
        report_text = report_text.encode('ascii', 'ignore').decode('ascii')
        
        pdf = FPDF()
        pdf.add_page()
        
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, f"Summary Report: {project_name}", ln=True, align="C")
        
        pdf.set_font("Arial", "I", 10)
        pdf.cell(0, 10, f"Generated on {datetime.now().strftime('%Y-%m-%d')}", ln=True)
        
        pdf.set_font("Arial", "", 12)
        pdf.multi_cell(0, 10, report_text)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            pdf.output(temp_file.name)
            temp_file_path = temp_file.name
        
        pdf_buffer = io.BytesIO()
        with open(temp_file_path, 'rb') as f:
            pdf_buffer.write(f.read())
        pdf_buffer.seek(0)
        
        os.unlink(temp_file_path)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{project_name}_summary_report.pdf"
        )
        
    except Exception as e:
        print(f"Report Error: {e}")
        return jsonify({"error": "Failed to generate report"}), 500
    finally:
        conn.close()

@app.route('/delete-project/<project_id>', methods=['POST'])
@login_required
def delete_project(project_id):
    conn = sqlite3.connect('housing_assistant.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT project_id FROM projects WHERE project_id = ? AND user_id = ?",
        (project_id, session['user_id'])
    )
    project = cursor.fetchone()
    
    if not project:
        conn.close()
        return jsonify({"error": "Unauthorized or project not found"}), 403
    
    try:
        cursor.execute(
            "DELETE FROM projects WHERE project_id = ?",
            (project_id,)
        )
        conn.commit()
        return jsonify({"success": "Project deleted successfully"})
    except Exception as e:
        conn.rollback()
        print(f"Delete Error: {e}")
        return jsonify({"error": f"Failed to delete project: {str(e)}"}), 500
    finally:
        conn.close()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)